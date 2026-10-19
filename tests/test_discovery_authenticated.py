from pathlib import Path

import pytest

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import DiscoverySource, ErrorCode

FIXTURE = (Path(__file__).parent / "fixtures" / "weread_results.html").read_text(
    encoding="utf-8"
)


class FixtureSession:
    def __init__(self, html: str) -> None:
        self.html = html
        self.urls: list[str] = []

    async def page_content(self, url: str) -> str:
        self.urls.append(url)
        return self.html


@pytest.mark.asyncio
async def test_authenticated_results_are_sorted_capped_and_attributed() -> None:
    from wechat_reader_mcp.discovery.authenticated import WeReadDiscoveryProvider

    provider = WeReadDiscoveryProvider(FixtureSession(FIXTURE))
    page = await provider.search("Alpha Lab", limit=10)

    assert len(page.articles) == 10
    assert [item.title for item in page.articles[:2]] == ["Newest", "Second"]
    assert all(item.account == "Alpha Lab" for item in page.articles)
    assert all(
        item.source is DiscoverySource.AUTHENTICATED_SEARCH
        for item in page.articles
    )
    assert page.articles[0].url == "https://mp.weixin.qq.com/s/auth-1"
    assert page.is_complete is False
    assert page.next_cursor is not None


@pytest.mark.asyncio
async def test_authenticated_search_requires_login_marker() -> None:
    from wechat_reader_mcp.discovery.authenticated import WeReadDiscoveryProvider

    logged_out = FIXTURE.replace(' data-authenticated="true"', "")
    provider = WeReadDiscoveryProvider(FixtureSession(logged_out))

    with pytest.raises(ReaderException) as caught:
        await provider.search("Alpha Lab", limit=10)
    assert caught.value.error.code is ErrorCode.LOGIN_REQUIRED


@pytest.mark.asyncio
async def test_authenticated_search_rejects_captcha_without_retrying() -> None:
    from wechat_reader_mcp.discovery.authenticated import WeReadDiscoveryProvider

    session = FixtureSession("<html><body>请完成验证后继续访问</body></html>")
    provider = WeReadDiscoveryProvider(session)

    with pytest.raises(ReaderException) as caught:
        await provider.search("Alpha Lab", limit=10)
    assert caught.value.error.code is ErrorCode.RATE_LIMITED_OR_CAPTCHA
    assert len(session.urls) == 1
