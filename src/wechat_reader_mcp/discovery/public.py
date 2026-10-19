"""Best-effort public discovery through Sogou's publicly visible result pages."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from wechat_reader_mcp.discovery.base import ProviderPage
from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.extraction.fetch import normalize_wechat_article_url
from wechat_reader_mcp.models import (
    AccountCandidate,
    ArticleSummary,
    DiscoverySource,
    ErrorCode,
    ReaderError,
)

_SEARCH_ORIGIN = "https://weixin.sogou.com"
_SEARCH_URL = f"{_SEARCH_ORIGIN}/weixin"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


def _error(code: ErrorCode, message: str, **details: object) -> ReaderException:
    return ReaderException(
        ReaderError(
            code=code,
            message=message,
            details=details or None,
        )
    )


class SearchTransport(Protocol):
    async def fetch(self, account: str, page: int) -> str: ...


class UrlResolver(Protocol):
    async def resolve(self, url: str) -> str | None: ...


class HttpSearchTransport:
    """Bounded network adapter for a public search results page."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def fetch(self, account: str, page: int) -> str:
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=httpx.Timeout(15, connect=5),
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params={"type": "2", "query": account, "page": str(page)},
                )
        except httpx.TimeoutException as exc:
            raise _error(ErrorCode.TIMEOUT, "Public search timed out.") from exc
        except httpx.HTTPError as exc:
            raise _error(ErrorCode.NETWORK_ERROR, "Public search could not be loaded.") from exc
        if response.status_code in (403, 429):
            raise _error(
                ErrorCode.RATE_LIMITED_OR_CAPTCHA,
                "Public search requested verification or limited the request.",
            )
        if response.is_error:
            raise _error(
                ErrorCode.NETWORK_ERROR,
                f"Public search returned HTTP {response.status_code}.",
            )
        return response.text


