from pathlib import Path

import pytest

from wechat_reader_mcp.discovery.base import ProviderPage
from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import (
    AccountCandidate,
    ArticleContent,
    ArticleSummary,
    DiscoveryMode,
    DiscoverySource,
    ErrorCode,
    ReaderError,
)
from wechat_reader_mcp.storage import SqliteStore


def _summary(index: int, source: DiscoverySource) -> ArticleSummary:
    return ArticleSummary(
        index=index,
        title=f"Article {index}",
        account="Alpha Lab",
        url=f"https://mp.weixin.qq.com/s/article-{index}",
        source=source,
    )


def _article(url: str = "https://mp.weixin.qq.com/s/article-1") -> ArticleContent:
    return ArticleContent(
        title="Readable",
        account="Alpha Lab",
        url=url,
        markdown="Readable body",
    )


def _exception(code: ErrorCode) -> ReaderException:
    return ReaderException(
        ReaderError(code=code, message=f"failure: {code.value}", retryable=True)
    )


class FakeProvider:
    def __init__(
        self,
        source: DiscoverySource,
        *,
        failure: ReaderException | None = None,
    ) -> None:
        self.source = source
        self.failure = failure
        self.calls = 0

    async def search(
        self, account: str, limit: int, cursor: str | None = None
    ) -> ProviderPage:
        self.calls += 1
        if self.failure:
            raise self.failure
        return ProviderPage(
            articles=[_summary(1, self.source)],
            is_complete=False,
            warning=f"{self.source.value} warning",
        )

    async def resolve_accounts(self, query: str) -> list[AccountCandidate]:
        return [
            AccountCandidate(
                name="Alpha Lab",
                account_ref="Alpha Lab",
                source=self.source,
            )
        ]


class FakeFetcher:
    def __init__(self, result: str | ReaderException) -> None:
        self.result = result
        self.calls = 0

    async def fetch(self, url: str) -> str:
        self.calls += 1
        if isinstance(self.result, ReaderException):
            raise self.result
        return self.result


class FakeParser:
    def __init__(self, result: ArticleContent | ReaderException) -> None:
        self.result = result
        self.calls = 0

    def parse(self, url: str, html: str) -> ArticleContent:
        self.calls += 1
        if isinstance(self.result, ReaderException):
            raise self.result
        return self.result


def _service(
    tmp_path: Path,
    *,
    public: FakeProvider | None = None,
    authenticated: FakeProvider | None = None,
    http: FakeFetcher | None = None,
    browser: FakeFetcher | None = None,
    parser: FakeParser | None = None,
):
    from wechat_reader_mcp.service import ReaderService

    return ReaderService(
        store=SqliteStore(tmp_path / "cache.sqlite3"),
        public_provider=public or FakeProvider(DiscoverySource.PUBLIC_SEARCH),
        authenticated_provider=authenticated,
        http_fetcher=http or FakeFetcher("html"),
        browser_fetcher=browser,
        parser=parser or FakeParser(_article()),
    )


@pytest.mark.asyncio
async def test_auto_prefers_authenticated_and_saves_exact_result_set(tmp_path: Path) -> None:
    public = FakeProvider(DiscoverySource.PUBLIC_SEARCH)
    authenticated = FakeProvider(DiscoverySource.AUTHENTICATED_SEARCH)
    service = _service(tmp_path, public=public, authenticated=authenticated)

    page = await service.list_recent_articles("Alpha Lab", mode=DiscoveryMode.AUTO)

    assert authenticated.calls == 1
    assert public.calls == 0
    assert page.discovery_source is DiscoverySource.AUTHENTICATED_SEARCH
    assert service.store.get_result_set(page.result_set_id) == page.articles


