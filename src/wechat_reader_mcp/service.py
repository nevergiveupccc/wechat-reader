"""Bounded orchestration for discovery, caching, and article extraction."""

from __future__ import annotations

from typing import Protocol

from wechat_reader_mcp import __version__
from wechat_reader_mcp.discovery.base import DiscoveryProvider, ProviderPage
from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.extraction.fetch import normalize_wechat_article_url
from wechat_reader_mcp.models import (
    AccountCandidate,
    ArticleContent,
    ArticleReadResult,
    BatchReadResponse,
    DiscoveryMode,
    DiscoveryPage,
    DiscoverySource,
    ErrorCode,
    LoginStatus,
    ReaderError,
    ReaderStatus,
)
from wechat_reader_mcp.storage import SqliteStore


class AccountResolver(DiscoveryProvider, Protocol):
    async def resolve_accounts(self, query: str) -> list[AccountCandidate]: ...


class ArticleFetcher(Protocol):
    async def fetch(self, url: str) -> str: ...


class ArticleParser(Protocol):
    def parse(self, url: str, html: str) -> ArticleContent: ...


class BrowserStatusProvider(Protocol):
    def status(self) -> LoginStatus: ...


_DISCOVERY_FALLBACK_CODES = {
    ErrorCode.LOGIN_REQUIRED,
    ErrorCode.LOGIN_EXPIRED,
    ErrorCode.BROWSER_UNAVAILABLE,
    ErrorCode.NO_DISCOVERY_RESULTS,
    ErrorCode.RATE_LIMITED_OR_CAPTCHA,
}
_BROWSER_FETCH_CODES = {
    ErrorCode.UNSUPPORTED_PAGE,
    ErrorCode.RATE_LIMITED_OR_CAPTCHA,
    ErrorCode.NETWORK_ERROR,
    ErrorCode.TIMEOUT,
}


def _selection_error(message: str) -> ReaderException:
    return ReaderException(
        ReaderError(code=ErrorCode.INVALID_SELECTION, message=message)
    )


