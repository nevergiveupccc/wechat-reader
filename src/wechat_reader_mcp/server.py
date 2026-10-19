"""FastMCP stdio server exposing the five stable reader tools."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import StrictInt

from wechat_reader_mcp.browser.session import BrowserSessionManager
from wechat_reader_mcp.config import Settings
from wechat_reader_mcp.discovery.authenticated import WeReadDiscoveryProvider
from wechat_reader_mcp.discovery.public import SogouDiscoveryProvider
from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.extraction.fetch import BrowserArticleFetcher, HttpArticleFetcher
from wechat_reader_mcp.extraction.parse import WeChatArticleParser
from wechat_reader_mcp.models import DiscoveryMode, ErrorCode, ReaderError
from wechat_reader_mcp.service import ReaderService
from wechat_reader_mcp.storage import SqliteStore


def _invalid_selection(message: str) -> ReaderException:
    return ReaderException(
        ReaderError(code=ErrorCode.INVALID_SELECTION, message=message)
    )


def validate_selections(selections: list[Any]) -> list[int]:
    """Validate one to ten unique positive integer result indices."""

    if not 1 <= len(selections) <= 10:
        raise _invalid_selection("Select from one to ten articles.")
    if any(isinstance(value, bool) or type(value) is not int for value in selections):
        raise _invalid_selection("Every selection must be an integer index.")
    if any(value <= 0 for value in selections):
        raise _invalid_selection("Every selection must be positive.")
    if len(set(selections)) != len(selections):
        raise _invalid_selection("Selections must be unique.")
    return selections


def _error_payload(error: ReaderError) -> dict[str, Any]:
    return {"error": error.model_dump(mode="json")}


def _unexpected_error() -> dict[str, Any]:
    return _error_payload(
        ReaderError(
            code=ErrorCode.INTERNAL_ERROR,
            message="The reader encountered an unexpected internal error.",
        )
    )


def create_default_service() -> ReaderService:
    settings = Settings.from_env()
    browser_session = BrowserSessionManager(settings.paths.browser_profile_dir)
    browser_available = browser_session.status().browser_available
    return ReaderService(
        store=SqliteStore(
            settings.database_path,
            result_ttl=settings.result_ttl,
            article_ttl=settings.article_ttl,
        ),
        public_provider=SogouDiscoveryProvider(),
        authenticated_provider=(
            WeReadDiscoveryProvider(browser_session) if browser_available else None
        ),
        http_fetcher=HttpArticleFetcher(),
        browser_fetcher=(
            BrowserArticleFetcher(browser_session) if browser_available else None
        ),
        parser=WeChatArticleParser(),
        browser_session=browser_session,
    )


def create_mcp_server(
    service_factory: Callable[[], ReaderService],
) -> FastMCP:
    """Create a server without starting transport or writing to stdout."""

    service = service_factory()
    mcp = FastMCP("wechat-reader-mcp")

    @mcp.tool(
        name="resolve_account",
        description=(
            "Find public-account candidates by name. Public search is best-effort "
            "and may not include every existing account."
        ),
        structured_output=True,
    )
    async def resolve_account(query: str) -> dict[str, Any]:
        try:
            candidates = await service.resolve_account(query)
            return {"candidates": [item.model_dump(mode="json") for item in candidates]}
        except ReaderException as exc:
            return _error_payload(exc.error)
        except Exception:
            return _unexpected_error()

    @mcp.tool(
        name="list_recent_articles",
        description=(
            "List one to ten recently discovered public articles. Results may be "
            "incomplete and are not claimed to be the official latest articles."
        ),
        structured_output=True,
    )
    async def list_recent_articles(
        account: str,
        limit: int = 10,
        mode: str = "auto",
        cursor: str | None = None,
    ) -> dict[str, Any]:
        try:
            page = await service.list_recent_articles(
                account=account,
                limit=limit,
                mode=DiscoveryMode(mode),
                cursor=cursor,
            )
            return page.model_dump(mode="json")
        except ValueError:
            return _error_payload(
                ReaderError(
                    code=ErrorCode.INVALID_SELECTION,
                    message="Discovery mode is invalid.",
                )
            )
        except ReaderException as exc:
            return _error_payload(exc.error)
        except Exception:
            return _unexpected_error()

    @mcp.tool(
        name="read_selected_articles",
        description=(
            "Read one to ten unique article indices from a prior result set. "
            "Each article keeps its own success or error result."
        ),
        structured_output=True,
    )
    async def read_selected_articles(
        result_set_id: str,
        selections: list[StrictInt],
    ) -> dict[str, Any]:
        try:
            validated = validate_selections(selections)
            response = await service.read_selected_articles(result_set_id, validated)
            return response.model_dump(mode="json")
        except ReaderException as exc:
            return _error_payload(exc.error)
        except Exception:
            return _unexpected_error()

    @mcp.tool(
        name="read_article_url",
        description="Read one public mp.weixin.qq.com article URL as clean Markdown.",
        structured_output=True,
    )
    async def read_article_url(url: str) -> dict[str, Any]:
        try:
            result = await service.read_article_url(url)
            return result.model_dump(mode="json")
        except ReaderException as exc:
            return _error_payload(exc.error)
        except Exception:
            return _unexpected_error()

    @mcp.tool(
        name="get_reader_status",
        description="Report reader, cache, browser, login, and provider status without secrets.",
        structured_output=True,
    )
    def get_reader_status() -> dict[str, Any]:
        try:
            return service.get_status().model_dump(mode="json")
        except ReaderException as exc:
            return _error_payload(exc.error)
        except Exception:
            return _unexpected_error()

    return mcp


def run_stdio() -> None:
    """Run the MCP transport while reserving stdout exclusively for protocol data."""

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    create_mcp_server(create_default_service).run(transport="stdio")