@pytest.mark.asyncio
async def test_auto_falls_back_once_on_login_required_and_discloses_source(
    tmp_path: Path,
) -> None:
    public = FakeProvider(DiscoverySource.PUBLIC_SEARCH)
    authenticated = FakeProvider(
        DiscoverySource.AUTHENTICATED_SEARCH,
        failure=_exception(ErrorCode.LOGIN_REQUIRED),
    )
    service = _service(tmp_path, public=public, authenticated=authenticated)

    page = await service.list_recent_articles("Alpha Lab", mode=DiscoveryMode.AUTO)

    assert authenticated.calls == 1
    assert public.calls == 1
    assert page.discovery_source is DiscoverySource.PUBLIC_SEARCH
    assert page.warning is not None and "fallback" in page.warning.lower()


@pytest.mark.asyncio
async def test_auto_never_falls_back_for_invalid_user_input(tmp_path: Path) -> None:
    public = FakeProvider(DiscoverySource.PUBLIC_SEARCH)
    authenticated = FakeProvider(
        DiscoverySource.AUTHENTICATED_SEARCH,
        failure=_exception(ErrorCode.INVALID_SELECTION),
    )
    service = _service(tmp_path, public=public, authenticated=authenticated)

    with pytest.raises(ReaderException) as caught:
        await service.list_recent_articles("Alpha Lab", mode=DiscoveryMode.AUTO)
    assert caught.value.error.code is ErrorCode.INVALID_SELECTION
    assert public.calls == 0


@pytest.mark.asyncio
async def test_article_cache_hit_avoids_network_and_parser(tmp_path: Path) -> None:
    http = FakeFetcher("should not be used")
    parser = FakeParser(_article())
    service = _service(tmp_path, http=http, parser=parser)
    article = _article()
    service.store.put_article(article)

    result = await service.read_article_url(article.url)

    assert result.article == article
    assert http.calls == 0
    assert parser.calls == 0


@pytest.mark.asyncio
async def test_http_extraction_failure_uses_browser_once_and_caches(tmp_path: Path) -> None:
    http = FakeFetcher("http html")
    browser = FakeFetcher("browser html")

    class FallbackParser:
        def __init__(self) -> None:
            self.calls = 0

        def parse(self, url: str, html: str) -> ArticleContent:
            self.calls += 1
            if html == "http html":
                raise _exception(ErrorCode.UNSUPPORTED_PAGE)
            return _article(url)

    parser = FallbackParser()
    service = _service(tmp_path, http=http, browser=browser, parser=parser)

    result = await service.read_article_url("https://mp.weixin.qq.com/s/article-1")

    assert result.article is not None
    assert http.calls == 1
    assert browser.calls == 1
    assert parser.calls == 2
    assert service.store.get_article(result.article.url) == result.article


@pytest.mark.asyncio
async def test_captcha_failure_does_not_loop_browser_fallback(tmp_path: Path) -> None:
    http = FakeFetcher(_exception(ErrorCode.RATE_LIMITED_OR_CAPTCHA))
    browser = FakeFetcher(_exception(ErrorCode.RATE_LIMITED_OR_CAPTCHA))
    service = _service(tmp_path, http=http, browser=browser)

    result = await service.read_article_url("https://mp.weixin.qq.com/s/article-1")

    assert result.error is not None
    assert result.error.code is ErrorCode.RATE_LIMITED_OR_CAPTCHA
    assert http.calls == 1
    assert browser.calls == 1


@pytest.mark.asyncio
async def test_batch_read_preserves_success_and_per_item_failure(tmp_path: Path) -> None:
    class PerUrlFetcher:
        async def fetch(self, url: str) -> str:
            if url.endswith("article-2"):
                raise _exception(ErrorCode.ARTICLE_UNAVAILABLE)
            return "html"

    service = _service(tmp_path, http=PerUrlFetcher())
    result_set_id = service.store.save_result_set(
        [
            _summary(1, DiscoverySource.PUBLIC_SEARCH),
            _summary(2, DiscoverySource.PUBLIC_SEARCH),
        ]
    )

    response = await service.read_selected_articles(result_set_id, [1, 2])

    assert response.results[0].article is not None
    assert response.results[1].error is not None
    assert response.results[1].error.code is ErrorCode.ARTICLE_UNAVAILABLE