class ReaderService:
    """Coordinate providers with explicit order and no unbounded retries."""

    def __init__(
        self,
        *,
        store: SqliteStore,
        public_provider: AccountResolver,
        http_fetcher: ArticleFetcher,
        parser: ArticleParser,
        authenticated_provider: DiscoveryProvider | None = None,
        browser_fetcher: ArticleFetcher | None = None,
        browser_session: BrowserStatusProvider | None = None,
        version: str = __version__,
    ) -> None:
        self.store = store
        self.public_provider = public_provider
        self.authenticated_provider = authenticated_provider
        self.http_fetcher = http_fetcher
        self.browser_fetcher = browser_fetcher
        self.parser = parser
        self.browser_session = browser_session
        self.version = version

    async def resolve_account(self, query: str) -> list[AccountCandidate]:
        if not query.strip():
            raise _selection_error("The account query cannot be empty.")
        return await self.public_provider.resolve_accounts(query.strip())

    async def list_recent_articles(
        self,
        account: str,
        limit: int = 10,
        mode: DiscoveryMode = DiscoveryMode.AUTO,
        cursor: str | None = None,
    ) -> DiscoveryPage:
        if not account.strip():
            raise _selection_error("The account name cannot be empty.")
        if not 1 <= limit <= 10:
            raise _selection_error("Article limit must be from 1 to 10.")
        try:
            selected_mode = DiscoveryMode(mode)
        except ValueError as exc:
            raise _selection_error("Discovery mode is invalid.") from exc

        used_fallback = False
        source = DiscoverySource.PUBLIC_SEARCH
        provider_page: ProviderPage
        if selected_mode is DiscoveryMode.PUBLIC:
            provider_page = await self.public_provider.search(account, limit, cursor)
        elif selected_mode is DiscoveryMode.AUTHENTICATED:
            if self.authenticated_provider is None:
                raise ReaderException(
                    ReaderError(
                        code=ErrorCode.LOGIN_REQUIRED,
                        message="Authenticated discovery is not configured.",
                    )
                )
            provider_page = await self.authenticated_provider.search(account, limit, cursor)
            source = DiscoverySource.AUTHENTICATED_SEARCH
        elif self.authenticated_provider is None:
            provider_page = await self.public_provider.search(account, limit, cursor)
        else:
            try:
                provider_page = await self.authenticated_provider.search(
                    account, limit, cursor
                )
                source = DiscoverySource.AUTHENTICATED_SEARCH
            except ReaderException as exc:
                if exc.error.code not in _DISCOVERY_FALLBACK_CODES:
                    raise
                provider_page = await self.public_provider.search(account, limit, cursor)
                source = DiscoverySource.PUBLIC_SEARCH
                used_fallback = True

        normalized = [
            article.model_copy(update={"index": index})
            for index, article in enumerate(provider_page.articles[:limit], 1)
        ]
        if normalized:
            source = normalized[0].source
        result_set_id = self.store.save_result_set(normalized)
        warning = provider_page.warning
        if used_fallback:
            fallback_warning = "Authenticated discovery failed; fallback used public search."
            warning = f"{fallback_warning} {warning}" if warning else fallback_warning
        return DiscoveryPage(
            result_set_id=result_set_id,
            account=normalized[0].account if normalized else account.strip(),
            requested=limit,
            returned=len(normalized),
            discovery_source=source,
            is_complete=provider_page.is_complete,
            articles=normalized,
            warning=warning,
            next_cursor=provider_page.next_cursor,
        )

    async def _extract_article(self, normalized_url: str) -> ArticleContent:
        try:
            html = await self.http_fetcher.fetch(normalized_url)
            article = self.parser.parse(normalized_url, html)
        except ReaderException as first_error:
            if (
                self.browser_fetcher is None
                or first_error.error.code not in _BROWSER_FETCH_CODES
            ):
                raise
            browser_html = await self.browser_fetcher.fetch(normalized_url)
            article = self.parser.parse(normalized_url, browser_html)
        self.store.put_article(article)
        return article

    async def read_article_url(self, url: str) -> ArticleReadResult:
        display_url = url.strip() or "invalid-url"
        try:
            normalized = normalize_wechat_article_url(url)
            cached = self.store.get_article(normalized)
            article = cached or await self._extract_article(normalized)
            return ArticleReadResult(url=normalized, article=article)
        except ReaderException as exc:
            return ArticleReadResult(url=display_url, error=exc.error)

    async def read_selected_articles(
        self, result_set_id: str, selections: list[int]
    ) -> BatchReadResponse:
        if not 1 <= len(selections) <= 10:
            raise _selection_error("Select from one to ten articles.")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in selections):
            raise _selection_error("Every selection must be an integer index.")
        if any(value <= 0 for value in selections):
            raise _selection_error("Every selection must be positive.")
        if len(set(selections)) != len(selections):
            raise _selection_error("Selections must be unique.")

        articles = self.store.get_result_set(result_set_id)
        if any(index > len(articles) for index in selections):
            raise _selection_error("A selection is outside the stored result set.")

        results: list[ArticleReadResult] = []
        for index in selections:
            result = await self.read_article_url(articles[index - 1].url)
            results.append(result.model_copy(update={"index": index}))
        return BatchReadResponse(result_set_id=result_set_id, results=results)

    def get_status(self) -> ReaderStatus:
        browser_status = self.browser_session.status() if self.browser_session else None
        providers = [DiscoverySource.PUBLIC_SEARCH, DiscoverySource.DIRECT_URL]
        if self.authenticated_provider is not None:
            providers.append(DiscoverySource.AUTHENTICATED_SEARCH)
        return ReaderStatus(
            version=self.version,
            cache_available=True,
            browser_available=(browser_status.browser_available if browser_status else False),
            login_status=(browser_status.state if browser_status else "not_configured"),
            providers=providers,
        )
