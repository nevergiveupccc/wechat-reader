"""Manage a user-controlled local browser profile without exposing secrets."""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import ErrorCode, LoginStatus, ReaderError

_LOGIN_URL = "https://weread.qq.com/"
_LOGIN_COOKIE_NAMES = {"wr_skey", "wr_vid"}
_SESSION_MARKER = ".wechat-reader-authenticated"


def _browser_error(message: str) -> ReaderException:
    return ReaderException(
        ReaderError(
            code=ErrorCode.BROWSER_UNAVAILABLE,
            message=message,
            retryable=False,
        )
    )


def _unsafe_navigation_error() -> ReaderException:
    return ReaderException(
        ReaderError(
            code=ErrorCode.UNSUPPORTED_URL,
            message="The browser blocked a redirect outside WeChat article pages.",
            retryable=False,
        )
    )


def _is_wechat_article_navigation(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "mp.weixin.qq.com"
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and (parsed.path == "/s" or parsed.path.startswith("/s/"))
    )


def _default_playwright_factory() -> Any:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise _browser_error(
            "Browser support is not installed; install the optional browser extra."
        ) from exc
    return async_playwright()


class BrowserSessionManager:
    """Own one exact persistent browser profile stored outside the repository."""

    def __init__(
        self,
        profile_dir: str | Path,
        *,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self._playwright_factory = playwright_factory or _default_playwright_factory
        self._injected_factory = playwright_factory is not None

    def _browser_available(self) -> bool:
        return self._injected_factory or importlib.util.find_spec("playwright") is not None

    def status(self) -> LoginStatus:
        available = self._browser_available()
        authenticated = available and (self.profile_dir / _SESSION_MARKER).is_file()
        if not available:
            state = "not_installed"
        elif authenticated:
            state = "authenticated"
        else:
            state = "logged_out"
        return LoginStatus(
            state=state,
            authenticated=authenticated,
            browser_available=available,
        )

    async def login(self, timeout_seconds: int = 180) -> LoginStatus:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        context: Any | None = None
        try:
            async with self._playwright_factory() as playwright:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=False,
                )
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(_LOGIN_URL, wait_until="domcontentloaded")
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    cookies = await context.cookies(_LOGIN_URL)
                    if _LOGIN_COOKIE_NAMES.intersection(
                        cookie.get("name") for cookie in cookies
                    ):
                        break
                    await asyncio.sleep(0.5)
                else:
                    raise TimeoutError("WeRead login was not confirmed.")
                (self.profile_dir / _SESSION_MARKER).write_text("ok", encoding="utf-8")
                return LoginStatus(
                    state="authenticated",
                    authenticated=True,
                    browser_available=True,
                    message="Login completed in the local browser.",
                )
        except ReaderException:
            raise
        except Exception:
            return LoginStatus(
                state="timed_out_or_failed",
                authenticated=False,
                browser_available=self._browser_available(),
                message="Login was not confirmed before the timeout.",
            )
        finally:
            if context is not None:
                await context.close()

    def logout(self) -> None:
        resolved = self.profile_dir.resolve()
        if resolved.name != "browser-profile" or resolved.parent == resolved:
            raise ValueError("refusing to remove an unmanaged browser profile path")
        if resolved.exists():
            shutil.rmtree(resolved)

    async def page_content(self, url: str) -> str:
        content, _ = await self._load_page(url, article_only=False)
        return content

    async def article_page_content(self, url: str) -> tuple[str, str]:
        return await self._load_page(url, article_only=True)

    async def _load_page(
        self, url: str, *, article_only: bool
    ) -> tuple[str, str]:
        context: Any | None = None
        try:
            async with self._playwright_factory() as playwright:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=True,
                )
                page = context.pages[0] if context.pages else await context.new_page()
                blocked_url: str | None = None
                if article_only:
                    async def guard_navigation(route: Any, request: Any) -> None:
                        nonlocal blocked_url
                        is_main_navigation = (
                            request.is_navigation_request()
                            and request.frame == page.main_frame
                        )
                        if (
                            is_main_navigation
                            and not _is_wechat_article_navigation(request.url)
                        ):
                            blocked_url = request.url
                            await route.abort(error_code="blockedbyclient")
                            return
                        await route.continue_()

                    await page.route("**/*", guard_navigation)
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                except Exception as exc:
                    if blocked_url is not None:
                        raise _unsafe_navigation_error() from exc
                    raise
                return await page.content(), page.url
        except ReaderException:
            raise
        except Exception as exc:
            raise _browser_error("The local browser could not load the page.") from exc
        finally:
            if context is not None:
                await context.close()
