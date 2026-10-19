from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    "relative",
    [
        ".mcp.json",
        "clients/claude/mcp.json",
        "clients/qoder/mcp.json",
    ],
)
def test_json_client_templates_parse(relative: str) -> None:
    payload = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    server = payload["mcpServers"]["wechat-reader"]
    assert server["command"] == "uv"
    assert server["args"] == ["run", "wechat-reader-mcp", "serve"]


def test_codex_template_is_valid_toml() -> None:
    payload = tomllib.loads(
        (ROOT / "clients/codex/config.toml").read_text(encoding="utf-8")
    )
    server = payload["mcp_servers"]["wechat-reader"]
    assert server["command"] == "uv"
    assert server["args"] == ["run", "wechat-reader-mcp", "serve"]


def test_root_mcp_manifest_runs_from_repository() -> None:
    payload = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = payload["mcpServers"]["wechat-reader"]
    assert server["type"] == "stdio"
    assert server["cwd"] == "."


def test_skill_activates_for_account_names_and_article_urls() -> None:
    skill = (ROOT / "skills/wechat-reader/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\n")
    frontmatter = skill.split("---", 2)[1]
    assert re.search(r"(?m)^name: [a-z0-9-]+$", frontmatter)
    assert re.search(r"(?m)^description: Use when ", frontmatter)
    lowered = skill.lower()
    for phrase in (
        "official account name",
        "mp.weixin.qq.com",
        "list_recent_articles",
        "read_selected_articles",
        "read_article_url",
    ):
        assert phrase in lowered


@pytest.mark.parametrize("relative", ["scripts/install.ps1", "scripts/install.sh"])
def test_installers_verify_then_run_doctor(relative: str) -> None:
    script = (ROOT / relative).read_text(encoding="utf-8").lower()
    assert "git" in script
    assert "uv" in script
    assert "doctor" in script
    assert "browser" in script
    assert "playwright" in script


def test_docs_capture_safety_and_completeness_contract() -> None:
    docs = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in ("README.md", "AGENT_INSTALL.md", "skills/wechat-reader/SKILL.md")
    ).lower()
    for phrase in (
        "maximum of 10",
        "may be incomplete",
        "qr",
        "captcha",
        "permission",
    ):
        assert phrase in docs


def test_templates_contain_no_local_absolute_paths_or_secret_values() -> None:
    files = [
        ROOT / ".mcp.json",
        ROOT / "clients/codex/config.toml",
        ROOT / "clients/claude/mcp.json",
        ROOT / "clients/qoder/mcp.json",
        ROOT / "skills/wechat-reader/SKILL.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert not re.search(r"(?i)(?:[a-z]:\\|/users/|/home/)", combined)
    assert not re.search(
        r'(?i)(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*["\'][^<][^"\']+["\']',
        combined,
    )


def test_ci_covers_supported_operating_systems_and_python_versions() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for value in (
        "ubuntu-latest",
        "windows-latest",
        "macos-latest",
        '"3.11"',
        '"3.12"',
        '"3.13"',
        'pytest -v -m "not live"',
        "uv build",
    ):
        assert value in workflow
