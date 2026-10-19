"""Optional browser-backed discovery from a user-controlled local session."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote_plus

from bs4 import BeautifulSoup, Tag

from wechat_reader_mcp.discovery.base import ProviderPage
from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.extraction.fetch import normalize_wechat_article_url
from wechat_reader_mcp.models import (
    ArticleSummary,
    DiscoverySource,
    ErrorCode,
    ReaderError,
)

_SEARCH_URL = "https://weread.qq.com/web/search/global?keyword={account}&page={page}"
_CAPTCHA_MARKERS = ("完成验证", "访问过于频繁", "captcha")


class BrowserPageSession(Protocol):
    async def page_content(self, url: str) -> str: ...


def _error(code: ErrorCode, message: str, *, retryable: bool = False) -> ReaderException:
    return ReaderException(
        ReaderError(code=code, message=message, retryable=retryable)
    )


def _encode_cursor(page: int) -> str:
    return base64.urlsafe_b64encode(f"authenticated:{page}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 1
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        prefix, raw_page = base64.urlsafe_b64decode(padded).decode().split(":", 1)
        page = int(raw_page)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _error(ErrorCode.INVALID_SELECTION, "The authenticated-search cursor is invalid.") from exc
    if prefix != "authenticated" or page < 1:
        raise _error(ErrorCode.INVALID_SELECTION, "The authenticated-search cursor is invalid.")
    return page


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return None
    return value.astimezone(UTC)


class WeReadDiscoveryProvider:
    """Parse browser-visible discovery results without exposing session data."""

    def __init__(self, session: BrowserPageSession) -> None:
        self.session = session

    async def search(
        self, account: str, limit: int, cursor: str | None = None
    ) -> ProviderPage:
        if not 1 <= limit <= 10:
            raise _error(ErrorCode.INVALID_SELECTION, "Article limit must be from 1 to 10.")
        if not account.strip():
            raise _error(ErrorCode.INVALID_SELECTION, "The account name cannot be empty.")
        page_number = _decode_cursor(cursor)
        url = _SEARCH_URL.format(
            account=quote_plus(account.strip()),
            page=page_number,
        )
        html = await self.session.page_content(url)
        lowered = BeautifulSoup(html, "lxml").get_text(" ", strip=True).lower()
        if any(marker in lowered for marker in _CAPTCHA_MARKERS):
            raise _error(
                ErrorCode.RATE_LIMITED_OR_CAPTCHA,
                "The authenticated source requested verification.",
                retryable=True,
            )

        soup = BeautifulSoup(html, "lxml")
        auth_marker = soup.select_one('[data-authenticated="true"]')
        if auth_marker is None:
            raise _error(
                ErrorCode.LOGIN_REQUIRED,
                "The local browser session is not logged in or has expired.",
                retryable=True,
            )

        parsed: list[ArticleSummary] = []
        seen: set[str] = set()
        for node in soup.select("[data-article-result]"):
            if not isinstance(node, Tag):
                continue
            title = node.get("data-title")
            found_account = node.get("data-account")
            raw_url = node.get("data-url")
            if not all(isinstance(value, str) and value for value in (title, found_account, raw_url)):
                continue
            if found_account.casefold() != account.casefold():
                continue
            try:
                normalized = normalize_wechat_article_url(raw_url)
            except ReaderException:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(
                ArticleSummary(
                    index=1,
                    title=title,
                    account=found_account,
                    url=normalized,
                    published_at=_parse_date(node.get("data-published")),
                    source=DiscoverySource.AUTHENTICATED_SEARCH,
                )
            )

        parsed.sort(
            key=lambda item: item.published_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        articles = [item.model_copy(update={"index": index}) for index, item in enumerate(parsed[:limit], 1)]
        if not articles:
            raise _error(ErrorCode.NO_DISCOVERY_RESULTS, "No authenticated results were found.")
        has_next = soup.select_one("[data-next-page]") is not None
        return ProviderPage(
            articles=articles,
            next_cursor=_encode_cursor(page_number + 1) if has_next else None,
            is_complete=False,
            warning="Authenticated discovery is best-effort and may be incomplete.",
        )
