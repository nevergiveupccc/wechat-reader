# Agent installation contract

This file is for an Agent asked to install WeChat Reader MCP from a Git URL.

## Authorized workflow

1. Explain the repository destination and ask for permission before cloning when the destination was not already chosen by the user.
2. Verify `git` and `uv`; do not install system software without explicit permission.
3. Clone the repository, enter it, and run the platform installer. Use the browser option only when the user asks for enhanced WeRead discovery.
4. Run `uv run wechat-reader-mcp doctor` and report PASS/WARN/FAIL without exposing local paths or secrets.
5. Prefer the repository's project-level `.mcp.json`. Before editing any user-level Codex, Claude, or Qoder configuration, show the proposed destination and ask permission. Never overwrite unrelated MCP servers.
6. Install or copy `skills/wechat-reader` only when the target Agent supports skills and the user wants the list-then-select behavior.

Do not start QR login without the user present. Do not request or print cookies, browser profiles, passwords, or tokens. CAPTCHA must be completed normally by the user and must not be bypassed.

The reader returns a maximum of 10 titles per request. Name discovery may be incomplete and is not an official WeChat archive. Optional enhanced discovery only sees Official Accounts followed in the user's local WeRead account and relies on an undocumented interface.

After installation, tell the user which files were changed, how to remove the MCP entry, and that `uv run wechat-reader-mcp logout` removes only this tool's managed local browser session.
