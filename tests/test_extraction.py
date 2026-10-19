from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import DiscoverySource, ErrorCode

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "https://mp.weixin.qq.com/s/article-id?utm_source=test#fragment",
            "https://mp.weixin.qq.com/s/article-id",
        ),
        (
            "https://mp.weixin.qq.com/s?sn=abc&idx=1&mid=2&__biz=biz#rd",
            "https://mp.weixin.qq.com/s?__biz=biz&mid=2&idx=1&sn=abc",
        ),
    ],
)
def test_normalize_wechat_article_url(source: str, expected: str) -> None:
    from wechat_reader_mcp.extraction.fetch import normalize_wechat_article_url

    assert normalize_wechat_article_url(source) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://mp.weixin.qq.com/s/insecure",
        "https://mp.weixin.qq.com.evil.example/s/lookalike",
        "https://user@mp.weixin.qq.com/s/user-info",
        "https://mp.weixin.qq.com/not-an-article",
    ],
)
def test_normalize_rejects_unsafe_or_non_article_urls(url: str) -> None:
    from wechat_reader_mcp.extraction.fetch import normalize_wechat_article_url

    with pytest.raises(ReaderException) as caught:
        normalize_wechat_article_url(url)
    assert caught.value.error.code in {ErrorCode.INVALID_URL, ErrorCode.UNSUPPORTED_URL}


def test_parser_extracts_metadata_markdown_and_images() -> None:
    from wechat_reader_mcp.extraction.parse import WeChatArticleParser

    article = WeChatArticleParser().parse(
        "https://mp.weixin.qq.com/s/requested", _fixture("article_standard.html")
    )

    assert article.title == "A Synthetic WeChat Article"
    assert article.account == "Example Account"
    assert article.url == "https://mp.weixin.qq.com/s/canonical-example"
    assert article.published_at == datetime(2026, 10, 19, 0, 30, tzinfo=UTC)
    assert "## First heading" in article.markdown
    assert "[reference](https://example.com/reference)" in article.markdown
    assert "secret" not in article.markdown
    assert article.images == ["https://mmbiz.qpic.cn/synthetic-image"]
    assert article.source is DiscoverySource.DIRECT_URL


def test_parser_recovers_script_timestamp() -> None:
    from wechat_reader_mcp.extraction.parse import WeChatArticleParser

    article = WeChatArticleParser().parse(
        "https://mp.weixin.qq.com/s/timestamp",
        _fixture("article_script_timestamp.html"),
    )

    assert article.published_at == datetime.fromtimestamp(1760832000, UTC)
    assert article.account == "Timestamp Account"


def test_parser_classifies_antibot_page() -> None:
    from wechat_reader_mcp.extraction.parse import WeChatArticleParser

    with pytest.raises(ReaderException) as caught:
        WeChatArticleParser().parse(
            "https://mp.weixin.qq.com/s/blocked", _fixture("article_antibot.html")
        )
    assert caught.value.error.code is ErrorCode.RATE_LIMITED_OR_CAPTCHA
    assert caught.value.error.retryable is True


@pytest.mark.asyncio
@respx.mock
async def test_http_fetcher_uses_bounded_redirecting_client() -> None:
    from wechat_reader_mcp.extraction.fetch import HttpArticleFetcher

    url = "https://mp.weixin.qq.com/s/fetchable"
    route = respx.get(url).mock(return_value=httpx.Response(200, text="<html>ok</html>"))

    html = await HttpArticleFetcher().fetch(url)

    assert html == "<html>ok</html>"
    assert route.called
    assert "Mozilla/5.0" in route.calls.last.request.headers["user-agent"]


@pytest.mark.asyncio
@respx.mock
async def test_http_fetcher_maps_unavailable_article() -> None:
    from wechat_reader_mcp.extraction.fetch import HttpArticleFetcher

    url = "https://mp.weixin.qq.com/s/deleted"
    respx.get(url).mock(return_value=httpx.Response(404, text="gone"))

    with pytest.raises(ReaderException) as caught:
        await HttpArticleFetcher().fetch(url)
    assert caught.value.error.code is ErrorCode.ARTICLE_UNAVAILABLE
