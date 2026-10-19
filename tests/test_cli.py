from __future__ import annotations

from dataclasses import dataclass

from typer.testing import CliRunner

from wechat_reader_mcp.models import LoginStatus

runner = CliRunner()


class FakeBrowserManager:
    def __init__(self, status: LoginStatus) -> None:
        self.login_status = status
        self.login_timeouts: list[int] = []
        self.logout_calls = 0

    async def login(self, timeout_seconds: int = 180) -> LoginStatus:
        self.login_timeouts.append(timeout_seconds)
        return self.login_status

    def logout(self) -> None:
        self.logout_calls += 1


def test_no_argument_and_serve_command_start_stdio(monkeypatch) -> None:
    from wechat_reader_mcp import cli

    calls: list[str] = []
    monkeypatch.setattr(cli, "run_stdio", lambda: calls.append("serve"))

    no_args = runner.invoke(cli.app, [])
    explicit = runner.invoke(cli.app, ["serve"])

    assert no_args.exit_code == 0
    assert explicit.exit_code == 0
    assert calls == ["serve", "serve"]


def test_login_timeout_has_safe_actionable_message(monkeypatch) -> None:
    from wechat_reader_mcp import cli

    manager = FakeBrowserManager(
        LoginStatus(
            state="timed_out_or_failed",
            authenticated=False,
            browser_available=True,
            message="do not echo C:/secret/browser-profile token=abc cookie=xyz",
        )
    )
    monkeypatch.setattr(cli, "create_browser_manager", lambda: manager)

    result = runner.invoke(cli.app, ["login", "--timeout", "7"])

    assert result.exit_code == 1
    assert manager.login_timeouts == [7]
    assert "not confirmed" in result.output.lower()
    lowered = result.output.lower()
    assert "token" not in lowered
    assert "cookie" not in lowered
    assert "browser-profile" not in lowered


def test_logout_is_idempotent(monkeypatch) -> None:
    from wechat_reader_mcp import cli

    manager = FakeBrowserManager(
        LoginStatus(
            state="logged_out",
            authenticated=False,
            browser_available=True,
        )
    )
    monkeypatch.setattr(cli, "create_browser_manager", lambda: manager)

    first = runner.invoke(cli.app, ["logout"])
    second = runner.invoke(cli.app, ["logout"])

    assert first.exit_code == second.exit_code == 0
    assert manager.logout_calls == 2
    assert "logged out" in second.output.lower()


@dataclass(frozen=True)
class FakeCheck:
    name: str
    level: str
    message: str


def test_doctor_reports_required_readiness_rows_without_secrets(monkeypatch) -> None:
    from wechat_reader_mcp import cli

    checks = [
        FakeCheck("Python", "PASS", "Supported runtime"),
        FakeCheck("Package", "PASS", "Version is available"),
        FakeCheck("Cache", "PASS", "Local cache is writable"),
        FakeCheck("Browser", "WARN", "Optional browser support is not installed"),
        FakeCheck("Network", "WARN", "Public endpoint was not reachable"),
    ]
    monkeypatch.setattr(cli, "collect_doctor_checks", lambda: checks)

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 0
    for name in ("Python", "Package", "Cache", "Browser", "Network"):
        assert name in result.output
    lowered = result.output.lower()
    assert "cookie" not in lowered
    assert "token=" not in lowered
    assert "browser-profile" not in lowered


def test_help_lists_all_commands() -> None:
    from wechat_reader_mcp.cli import app

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("serve", "login", "logout", "doctor"):
        assert command in result.output
