"""Human-facing commands for serving, login, logout, and safe diagnostics."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from dataclasses import dataclass

import httpx
import typer

from wechat_reader_mcp import __version__
from wechat_reader_mcp.browser.session import BrowserSessionManager
from wechat_reader_mcp.config import Settings
from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.server import run_stdio

app = typer.Typer(
    name="wechat-reader-mcp",
    help="Discover and read public WeChat Official Account articles through MCP.",
    no_args_is_help=False,
)


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    level: str
    message: str


def create_browser_manager() -> BrowserSessionManager:
    settings = Settings.from_env()
    return BrowserSessionManager(settings.paths.browser_profile_dir)


def _network_ready() -> bool:
    try:
        with httpx.Client(timeout=5, follow_redirects=True) as client:
            response = client.head("https://mp.weixin.qq.com/")
        return response.status_code < 500
    except httpx.HTTPError:
        return False


def collect_doctor_checks() -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []
    python_ok = sys.version_info >= (3, 11)
    checks.append(
        DiagnosticCheck(
            "Python",
            "PASS" if python_ok else "FAIL",
            "Supported runtime" if python_ok else "Python 3.11 or newer is required",
        )
    )
    checks.append(DiagnosticCheck("Package", "PASS", f"Version {__version__} is available"))

    cache_ok = False
    try:
        cache_dir = Settings.from_env().paths.cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache_dir):
            cache_ok = True
    except OSError:
        pass
    checks.append(
        DiagnosticCheck(
            "Cache",
            "PASS" if cache_ok else "FAIL",
            "Local cache is writable" if cache_ok else "Local cache is not writable",
        )
    )

    browser_status = create_browser_manager().status()
    checks.append(
        DiagnosticCheck(
            "Browser",
            "PASS" if browser_status.browser_available else "WARN",
            (
                "Optional browser support is available"
                if browser_status.browser_available
                else "Optional browser support is not installed"
            ),
        )
    )

    network_ok = _network_ready()
    checks.append(
        DiagnosticCheck(
            "Network",
            "PASS" if network_ok else "WARN",
            (
                "Public endpoint is reachable"
                if network_ok
                else "Public endpoint was not reachable; direct and name search may fail"
            ),
        )
    )
    return checks


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Start the stdio MCP server when no explicit command is supplied."""

    if ctx.invoked_subcommand is None:
        run_stdio()


@app.command()
def serve() -> None:
    """Start the MCP server over stdio."""

    run_stdio()


@app.command()
def login(
    timeout: int = typer.Option(
        180,
        "--timeout",
        min=1,
        max=900,
        help="Seconds to wait for local QR login.",
    ),
) -> None:
    """Open a visible local browser and wait for the user to complete login."""

    try:
        status = asyncio.run(
            create_browser_manager().login(timeout_seconds=timeout)
        )
    except (ReaderException, OSError):
        typer.echo("Login could not start. Run 'doctor' and install optional browser support.")
        raise typer.Exit(code=1) from None
    if status.authenticated:
        typer.echo("Login confirmed. Session data remains only in the local browser profile.")
        return
    typer.echo("Login was not confirmed. Try again and complete the QR scan before timeout.")
    raise typer.Exit(code=1)


@app.command()
def logout() -> None:
    """Remove only this tool's managed local browser session."""

    try:
        create_browser_manager().logout()
    except (OSError, ValueError):
        typer.echo("Logout could not remove the managed session.")
        raise typer.Exit(code=1) from None
    typer.echo("Logged out. The managed local browser session has been removed.")


@app.command()
def doctor() -> None:
    """Check local runtime readiness without printing secrets or local paths."""

    checks = collect_doctor_checks()
    for check in checks:
        typer.echo(f"[{check.level}] {check.name}: {check.message}")
    if any(check.level == "FAIL" for check in checks):
        raise typer.Exit(code=1)
