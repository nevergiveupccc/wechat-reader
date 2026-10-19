"""Optional discovery through a user-controlled WeRead browser session."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from wechat_reader_mcp.discovery.base import ProviderPage
from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.extraction.fetch import normalize_wechat_article_url
from wechat_reader_mcp.models import (
    ArticleSummary,
    DiscoverySource,
    ErrorCode,
    ReaderError,
)

_HOST = "https://weread.qq.com"
_SHELF_PATH = "/web/shelf/sync"
_ARTICLES_PATH = "/web/mp/articles"
_CONTENT_PATH = "/web/mp/content"


class BrowserPageSession(Protocol):
    async def page_content(self, url: str) -> str: ...


def _error(code: ErrorCode, message: str, *, retryable: bool = False) -> ReaderException:
    return ReaderException(
        ReaderError(code=code, message=message, retryable=retryable)
    )


def _url(path: str, **params: object) -> str:
    return f"{_HOST}{path}?{urlencode(params)}"


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(
        f"authenticated:{offset}".encode()
    ).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        prefix, raw_offset = base64.urlsafe_b64decode(padded).decode().split(":", 1)
        offset = int(raw_offset)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _error(
            ErrorCode.INVALID_SELECTION,
            "The authenticated-search cursor is invalid.",
        ) from exc
    if prefix != "authenticated" or offset < 0:
        raise _error(
            ErrorCode.INVALID_SELECTION,
            "The authenticated-search cursor is invalid.",
        )
    return offset


def _json_from_browser_page(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    pre = soup.select_one("pre")
    raw = pre.get_text() if pre is not None else soup.get_text(" ", strip=True)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _error(
            ErrorCode.LOGIN_REQUIRED,
            "The local WeRead session is not logged in or has expired.",
            retryable=True,
        ) from exc
    if not isinstance(payload, dict):
        raise _error(
            ErrorCode.LOGIN_REQUIRED,
            "The local WeRead session returned an unexpected response.",
            retryable=True,
        )
    error_code = payload.get("errCode", payload.get("errcode", 0))
    if str(error_code) == "-2041":
        raise _error(
            ErrorCode.RATE_LIMITED_OR_CAPTCHA,
            "WeRead requested interactive verification in the local browser.",
            retryable=True,
        )
    if error_code not in (None, 0, "0"):
        raise _error(
            ErrorCode.LOGIN_REQUIRED,
            "The local WeRead session is not logged in or has expired.",
            retryable=True,
        )
    return payload


def _published_at(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _article_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    reviews = payload.get("reviews", [])
    if not isinstance(reviews, list):
        return items
    for review_group in reviews:
        if not isinstance(review_group, dict):
            continue
        sub_reviews = review_group.get("subReviews", [])
        if not isinstance(sub_reviews, list):
            continue
        for sub_review in sub_reviews:
            if not isinstance(sub_review, dict):
                continue
            review = sub_review.get("review")
            info = review.get("mpInfo") if isinstance(review, dict) else None
            if isinstance(info, dict) and info.get("title"):
                items.append(info)
    return items


def _public_url_from_content(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    node = soup.select_one('meta[property="og:url"]')
    raw_url = node.get("content") if node is not None else None
    if not isinstance(raw_url, str) or not raw_url:
        return None
    try:
        return normalize_wechat_article_url(raw_url)
    except ReaderException:
        return None


class WeReadDiscoveryProvider:
    """Read followed-account articles without exporting the browser session."""

    def __init__(self, session: BrowserPageSession) -> None:
        self.session = session

    async def search(
        self, account: str, limit: int, cursor: str | None = None
    ) -> ProviderPage:
        if not 1 <= limit <= 10:
            raise _error(ErrorCode.INVALID_SELECTION, "Article limit must be from 1 to 10.")
        account_name = account.strip()
        if not account_name:
            raise _error(ErrorCode.INVALID_SELECTION, "The account name cannot be empty.")
        offset = _decode_cursor(cursor)

        shelf_html = await self.session.page_content(
            _url(_SHELF_PATH, userVid="", synckey=0)
        )
        shelf = _json_from_browser_page(shelf_html)
        books = shelf.get("books", [])
        match: dict[str, Any] | None = None
        if isinstance(books, list):
            for book in books:
                if not isinstance(book, dict):
                    continue
                book_id = book.get("bookId")
                title = book.get("title")
                if (
                    isinstance(book_id, str)
                    and book_id.startswith("MP_WXS_")
                    and isinstance(title, str)
                    and title.casefold() == account_name.casefold()
                ):
                    match = book
                    break
        if match is None:
            raise _error(
                ErrorCode.NO_DISCOVERY_RESULTS,
                "This account is not available in the local WeRead followed list.",
            )

        book_id = str(match["bookId"])
        canonical_account = str(match["title"])
        article_html = await self.session.page_content(
            _url(_ARTICLES_PATH, bookId=book_id, offset=offset)
        )
        raw_items = _article_items(_json_from_browser_page(article_html))

        articles: list[ArticleSummary] = []
        seen: set[str] = set()
        for item in raw_items:
            if len(articles) == limit:
                break
            original_id = item.get("originalId")
            title = item.get("title")
            if not isinstance(original_id, str) or not original_id:
                continue
            if not isinstance(title, str) or not title:
                continue
            content_html = await self.session.page_content(
                _url(_CONTENT_PATH, reviewId=f"{book_id}_{original_id}")
            )
            public_url = _public_url_from_content(content_html)
            if public_url is None or public_url in seen:
                continue
            seen.add(public_url)
            digest = item.get("content")
            found_account = item.get("mp_name")
            articles.append(
                ArticleSummary(
                    index=len(articles) + 1,
                    title=title,
                    account=(
                        found_account
                        if isinstance(found_account, str) and found_account
                        else canonical_account
                    ),
                    url=public_url,
                    published_at=_published_at(item.get("time")),
                    digest=digest if isinstance(digest, str) and digest else None,
                    source=DiscoverySource.AUTHENTICATED_SEARCH,
                )
            )

        if not articles:
            raise _error(
                ErrorCode.NO_DISCOVERY_RESULTS,
                "No readable articles were found for this followed account.",
            )
        has_next = len(raw_items) > limit
        return ProviderPage(
            articles=articles,
            next_cursor=_encode_cursor(offset + len(raw_items)) if has_next else None,
            is_complete=False,
            warning=(
                "Authenticated discovery uses an undocumented WeRead interface, only "
                "covers accounts followed there, and may be incomplete."
            ),
        )
