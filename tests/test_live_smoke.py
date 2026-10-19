"""Opt-in, tightly bounded checks against maintainer-supplied public inputs."""

from __future__ import annotations

import os

import pytest

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import DiscoveryMode
from wechat_reader_mcp.server import create_default_service

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_one_public_listing_and_one_direct_article_read() -> None:
    if os.getenv("WECHAT_READER_RUN_LIVE") != "1":
        pytest.skip("set WECHAT_READER_RUN_LIVE=1 to enable bounded live checks")
    account = os.getenv("WECHAT_READER_LIVE_ACCOUNT", "").strip()
    article_url = os.getenv("WECHAT_READER_LIVE_ARTICLE_URL", "").strip()
    if not account or not article_url:
        pytest.skip(
            "set WECHAT_READER_LIVE_ACCOUNT and WECHAT_READER_LIVE_ARTICLE_URL"
        )

    service = create_default_service()
    try:
        page = await service.list_recent_articles(
            account,
            limit=1,
            mode=DiscoveryMode.PUBLIC,
        )
    except ReaderException as exc:
        pytest.fail(f"discovery failed with typed code: {exc.error.code.value}")
    assert page.requested == 1
    assert 0 < page.returned <= 1

    result = await service.read_article_url(article_url)
    assert result.error is None, (
        f"direct read failed with typed code: {result.error.code.value}"
        if result.error is not None
        else "direct read failed"
    )
    assert result.article is not None
