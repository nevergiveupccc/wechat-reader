"""Convert a recognized public WeChat article page to clean Markdown."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.extraction.fetch import normalize_wechat_article_url
from wechat_reader_mcp.models import (
    ArticleContent,
    DiscoverySource,
    ErrorCode,
    ReaderError,
)

_TIMESTAMP_RE = re.compile(r"\b(?:var\s+)?ct\s*=\s*['\"](\d{9,12})['\"]")
_ANTIBOT_MARKERS = ("访问过于频繁", "环境异常", "完成验证", "captcha")
_UNAVAILABLE_MARKERS = ("内容已被删除", "该内容已被发布者删除", "此内容因违规无法查看")


def _error(code: ErrorCode, message: str, *, retryable: bool = False) -> ReaderException:
    return ReaderException(
        ReaderError(code=code, message=message, retryable=retryable)
    )


def _meta(soup: BeautifulSoup, *, property_name: str | None = None, name: str | None = None) -> str | None:
    attrs = {"property": property_name} if property_name else {"name": name}
    node = soup.find("meta", attrs=attrs)
    if isinstance(node, Tag):
        value = node.get("content")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _text(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if node:
        value = node.get_text(" ", strip=True)
        return value or None
    return None


def _published_at(soup: BeautifulSoup, html: str) -> datetime | None:
    raw = _meta(soup, property_name="article:published_time")
    if raw:
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if value.tzinfo is not None:
                return value.astimezone(UTC)
        except ValueError:
            pass
    match = _TIMESTAMP_RE.search(html)
    if match:
        return datetime.fromtimestamp(int(match.group(1)), UTC)
    return None


def _normalize_markdown(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
    result: list[str] = []
    blank = False
    for line in lines:
        if line.strip():
            result.append(line)
            blank = False
        elif not blank:
            result.append("")
            blank = True
    return "\n".join(result).strip()


class WeChatArticleParser:
    """Parse only pages containing a recognized WeChat article body."""

    def parse(self, url: str, html: str) -> ArticleContent:
        requested_url = normalize_wechat_article_url(url)
        soup = BeautifulSoup(html, "lxml")
        page_text = soup.get_text(" ", strip=True).lower()
        if any(marker in page_text for marker in _ANTIBOT_MARKERS):
            raise _error(
                ErrorCode.RATE_LIMITED_OR_CAPTCHA,
                "WeChat requested verification or limited this request.",
                retryable=True,
            )
        if any(marker in page_text for marker in _UNAVAILABLE_MARKERS):
            raise _error(ErrorCode.ARTICLE_UNAVAILABLE, "The article is unavailable.")

        body = soup.select_one("#js_content")
        if body is None:
            raise _error(
                ErrorCode.UNSUPPORTED_PAGE,
                "The page does not contain a recognized WeChat article body.",
            )

        title = (
            _meta(soup, property_name="og:title")
            or _text(soup, "#activity-name")
            or _text(soup, "h1")
        )
        account = (
            _meta(soup, name="author")
            or _text(soup, ".rich_media_meta_nickname")
            or _text(soup, "#js_name")
        )
        if not title or not account:
            raise _error(
                ErrorCode.UNSUPPORTED_PAGE,
                "The article title or account metadata is missing.",
            )

        canonical_url = requested_url
        canonical = soup.find("link", rel="canonical")
        if isinstance(canonical, Tag) and isinstance(canonical.get("href"), str):
            try:
                canonical_url = normalize_wechat_article_url(canonical["href"])
            except ReaderException:
                pass

        images: list[str] = []
        for image in body.select("img"):
            source = image.get("data-src") or image.get("src")
            if isinstance(source, str) and source.startswith("https://"):
                if source not in images:
                    images.append(source)
                image["src"] = source
            image.attrs.pop("data-src", None)
        for unwanted in body.select("script, style, noscript"):
            unwanted.decompose()

        content = _normalize_markdown(
            markdownify(str(body), heading_style="ATX", strip=["div"])
        )
        if not content:
            raise _error(ErrorCode.UNSUPPORTED_PAGE, "The article body is empty.")

        return ArticleContent(
            title=title,
            account=account,
            url=canonical_url,
            markdown=content,
            published_at=_published_at(soup, html),
            images=images,
            source=DiscoverySource.DIRECT_URL,
        )
