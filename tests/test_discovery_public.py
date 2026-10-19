from pathlib import Path
import httpx
import pytest

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import DiscoverySource, ErrorCode

FIXTURE = (Path(__file__).parent / "fixtures" / "sogou_results.html").read_text(
    encoding="utf-8"
)


class FixtureTransport:
    def __init__(self) -> None:
        self.pages: list[int] = []

    async def fetch(self, account: str, page: int) -> str:
        assert account
        self.pages.append(page)
        return FIXTURE


class MappingResolver:
    async def resolve(self, url: str) -> str | None:
        token = url.split("=")[-1]
        if token == "missing":
            return None
        if token == "dup":
            token = "a2"
        return f"https://mp.weixin.qq.com/s/{token}"


@pytest.mark.asyncio
async def test_public_search_caps_sorts_deduplicates_and_warns() -> None:
    from wechat_reader_mcp.discovery.public import SogouDiscoveryProvider

    provider = SogouDiscoveryProvider(
        transport=FixtureTransport(), resolver=MappingResolver()
    )
    page = await provider.search("Alpha Lab", limit=10)

    assert len(page.articles) == 10
    assert [article.title for article in page.articles[:3]] == [
        "Alpha newest",
        "Alpha second",
        "Alpha third",
    ]
    assert len({article.url for article in page.articles}) == 10
    assert all(article.account == "Alpha Lab" for article in page.articles)
    assert all(article.source is DiscoverySource.PUBLIC_SEARCH for article in page.articles)
    assert all(article.url.startswith("https://mp.weixin.qq.com/") for article in page.articles)
    assert page.is_complete is False
    assert page.warning is not None and "unresolved" in page.warning.lower()
    assert "skipped" in page.warning.lower()
    assert all(item.title != "Alpha unresolved" for item in page.articles)


@pytest.mark.asyncio
async def test_public_search_cursor_round_trips_as_provider_owned_token() -> None:
    from wechat_reader_mcp.discovery.public import SogouDiscoveryProvider

    transport = FixtureTransport()
    provider = SogouDiscoveryProvider(transport=transport, resolver=MappingResolver())
    first = await provider.search("Alpha Lab", limit=2)
    second = await provider.search("Alpha Lab", limit=2, cursor=first.next_cursor)

    assert first.next_cursor is not None
    assert transport.pages == [1, 2]
    assert len(second.articles) == 2


@pytest.mark.asyncio
async def test_public_search_rejects_limit_above_ten() -> None:
    from wechat_reader_mcp.discovery.public import SogouDiscoveryProvider

    provider = SogouDiscoveryProvider(
        transport=FixtureTransport(), resolver=MappingResolver()
    )
    with pytest.raises(ReaderException) as caught:
        await provider.search("Alpha Lab", limit=11)
    assert caught.value.error.code is ErrorCode.INVALID_SELECTION


@pytest.mark.asyncio
async def test_public_search_rejects_malformed_cursor_as_typed_error() -> None:
    from wechat_reader_mcp.discovery.public import SogouDiscoveryProvider

    provider = SogouDiscoveryProvider(
        transport=FixtureTransport(), resolver=MappingResolver()
    )
    with pytest.raises(ReaderException) as caught:
        await provider.search("Alpha Lab", limit=2, cursor="%%%not-base64%%")
    assert caught.value.error.code is ErrorCode.INVALID_SELECTION


@pytest.mark.asyncio
async def test_account_resolution_groups_ambiguous_names() -> None:
    from wechat_reader_mcp.discovery.public import SogouDiscoveryProvider

    provider = SogouDiscoveryProvider(
        transport=FixtureTransport(), resolver=MappingResolver()
    )
    candidates = await provider.resolve_accounts("Alpha")

    assert [candidate.name for candidate in candidates] == [
        "Alpha Lab",
        "Alpha Research",
    ]
    assert all(candidate.source is DiscoverySource.PUBLIC_SEARCH for candidate in candidates)


@pytest.mark.asyncio
async def test_url_resolver_follows_bounded_redirects_and_validates_destination() -> None:
    from wechat_reader_mcp.discovery.public import SogouUrlResolver

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/middle"})
        if request.url.path == "/middle":
            return httpx.Response(
                302, headers={"location": "https://mp.weixin.qq.com/s/final"}
            )
        return httpx.Response(200)

    resolver = SogouUrlResolver(transport=httpx.MockTransport(handler), max_redirects=3)

    assert await resolver.resolve("https://weixin.sogou.com/start") == (
        "https://mp.weixin.qq.com/s/final"
    )


@pytest.mark.asyncio
async def test_url_resolver_returns_none_for_invalid_destination() -> None:
    from wechat_reader_mcp.discovery.public import SogouUrlResolver

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302, headers={"location": "https://example.com/not-wechat"}
        )
    )
    resolver = SogouUrlResolver(transport=transport, max_redirects=1)

    assert await resolver.resolve("https://weixin.sogou.com/start") is None