class SogouUrlResolver:
    """Resolve only bounded Sogou redirects to validated WeChat article URLs."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_redirects: int = 3,
    ) -> None:
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        self.transport = transport
        self.max_redirects = max_redirects

    async def resolve(self, url: str) -> str | None:
        current = url
        redirects = 0
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=httpx.Timeout(10, connect=5),
            follow_redirects=False,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            while True:
                try:
                    return normalize_wechat_article_url(current)
                except ReaderException:
                    pass
                parsed = urlsplit(current)
                if parsed.scheme != "https" or parsed.hostname != "weixin.sogou.com":
                    return None
                if redirects >= self.max_redirects:
                    return None
                try:
                    response = await client.get(current)
                except httpx.HTTPError:
                    return None
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        return None
                    current = urljoin(current, location)
                    redirects += 1
                    continue
                return None


@dataclass(slots=True)
class _RawResult:
    title: str
    account: str
    url: str
    published_at: datetime | None
    digest: str | None


def _page_to_cursor(page: int) -> str:
    return base64.urlsafe_b64encode(f"sogou:{page}".encode()).decode().rstrip("=")


def _cursor_to_page(cursor: str | None) -> int:
    if cursor is None:
        return 1
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = base64.urlsafe_b64decode(padded).decode()
        prefix, raw_page = value.split(":", 1)
        page = int(raw_page)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _error(ErrorCode.INVALID_SELECTION, "The public-search cursor is invalid.") from exc
    if prefix != "sogou" or page < 1:
        raise _error(ErrorCode.INVALID_SELECTION, "The public-search cursor is invalid.")
    return page


def _parse_timestamp(node: Tag) -> datetime | None:
    raw = node.get("data-ts")
    if isinstance(raw, str) and raw.isdigit():
        return datetime.fromtimestamp(int(raw), UTC)
    text = node.get_text(" ", strip=True)
    for format_string in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, format_string).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def _parse_results(html: str) -> tuple[list[_RawResult], bool]:
    soup = BeautifulSoup(html, "lxml")
    results: list[_RawResult] = []
    for item in soup.select("ul.news-list > li"):
        link = item.select_one("h3 a")
        account_node = item.select_one(".s-p .account, .s-p a")
        if not isinstance(link, Tag) or not isinstance(account_node, Tag):
            continue
        href = link.get("href")
        title = link.get_text(" ", strip=True)
        account = account_node.get_text(" ", strip=True)
        if not isinstance(href, str) or not title or not account:
            continue
        date_node = item.select_one(".s2")
        digest_node = item.select_one(".txt-info")
        results.append(
            _RawResult(
                title=title,
                account=account,
                url=urljoin(_SEARCH_ORIGIN, href),
                published_at=(
                    _parse_timestamp(date_node) if isinstance(date_node, Tag) else None
                ),
                digest=(digest_node.get_text(" ", strip=True) if digest_node else None),
            )
        )
    return results, soup.select_one(".p-fy #sogou_next") is not None


class SogouDiscoveryProvider:
    """A best-effort source; results are never represented as exhaustive."""

    def __init__(
        self,
        *,
        transport: SearchTransport | None = None,
        resolver: UrlResolver | None = None,
    ) -> None:
        self.transport = transport or HttpSearchTransport()
        self.resolver = resolver or SogouUrlResolver()

    async def resolve_accounts(self, query: str) -> list[AccountCandidate]:
        if not query.strip():
            raise _error(ErrorCode.INVALID_SELECTION, "The account query cannot be empty.")
        html = await self.transport.fetch(query.strip(), 1)
        raw_results, _ = _parse_results(html)
        lowered = query.casefold().strip()
        names = sorted(
            {item.account for item in raw_results if lowered in item.account.casefold()},
            key=str.casefold,
        )
        return [
            AccountCandidate(
                name=name,
                account_ref=name,
                source=DiscoverySource.PUBLIC_SEARCH,
                confidence=1.0 if name.casefold() == lowered else 0.7,
            )
            for name in names
        ]

    async def search(
        self, account: str, limit: int, cursor: str | None = None
    ) -> ProviderPage:
        if not 1 <= limit <= 10:
            raise _error(ErrorCode.INVALID_SELECTION, "Article limit must be from 1 to 10.")
        if not account.strip():
            raise _error(ErrorCode.INVALID_SELECTION, "The account name cannot be empty.")
        page_number = _cursor_to_page(cursor)
        html = await self.transport.fetch(account.strip(), page_number)
        raw_results, has_next = _parse_results(html)

        exact = [item for item in raw_results if item.account.casefold() == account.casefold()]
        if not exact:
            matching_names = sorted(
                {
                    item.account
                    for item in raw_results
                    if account.casefold() in item.account.casefold()
                },
                key=str.casefold,
            )
            if len(matching_names) > 1:
                raise _error(
                    ErrorCode.AMBIGUOUS_ACCOUNT,
                    "More than one public account matched the query.",
                    candidates=matching_names,
                )
            if len(matching_names) == 1:
                exact = [item for item in raw_results if item.account == matching_names[0]]
        if not exact:
            raise _error(ErrorCode.NO_DISCOVERY_RESULTS, "No public articles were found.")

        exact.sort(
            key=lambda item: item.published_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        articles: list[ArticleSummary] = []
        seen: set[str] = set()
        unresolved = 0
        for item in exact:
            resolved = await self.resolver.resolve(item.url)
            final_url = resolved or item.url
            if final_url in seen:
                continue
            seen.add(final_url)
            if resolved is None:
                unresolved += 1
            articles.append(
                ArticleSummary(
                    index=len(articles) + 1,
                    title=item.title,
                    url=final_url,
                    account=item.account,
                    published_at=item.published_at,
                    digest=item.digest,
                    source=DiscoverySource.PUBLIC_SEARCH,
                )
            )
            if len(articles) == limit:
                break

        warning = "Public search is best-effort and may be incomplete."
        if unresolved:
            warning += f" {unresolved} result link was unresolved and kept as returned."
        return ProviderPage(
            articles=articles,
            next_cursor=_page_to_cursor(page_number + 1) if has_next else None,
            is_complete=False,
            warning=warning,
        )
