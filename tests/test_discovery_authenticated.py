import json
from urllib.parse import parse_qs, urlparse

import pytest

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import DiscoverySource, ErrorCode

class FixtureSession:
    def __init__(
        self,
        *,
        shelf: dict[str, object] | None = None,
        articles: dict[str, object] | None = None,
    ) -> None:
        self.shelf = shelf or {
            "books": [
                {"bookId": "BOOK_IGNORED", "title": "Ordinary Book"},
                {"bookId": "MP_WXS_ALPHA", "title": "Alpha Lab"},
            ]
        }
        self.articles = articles or _articles_payload(11)
        self.urls: list[str] = []

    async def page_content(self, url: str) -> str:
        self.urls.append(url)
        parsed = urlparse(url)
        if parsed.path == "/web/shelf/sync":
            return _json_page(self.shelf)
        if parsed.path == "/web/mp/articles":
            return _json_page(self.articles)
        if parsed.path == "/web/mp/content":
            review_id = parse_qs(parsed.query)["reviewId"][0]
            original_id = review_id.removeprefix("MP_WXS_ALPHA_")
            return (
                '<html><head><meta property="og:url" '
                f'content="https://mp.weixin.qq.com/s/{original_id}"></head></html>'
            )
        raise AssertionError(f"unexpected URL: {url}")


def _json_page(payload: dict[str, object]) -> str:
    return f"<html><body><pre>{json.dumps(payload)}</pre></body></html>"


def _articles_payload(count: int) -> dict[str, object]:
    return {
        "reviews": [
            {
                "subReviews": [
                    {
                        "review": {
                            "mpInfo": {
                                "title": "Newest" if index == 1 else f"Article {index}",
                                "mp_name": "Alpha Lab",
                                "originalId": f"auth-{index}",
                                "content": f"Digest {index}",
                                "time": 1_700_000_000 - index,
                            }
                        }
                    }
                    for index in range(1, count + 1)
                ]
            }
        ]
    }


@pytest.mark.asyncio
async def test_authenticated_results_are_sorted_capped_and_attributed() -> None:
    from wechat_reader_mcp.discovery.authenticated import WeReadDiscoveryProvider

    session = FixtureSession()
    provider = WeReadDiscoveryProvider(session)
    page = await provider.search("Alpha Lab", limit=10)

    assert len(page.articles) == 10
    assert [item.title for item in page.articles[:2]] == ["Newest", "Article 2"]
    assert all(item.account == "Alpha Lab" for item in page.articles)
    assert all(
        item.source is DiscoverySource.AUTHENTICATED_SEARCH
        for item in page.articles
    )
    assert page.articles[0].url == "https://mp.weixin.qq.com/s/auth-1"
    assert page.is_complete is False
    assert page.next_cursor is not None
    assert session.urls[0].startswith("https://weread.qq.com/web/shelf/sync?")
    assert session.urls[1].startswith("https://weread.qq.com/web/mp/articles?")
    assert "bookId=MP_WXS_ALPHA" in session.urls[1]
    assert sum("/web/mp/content?" in url for url in session.urls) == 10


@pytest.mark.asyncio
async def test_authenticated_search_requires_login_marker() -> None:
    from wechat_reader_mcp.discovery.authenticated import WeReadDiscoveryProvider

    provider = WeReadDiscoveryProvider(
        FixtureSession(shelf={"errCode": -2012, "errMsg": "login expired"})
    )

    with pytest.raises(ReaderException) as caught:
        await provider.search("Alpha Lab", limit=10)
    assert caught.value.error.code is ErrorCode.LOGIN_REQUIRED


@pytest.mark.asyncio
async def test_authenticated_search_rejects_captcha_without_retrying() -> None:
    from wechat_reader_mcp.discovery.authenticated import WeReadDiscoveryProvider

    session = FixtureSession(
        shelf={"errCode": -2041, "errMsg": "captcha required"}
    )
    provider = WeReadDiscoveryProvider(session)

    with pytest.raises(ReaderException) as caught:
        await provider.search("Alpha Lab", limit=10)
    assert caught.value.error.code is ErrorCode.RATE_LIMITED_OR_CAPTCHA
    assert len(session.urls) == 1


@pytest.mark.asyncio
async def test_authenticated_search_only_matches_followed_accounts() -> None:
    from wechat_reader_mcp.discovery.authenticated import WeReadDiscoveryProvider

    provider = WeReadDiscoveryProvider(FixtureSession())

    with pytest.raises(ReaderException) as caught:
        await provider.search("Not Followed", limit=10)
    assert caught.value.error.code is ErrorCode.NO_DISCOVERY_RESULTS
