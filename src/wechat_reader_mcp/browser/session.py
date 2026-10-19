"""Manage a user-controlled local browser profile without exposing secrets."""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
        context: Any | None = None
        try:
            async with self._playwright_factory() as playwright:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=True,
                )
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                return await page.content()
        except ReaderException:
            raise
        except Exception as exc:
            raise _browser_error("The local browser could not load the page.") from exc
        finally:
            if context is not None:
                await context.close()
