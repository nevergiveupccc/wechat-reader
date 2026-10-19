"""URL validation and bounded HTTP retrieval for public article pages."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import ErrorCode, ReaderError

_QUERY_KEYS = ("__biz", "mid", "idx", "sn", "chksm")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


def _fail(code: ErrorCode, message: str, *, retryable: bool = False) -> ReaderException:
    return ReaderException(
        ReaderError(code=code, message=message, retryable=retryable)
    )


def normalize_wechat_article_url(url: str) -> str:
    """Validate an exact WeChat article host/path and remove tracking data."""

    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise _fail(ErrorCode.INVALID_URL, "The article URL is invalid.") from exc

    if parsed.scheme != "https":
        raise _fail(ErrorCode.INVALID_URL, "A WeChat article URL must use HTTPS.")
    if parsed.hostname != "mp.weixin.qq.com":
        raise _fail(ErrorCode.UNSUPPORTED_URL, "Only mp.weixin.qq.com article URLs are supported.")
    if parsed.username is not None or parsed.password is not None or port not in (None, 443):
        raise _fail(ErrorCode.INVALID_URL, "The article URL contains unsafe authority data.")

    if parsed.path.startswith("/s/") and len(parsed.path) > 3:
        return urlunsplit(("https", "mp.weixin.qq.com", parsed.path, "", ""))
    if parsed.path != "/s":
        raise _fail(ErrorCode.UNSUPPORTED_URL, "The URL is not a recognized WeChat article page.")

    query = parse_qs(parsed.query, keep_blank_values=False)
    required = {"__biz", "mid", "idx", "sn"}
    if not required.issubset(query) or any(not query[key][0] for key in required):
        raise _fail(ErrorCode.INVALID_URL, "The query-form WeChat article URL is incomplete.")
    canonical_query = urlencode(
        [(key, query[key][0]) for key in _QUERY_KEYS if key in query]
    )
    return urlunsplit(("https", "mp.weixin.qq.com", "/s", canonical_query, ""))


class HttpArticleFetcher:
    """Fetch one public page with redirects, limits, and typed failures."""

    def __init__(
        self,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=connect_timeout,
            pool=connect_timeout,
        )
        self.max_bytes = max_bytes

    async def fetch(self, url: str) -> str:
        normalized = normalize_wechat_article_url(url)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
            ) as client:
                response = await client.get(normalized)
        except httpx.TimeoutException as exc:
            raise _fail(
                ErrorCode.TIMEOUT,
                "Timed out while loading the WeChat article.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise _fail(
                ErrorCode.NETWORK_ERROR,
                "Could not load the WeChat article.",
                retryable=True,
            ) from exc

        if response.status_code in (401, 403, 429):
            raise _fail(
                ErrorCode.RATE_LIMITED_OR_CAPTCHA,
                "WeChat requested verification or limited this request.",
                retryable=True,
            )
        if response.status_code in (404, 410):
            raise _fail(ErrorCode.ARTICLE_UNAVAILABLE, "The article is unavailable.")
        if response.is_error:
            raise _fail(
                ErrorCode.NETWORK_ERROR,
                f"WeChat returned HTTP {response.status_code}.",
                retryable=response.status_code >= 500,
            )
        if len(response.content) > self.max_bytes:
            raise _fail(ErrorCode.UNSUPPORTED_PAGE, "The article page is unexpectedly large.")
        return response.text
