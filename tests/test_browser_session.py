from pathlib import Path

import pytest

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import ErrorCode


class FakePage:
    def __init__(
        self,
        html: str = "<html>page</html>",
        *,
        final_url: str | None = None,
    ) -> None:
        self.html = html
        self.final_url = final_url
        self.url = "about:blank"
        self.visited: list[str] = []
        self.network_requests: list[str] = []
        self.main_frame = object()
        self._route_handler = None

    async def goto(self, url: str, **kwargs: object) -> None:
        self.visited.append(url)
        targets = [url]
        if self.final_url is not None and self.final_url != url:
            targets.append(self.final_url)
        for target in targets:
            if self._route_handler is not None:
                request = FakeRequest(target, self.main_frame)
                route = FakeRoute(target, self.network_requests)
                await self._route_handler(route, request)
                if route.aborted:
                    raise RuntimeError("navigation was blocked")
            else:
                self.network_requests.append(target)
        self.url = self.final_url or url

    async def route(self, pattern: str, handler: object) -> None:
        assert pattern == "**/*"
        self._route_handler = handler

    async def wait_for_selector(self, selector: str, **kwargs: object) -> None:
        assert selector

    async def content(self) -> str:
        return self.html


class FakeRequest:
    def __init__(self, url: str, frame: object) -> None:
        self.url = url
        self.frame = frame

    def is_navigation_request(self) -> bool:
        return True


class FakeRoute:
    def __init__(self, url: str, requests: list[str]) -> None:
        self.url = url
        self.requests = requests
        self.aborted = False

    async def continue_(self) -> None:
        self.requests.append(self.url)

    async def abort(self, **kwargs: object) -> None:
        self.aborted = True


class FakeContext:
    def __init__(self, page: FakePage, *, cookies: list[dict[str, str]] | None = None) -> None:
        self.pages = [page]
        self.closed = False
        self._cookies = cookies or [{"name": "wr_skey", "value": "test-only"}]

    async def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed = True

    async def cookies(self, *urls: str) -> list[dict[str, str]]:
        assert urls == ("https://weread.qq.com/",)
        return self._cookies


class FakeChromium:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.calls: list[dict[str, object]] = []

    async def launch_persistent_context(self, **kwargs: object) -> FakeContext:
        self.calls.append(kwargs)
        return self.context


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium


class FakePlaywrightManager:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    async def __aenter__(self) -> FakePlaywright:
        return self.playwright

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_login_uses_managed_profile_and_returns_no_secrets(tmp_path: Path) -> None:
    from wechat_reader_mcp.browser.session import BrowserSessionManager

    profile = tmp_path / "data" / "browser-profile"
    context = FakeContext(FakePage())
    chromium = FakeChromium(context)
    factory = lambda: FakePlaywrightManager(FakePlaywright(chromium))
    manager = BrowserSessionManager(profile, playwright_factory=factory)

    status = await manager.login(timeout_seconds=5)
    payload = status.model_dump(mode="json")

    assert chromium.calls[0]["user_data_dir"] == str(profile)
    assert chromium.calls[0]["headless"] is False
    assert context.pages[0].visited == ["https://weread.qq.com/"]
    assert status.authenticated is True
    assert context.closed is True
    serialized = str(payload).lower()
    assert "cookie" not in serialized
    assert "browser-profile" not in serialized
    assert str(tmp_path).lower() not in serialized


def test_logout_removes_only_the_exact_managed_profile(tmp_path: Path) -> None:
    from wechat_reader_mcp.browser.session import BrowserSessionManager

    profile = tmp_path / "data" / "browser-profile"
    sibling = tmp_path / "data" / "keep-me"
    profile.mkdir(parents=True)
    sibling.mkdir(parents=True)
    (profile / "browser.db").write_text("local state", encoding="utf-8")
    (sibling / "important.txt").write_text("keep", encoding="utf-8")

    BrowserSessionManager(profile).logout()

    assert not profile.exists()
    assert (sibling / "important.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_browser_article_fetcher_validates_url_before_navigation(tmp_path: Path) -> None:
    from wechat_reader_mcp.browser.session import BrowserSessionManager
    from wechat_reader_mcp.extraction.fetch import BrowserArticleFetcher

    page = FakePage("<html>article</html>")
    chromium = FakeChromium(FakeContext(page))
    factory = lambda: FakePlaywrightManager(FakePlaywright(chromium))
    manager = BrowserSessionManager(
        tmp_path / "data" / "browser-profile", playwright_factory=factory
    )

    html = await BrowserArticleFetcher(manager).fetch(
        "https://mp.weixin.qq.com/s/browser-article"
    )

    assert html == "<html>article</html>"
    assert page.visited == ["https://mp.weixin.qq.com/s/browser-article"]


@pytest.mark.asyncio
async def test_browser_article_fetcher_rejects_cross_host_final_url(tmp_path: Path) -> None:
    from wechat_reader_mcp.browser.session import BrowserSessionManager
    from wechat_reader_mcp.extraction.fetch import BrowserArticleFetcher

    page = FakePage(
        "<html>external</html>",
        final_url="https://example.com/not-wechat",
    )
    chromium = FakeChromium(FakeContext(page))
    factory = lambda: FakePlaywrightManager(FakePlaywright(chromium))
    manager = BrowserSessionManager(
        tmp_path / "data" / "browser-profile", playwright_factory=factory
    )

    with pytest.raises(ReaderException) as caught:
        await BrowserArticleFetcher(manager).fetch(
            "https://mp.weixin.qq.com/s/browser-article"
        )
    assert caught.value.error.code is ErrorCode.UNSUPPORTED_URL
    assert "https://example.com/not-wechat" not in page.network_requests
