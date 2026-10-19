from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from wechat_reader_mcp.models import (
    ArticleContent,
    ArticleReadResult,
    ArticleSummary,
    BatchReadResponse,
    DiscoveryPage,
    DiscoverySource,
    ErrorCode,
    ReaderError,
    ReaderStatus,
)


def _summary(index: int = 1) -> ArticleSummary:
    return ArticleSummary(
        index=index,
        title="A public article",
        url=f"https://mp.weixin.qq.com/s/article-{index}",
        account="Example Account",
        published_at=datetime(2026, 10, 19, tzinfo=UTC),
    )


def test_discovery_page_limit_cannot_exceed_ten() -> None:
    with pytest.raises(ValidationError):
        DiscoveryPage(
            result_set_id="rs_1",
            account="Example Account",
            requested=11,
            returned=0,
            discovery_source=DiscoverySource.PUBLIC_SEARCH,
            is_complete=False,
            articles=[],
        )

    assert {source.value for source in DiscoverySource} == {
        "public_search",
        "authenticated_search",
        "official_authorized",
        "direct_url",
    }


def test_batch_response_preserves_per_item_errors() -> None:
    article = ArticleContent(
        title="Readable",
        account="Example Account",
        url="https://mp.weixin.qq.com/s/readable",
        markdown="Readable body",
    )
    response = BatchReadResponse(
        result_set_id="rs_1",
        results=[
            ArticleReadResult(index=1, url=article.url, article=article),
            ArticleReadResult(
                index=2,
                url="https://mp.weixin.qq.com/s/deleted",
                error=ReaderError(
                    code=ErrorCode.ARTICLE_UNAVAILABLE,
                    message="Article is unavailable",
                    retryable=False,
                ),
            ),
        ],
    )

    assert response.results[0].article == article
    assert response.results[1].error is not None
    assert response.results[1].error.code is ErrorCode.ARTICLE_UNAVAILABLE


def test_reader_status_serialization_contains_no_secret_fields() -> None:
    status = ReaderStatus(
        version="0.1.0",
        cache_available=True,
        browser_available=False,
        login_status="not_configured",
        providers=[DiscoverySource.PUBLIC_SEARCH],
    )

    payload = status.model_dump(mode="json")
    serialized_keys = {key.lower() for key in payload}

    assert serialized_keys.isdisjoint(
        {"cookie", "cookies", "token", "qr", "profile_path", "browser_profile"}
    )
    assert payload["providers"] == ["public_search"]


def test_article_summary_index_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _summary(index=0)
