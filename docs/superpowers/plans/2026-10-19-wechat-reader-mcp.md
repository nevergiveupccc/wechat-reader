# WeChat Reader MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a distributable local MCP server that lets Codex, Claude, and Qoder discover up to ten recent WeChat Official Account articles, let the user select up to ten, and read their structured Markdown content without exposing login data.

**Architecture:** A Python package exposes stable Pydantic contracts through a FastMCP stdio server. Discovery, extraction, browser login, persistence, and client configuration are separate modules connected by a `ReaderService`; public discovery is the default and an optional local Playwright profile provides authenticated discovery and browser fallback.

**Tech Stack:** Python 3.11+, uv, official MCP Python SDK/FastMCP, Pydantic 2, httpx, Beautiful Soup 4, lxml, markdownify, platformdirs, Typer, optional Playwright, SQLite, pytest, pytest-asyncio, respx, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-19-wechat-reader-mcp-design.md`

## Global Constraints

- Create a standalone Git repository at `wechat-reader-mcp/`; do not mix product code into the existing `MLIC_v2` files.
- Require Python `>=3.11`; use `pyproject.toml`, a `src/` layout, and uv-compatible console scripts.
- Use a local stdio MCP transport; stdout carries protocol data only and logs go to stderr.
- `list_recent_articles` defaults to 10 and rejects values above 10.
- `read_selected_articles` accepts one to ten unique selections and rejects larger or empty batches.
- Result sets expire after 30 minutes; article cache entries expire after 24 hours by default.
- Public and authenticated discovery must disclose source and completeness and must never claim to be an official complete history.
- Browser profiles and cookies stay in the platform user-data directory and never appear in logs, Git-tracked files, or MCP responses.
- Fallbacks are bounded to one alternate provider or one browser extraction attempt; no infinite retries or captcha bypass.
- Ordinary automated tests use fixtures and mocks; live tests are opt-in and limited to one account query and one article read.
- Keep official authorization as a future provider value only; version 1 does not request account credentials or implement official publishing APIs.

## Review Focus

- Reject lookalike hosts such as `mp.weixin.qq.com.evil.example` while accepting canonical HTTPS `mp.weixin.qq.com` article URLs; Task 3 pins this behavior.
- Treat malformed, duplicate, zero, negative, and more-than-ten selections as input errors without performing network work; Task 7 pins this behavior.
- Preserve successful article results when another item in the same batch is deleted, blocked, or malformed; Task 7 pins this behavior.
- When an authenticated session expires during discovery, fall back once to public search and mark the returned source accurately; Task 6 pins this behavior.
- Never emit cookie values, browser-profile paths, QR contents, or machine-specific absolute paths from status, diagnostics, logs, or MCP responses; Tasks 5, 8, and 9 pin this behavior.

---

## Planned File Map

```text
wechat-reader-mcp/
├── .github/workflows/ci.yml                 # cross-platform unit and packaging checks
├── .gitignore                               # Python, cache, browser, and local config exclusions
├── .mcp.json                                # Qoder project-level stdio configuration
├── AGENT_INSTALL.md                         # deterministic instructions for coding agents
├── LICENSE                                  # project license
├── README.md                                # user installation, usage, limits, and safety
├── pyproject.toml                           # package metadata, dependencies, extras, scripts
├── uv.lock                                  # reproducible dependency resolution
├── clients/
│   ├── claude/mcp.json                      # Claude configuration example
│   ├── codex/config.toml                    # Codex configuration example
│   └── qoder/mcp.json                       # Qoder user-level configuration example
├── docs/superpowers/
│   ├── plans/2026-10-19-wechat-reader-mcp.md
│   └── specs/2026-10-19-wechat-reader-mcp-design.md
├── scripts/
│   ├── install.ps1                          # Windows source installer and diagnostics
│   └── install.sh                           # macOS/Linux source installer and diagnostics
├── skills/wechat-reader/
│   └── SKILL.md                             # portable list-then-select workflow
├── src/wechat_reader_mcp/
│   ├── __init__.py                          # package version
│   ├── cli.py                               # serve/login/logout/doctor commands
│   ├── errors.py                            # typed domain errors
│   ├── models.py                            # stable request and response models
│   ├── server.py                            # FastMCP tool registration and stdio entrypoint
│   ├── service.py                           # orchestration, fallback, and batch isolation
│   ├── config.py                            # settings and platform paths
│   ├── storage.py                           # SQLite result-set and article cache
│   ├── discovery/
│   │   ├── base.py                          # provider protocol and provider page model
│   │   ├── public.py                        # Sogou public discovery and redirect resolution
│   │   └── authenticated.py                 # Playwright/WeRead authenticated discovery
│   ├── extraction/
│   │   ├── fetch.py                         # HTTP and browser fetchers
│   │   └── parse.py                         # WeChat HTML metadata and Markdown parser
│   └── browser/
│       └── session.py                       # persistent local browser profile lifecycle
└── tests/
    ├── fixtures/
    │   ├── article_standard.html
    │   ├── article_script_timestamp.html
    │   ├── article_antibot.html
    │   ├── sogou_results.html
    │   └── weread_results.html
    ├── test_browser_session.py
    ├── test_cli.py
    ├── test_discovery_authenticated.py
    ├── test_discovery_public.py
    ├── test_extraction.py
    ├── test_models.py
    ├── test_distribution.py
    ├── test_live_smoke.py
    ├── test_server.py
    ├── test_service.py
    └── test_storage.py
```

### Task 1: Standalone Package and Stable Domain Contracts

**Files:**
- Create: `wechat-reader-mcp/.gitignore`
- Create: `wechat-reader-mcp/LICENSE`
- Create: `wechat-reader-mcp/pyproject.toml`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/__init__.py`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/errors.py`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/models.py`
- Create: `wechat-reader-mcp/tests/test_models.py`
- Copy: `docs/superpowers/specs/2026-10-19-wechat-reader-mcp-design.md` to `wechat-reader-mcp/docs/superpowers/specs/2026-10-19-wechat-reader-mcp-design.md`
- Copy: `docs/superpowers/plans/2026-10-19-wechat-reader-mcp.md` to `wechat-reader-mcp/docs/superpowers/plans/2026-10-19-wechat-reader-mcp.md`

**Interfaces:**
- Consumes: the approved design spec only.
- Produces: `DiscoverySource`, `DiscoveryMode`, `ErrorCode`, `ReaderError`, `AccountCandidate`, `ArticleSummary`, `ArticleContent`, `DiscoveryPage`, `ArticleReadResult`, `BatchReadResponse`, and `ReaderStatus` Pydantic models; `ReaderException(error: ReaderError)`.

- [ ] **Step 1: Initialize the standalone repository and package metadata**

Create `wechat-reader-mcp/`, run `git init`, copy the approved docs, and define a `wechat-reader-mcp` console script. Declare base dependencies for MCP, Pydantic, httpx, Beautiful Soup, lxml, markdownify, platformdirs, and Typer; declare Playwright in a `browser` extra and pytest tooling in a `dev` group.

- [ ] **Step 2: Write failing model-validation tests**

Add tests named `test_discovery_page_limit_cannot_exceed_ten`, `test_batch_response_preserves_per_item_errors`, and `test_reader_status_serialization_contains_no_secret_fields`. Assert the exact maximum of 10 and the four source values `public_search`, `authenticated_search`, `official_authorized`, and `direct_url`.

- [ ] **Step 3: Run the tests and verify failure**

Run: `uv run pytest tests/test_models.py -v`

Expected: FAIL because the models do not exist.

- [ ] **Step 4: Implement the domain enums, models, and exception**

Use Pydantic field validators for count and selection constraints. `ReaderError` contains `code`, `message`, `retryable`, and optional `details`; it contains no raw exception, cookie, or path fields.

- [ ] **Step 5: Run contract tests and package import check**

Run: `uv run pytest tests/test_models.py -v`

Expected: PASS.

Run: `uv run python -c "import wechat_reader_mcp; print(wechat_reader_mcp.__version__)"`

Expected: prints the initial semantic version.

- [ ] **Step 6: Commit the package foundation**

```bash
git add .
git commit -m "chore: initialize wechat reader mcp package"
```

### Task 2: Platform Paths, Settings, and TTL Storage

**Files:**
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/config.py`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/storage.py`
- Create: `wechat-reader-mcp/tests/test_storage.py`

**Interfaces:**
- Consumes: `ArticleContent`, `ArticleSummary`, and `ReaderException` from Task 1.
- Produces: `AppPaths.from_platform(app_name: str = "wechat-reader-mcp") -> AppPaths`, `Settings.from_env() -> Settings`, and `SqliteStore` methods `save_result_set(articles) -> str`, `get_result_set(result_set_id) -> list[ArticleSummary]`, `put_article(article) -> None`, `get_article(url) -> ArticleContent | None`, and `purge_expired() -> int`.

- [ ] **Step 1: Write failing path and TTL tests**

Test that cache, data, log, and browser-profile directories are derived through `platformdirs`, result sets expire at exactly 30 minutes, articles expire at exactly 24 hours, and an expired result set raises `ErrorCode.RESULT_SET_EXPIRED`.

- [ ] **Step 2: Run storage tests and verify failure**

Run: `uv run pytest tests/test_storage.py -v`

Expected: FAIL because settings and storage are undefined.

- [ ] **Step 3: Implement settings and SQLite storage**

Inject a clock callable into `SqliteStore` so expiry tests do not sleep. Store article models as JSON with canonical URLs as keys. Create directories lazily and never place runtime data under the Git checkout.

- [ ] **Step 4: Run storage tests**

Run: `uv run pytest tests/test_storage.py -v`

Expected: PASS, including expiry and cache-hit cases.

- [ ] **Step 5: Commit local persistence**

```bash
git add src/wechat_reader_mcp/config.py src/wechat_reader_mcp/storage.py tests/test_storage.py
git commit -m "feat: add local settings and ttl cache"
```

### Task 3: Safe Direct-URL Fetching and Article Extraction

**Files:**
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/extraction/__init__.py`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/extraction/fetch.py`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/extraction/parse.py`
- Create: `wechat-reader-mcp/tests/fixtures/article_standard.html`
- Create: `wechat-reader-mcp/tests/fixtures/article_script_timestamp.html`
- Create: `wechat-reader-mcp/tests/fixtures/article_antibot.html`
- Create: `wechat-reader-mcp/tests/test_extraction.py`

**Interfaces:**
- Consumes: `ArticleContent`, `ErrorCode`, and `ReaderException` from Task 1.
- Produces: `normalize_wechat_article_url(url: str) -> str`, `HttpArticleFetcher.fetch(url: str) -> str`, and `WeChatArticleParser.parse(url: str, html: str) -> ArticleContent`.

- [ ] **Step 1: Add representative sanitized HTML fixtures**

Fixtures cover the standard `#js_content` container, title/account metadata, inline `var ct` timestamp recovery, canonical link, image URLs, and an anti-bot page with no article container. Do not copy complete copyrighted articles; use minimal synthetic fixture text.

- [ ] **Step 2: Write failing URL and parser tests**

Add tests that accept `https://mp.weixin.qq.com/s/...`, normalize query-form article URLs, reject non-HTTPS schemes and lookalike hosts, extract metadata and Markdown, recover the script timestamp, and classify an anti-bot response as `ErrorCode.RATE_LIMITED_OR_CAPTCHA`.

- [ ] **Step 3: Run extraction tests and verify failure**

Run: `uv run pytest tests/test_extraction.py -v`

Expected: FAIL because fetchers and parser are undefined.

- [ ] **Step 4: Implement canonical URL validation and the HTTP fetcher**

Use `urllib.parse` for exact hostname and scheme checks and `httpx.AsyncClient` with bounded connect/read timeouts, redirects enabled, and a normal browser user agent. Map timeouts, unavailable pages, and anti-bot responses to typed errors.

- [ ] **Step 5: Implement HTML-to-article parsing**

Require a recognized article body container before success. Sanitize scripts and styles, preserve meaningful links and image URLs, and convert the article body to Markdown with normalized whitespace.

- [ ] **Step 6: Run extraction tests**

Run: `uv run pytest tests/test_extraction.py -v`

Expected: PASS.

- [ ] **Step 7: Commit direct article reading**

```bash
git add src/wechat_reader_mcp/extraction tests/fixtures/article_*.html tests/test_extraction.py
git commit -m "feat: read public wechat article urls"
```

### Task 4: Public Account Discovery Provider

**Files:**
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/discovery/__init__.py`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/discovery/base.py`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/discovery/public.py`
- Create: `wechat-reader-mcp/tests/fixtures/sogou_results.html`
- Create: `wechat-reader-mcp/tests/test_discovery_public.py`

**Interfaces:**
- Consumes: `AccountCandidate`, `ArticleSummary`, `DiscoverySource`, and typed errors from Task 1; URL normalization from Task 3.
- Produces: `ProviderPage(articles, next_cursor, is_complete, warning)`, `DiscoveryProvider.search(account: str, limit: int, cursor: str | None) -> ProviderPage`, `SogouDiscoveryProvider.search(...)`, `SogouDiscoveryProvider.resolve_accounts(query: str) -> list[AccountCandidate]`, and `SogouUrlResolver.resolve(url: str) -> str | None`.

- [ ] **Step 1: Add a sanitized public-search fixture**

Include more than ten entries, duplicate article URLs, two account names, mixed publication dates, and one unresolved redirect.

- [ ] **Step 2: Write failing public-discovery tests**

Assert exact limit enforcement, newest-first sorting for trustworthy dates, canonical-URL deduplication, grouping of ambiguous account candidates, cursor round-tripping, and preservation of unresolved results with a completeness warning rather than invented URLs.

- [ ] **Step 3: Run public discovery tests and verify failure**

Run: `uv run pytest tests/test_discovery_public.py -v`

Expected: FAIL because provider interfaces are undefined.

- [ ] **Step 4: Implement provider contracts and the public parser**

Keep HTTP transport injectable for tests. Encode cursors as opaque page tokens owned by the provider. Mark every result `DiscoverySource.PUBLIC_SEARCH` and `is_complete=False`.

- [ ] **Step 5: Implement bounded redirect resolution**

Follow at most the configured redirect count, validate the final WeChat URL with Task 3, and return `None` on captcha or invalid destinations without retry loops.

- [ ] **Step 6: Run public discovery tests**

Run: `uv run pytest tests/test_discovery_public.py -v`

Expected: PASS with no live requests.

- [ ] **Step 7: Commit public discovery**

```bash
git add src/wechat_reader_mcp/discovery tests/fixtures/sogou_results.html tests/test_discovery_public.py
git commit -m "feat: discover public wechat articles"
```

### Task 5: Local Browser Login and Authenticated Discovery

**Files:**
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/browser/__init__.py`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/browser/session.py`
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/discovery/authenticated.py`
- Modify: `wechat-reader-mcp/src/wechat_reader_mcp/extraction/fetch.py`
- Create: `wechat-reader-mcp/tests/fixtures/weread_results.html`
- Create: `wechat-reader-mcp/tests/test_browser_session.py`
- Create: `wechat-reader-mcp/tests/test_discovery_authenticated.py`

**Interfaces:**
- Consumes: `AppPaths`, `Settings`, discovery provider contracts, article models, and typed errors from Tasks 1, 2, and 4.
- Produces: `BrowserSessionManager.login(timeout_seconds: int = 180) -> LoginStatus`, `logout() -> None`, `status() -> LoginStatus`, `page_content(url: str) -> str`, `BrowserArticleFetcher.fetch(url: str) -> str`, and `WeReadDiscoveryProvider.search(account, limit, cursor) -> ProviderPage`.

- [ ] **Step 1: Write failing browser-profile security tests**

Mock Playwright and assert `launch_persistent_context` receives the platform browser-profile directory, login results contain only boolean/status metadata, logout removes only the exact managed profile directory, and no cookie values or absolute paths occur in serialized results or logs.

- [ ] **Step 2: Write failing authenticated-result parser tests**

Using the sanitized fixture, assert title, account, publication time, canonical URL, newest-first order, ten-item cap, `DiscoverySource.AUTHENTICATED_SEARCH`, and a typed `LOGIN_REQUIRED` result when the authenticated marker is absent.

- [ ] **Step 3: Run browser tests and verify failure**

Run: `uv run pytest tests/test_browser_session.py tests/test_discovery_authenticated.py -v`

Expected: FAIL because browser lifecycle and provider are undefined.

- [ ] **Step 4: Implement the persistent local browser session manager**

Use Playwright's persistent context with a visible browser for `login`. Keep profile paths internal, wait only up to the explicit timeout, and never export storage state or cookies.

- [ ] **Step 5: Implement authenticated discovery and browser page fetching**

Separate DOM parsing from live navigation so fixture tests remain deterministic. Detect login expiry and captcha pages explicitly. Do not attempt captcha solving.

- [ ] **Step 6: Run browser tests**

Run: `uv run pytest tests/test_browser_session.py tests/test_discovery_authenticated.py -v`

Expected: PASS with Playwright mocked and no browser launched.

- [ ] **Step 7: Commit optional authenticated discovery**

```bash
git add src/wechat_reader_mcp/browser src/wechat_reader_mcp/discovery/authenticated.py tests/fixtures/weread_results.html tests/test_browser_session.py tests/test_discovery_authenticated.py
git commit -m "feat: add local authenticated discovery"
```

### Task 6: Reader Service, Provider Selection, and Bounded Fallbacks

**Files:**
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/service.py`
- Create: `wechat-reader-mcp/tests/test_service.py`

**Interfaces:**
- Consumes: store, HTTP/browser fetchers, parser, public provider, authenticated provider, and all domain models.
- Produces: `ReaderService.resolve_account(query: str) -> list[AccountCandidate]`, `list_recent_articles(account: str, limit: int = 10, mode: DiscoveryMode = AUTO, cursor: str | None = None) -> DiscoveryPage`, `read_article_url(url: str) -> ArticleReadResult`, `read_selected_articles(result_set_id: str, selections: list[int]) -> BatchReadResponse`, and `get_status() -> ReaderStatus`.

- [ ] **Step 1: Write failing provider-selection tests**

Assert that `AUTO` uses authenticated discovery when healthy, falls back exactly once to public search on `LOGIN_REQUIRED`, reports `public_search` after fallback, never falls back for invalid user input, and saves returned articles under a 30-minute result set.

- [ ] **Step 2: Write failing extraction-fallback and cache tests**

Assert an article cache hit avoids network work; HTTP extraction failure triggers at most one browser fetch; captcha does not loop; and successful extraction is cached for 24 hours.

- [ ] **Step 3: Run service tests and verify failure**

Run: `uv run pytest tests/test_service.py -v`

Expected: FAIL because `ReaderService` is undefined.

- [ ] **Step 4: Implement account resolution and discovery orchestration**

Keep provider order explicit and injectable. Save the exact normalized result list before returning it, and carry warnings and completeness from the actual provider used.

- [ ] **Step 5: Implement direct and batch article reading**

Use cache, HTTP extraction, and one browser fallback in that order. Convert each domain exception into an `ArticleReadResult` so batch work preserves other successes.

- [ ] **Step 6: Run service tests**

Run: `uv run pytest tests/test_service.py -v`

Expected: PASS, including expired-login fallback and partial batch success.

- [ ] **Step 7: Commit the orchestration layer**

```bash
git add src/wechat_reader_mcp/service.py tests/test_service.py
git commit -m "feat: orchestrate discovery and article reading"
```

### Task 7: FastMCP Tools and Selection Validation

**Files:**
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/server.py`
- Create: `wechat-reader-mcp/tests/test_server.py`

**Interfaces:**
- Consumes: `ReaderService` from Task 6 and stable models from Task 1.
- Produces: `create_mcp_server(service_factory: Callable[[], ReaderService]) -> FastMCP`, registered tools `resolve_account`, `list_recent_articles`, `read_selected_articles`, `read_article_url`, and `get_reader_status`, plus `run_stdio() -> None`.

- [ ] **Step 1: Write failing MCP registration tests**

Use an in-memory/fake service and assert the exact five tool names and JSON-compatible responses. Verify the service is not called when arguments fail validation.

- [ ] **Step 2: Write failing selection boundary tests**

Cover empty selections, zero, negative values, duplicates, non-integers, eleven selections, and an index outside the stored result set. Assert one to ten unique valid indices are accepted.

- [ ] **Step 3: Run server tests and verify failure**

Run: `uv run pytest tests/test_server.py -v`

Expected: FAIL because server creation and tools are undefined.

- [ ] **Step 4: Implement FastMCP tool registration**

Keep tool docstrings explicit about public-search incompleteness and the ten-item maximum. Convert validation and domain failures into stable `ReaderError` payloads without stack traces.

- [ ] **Step 5: Implement stdio startup discipline**

Configure logging to stderr before starting `mcp.run(transport="stdio")`; add a test that captures stdout during startup setup and finds no log text.

- [ ] **Step 6: Run server tests**

Run: `uv run pytest tests/test_server.py -v`

Expected: PASS.

- [ ] **Step 7: Commit the MCP server**

```bash
git add src/wechat_reader_mcp/server.py tests/test_server.py
git commit -m "feat: expose wechat reader mcp tools"
```

### Task 8: CLI Commands and Safe Diagnostics

**Files:**
- Create: `wechat-reader-mcp/src/wechat_reader_mcp/cli.py`
- Create: `wechat-reader-mcp/tests/test_cli.py`
- Modify: `wechat-reader-mcp/pyproject.toml`

**Interfaces:**
- Consumes: `run_stdio`, `BrowserSessionManager`, `ReaderService.get_status`, settings, and paths.
- Produces: console commands `serve`, `login`, `logout`, and `doctor`; no-argument invocation aliases `serve` for MCP client compatibility.

- [ ] **Step 1: Write failing CLI tests**

Using Typer's test runner and fakes, assert command exit codes, login timeout messaging, logout idempotence, `doctor` checks for Python/package/cache/browser/network readiness, and all output redacts cookies, QR contents, tokens, and absolute browser-profile paths.

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `uv run pytest tests/test_cli.py -v`

Expected: FAIL because the CLI does not exist.

- [ ] **Step 3: Implement CLI composition and dependency factories**

The default callback starts stdio only when no subcommand is provided. `doctor` performs read-only or temporary-file checks and prints actionable pass/warn/fail rows without secrets.

- [ ] **Step 4: Run CLI and package-entrypoint tests**

Run: `uv run pytest tests/test_cli.py -v`

Expected: PASS.

Run: `uv run wechat-reader-mcp --help`

Expected: lists `serve`, `login`, `logout`, and `doctor`.

- [ ] **Step 5: Commit CLI operations**

```bash
git add src/wechat_reader_mcp/cli.py tests/test_cli.py pyproject.toml uv.lock
git commit -m "feat: add login and diagnostic commands"
```

### Task 9: Agent Skill, Client Configurations, Installers, and CI

**Files:**
- Create: `wechat-reader-mcp/skills/wechat-reader/SKILL.md`
- Create: `wechat-reader-mcp/.mcp.json`
- Create: `wechat-reader-mcp/clients/codex/config.toml`
- Create: `wechat-reader-mcp/clients/claude/mcp.json`
- Create: `wechat-reader-mcp/clients/qoder/mcp.json`
- Create: `wechat-reader-mcp/scripts/install.ps1`
- Create: `wechat-reader-mcp/scripts/install.sh`
- Create: `wechat-reader-mcp/AGENT_INSTALL.md`
- Create: `wechat-reader-mcp/README.md`
- Create: `wechat-reader-mcp/.github/workflows/ci.yml`
- Modify: `wechat-reader-mcp/.gitignore`
- Create: `wechat-reader-mcp/tests/test_distribution.py`

**Interfaces:**
- Consumes: the installed `wechat-reader-mcp` entry point and five MCP tools.
- Produces: clone-to-install instructions, client-specific configuration templates, a portable list-then-select skill, cross-platform installer scripts, and CI/package verification.

- [ ] **Step 1: Write failing distribution tests**

Assert all JSON and TOML templates parse; `.mcp.json` launches `uv run wechat-reader-mcp serve` from the repository; skill metadata activates for account names and article URLs; installers call `doctor`; docs contain the ten-item cap, source/completeness warning, QR-login boundary, and no-captcha-bypass rule; tracked templates contain no absolute local paths or secret-like values.

- [ ] **Step 2: Run distribution tests and verify failure**

Run: `uv run pytest tests/test_distribution.py -v`

Expected: FAIL because artifacts are absent.

- [ ] **Step 3: Write the portable skill and client templates**

The skill instructs agents to list titles first, wait for the user's selection, read at most ten, surface partial failures, and never describe public discovery as official completeness. Keep client-specific command syntax in `clients/`, not in core skill instructions.

- [ ] **Step 4: Write safe source installers and agent instructions**

Installers verify `git` and `uv`, sync the package, optionally install Playwright only when requested, run `doctor`, and print rather than silently mutate unsupported client configuration. `AGENT_INSTALL.md` requires permission confirmation before filesystem, installation, browser, or user-level configuration changes.

- [ ] **Step 5: Write README and CI workflow**

Document clone/install/configure/use/troubleshoot flows, supported limitations, local data locations, and copyright/platform-respect guidance. CI runs unit tests and builds wheels on Windows, macOS, and Ubuntu for Python 3.11, 3.12, and 3.13; live network tests remain manual and opt-in.

- [ ] **Step 6: Run distribution and full unit tests**

Run: `uv run pytest -v -m "not live"`

Expected: all tests PASS with no live WeChat or Sogou traffic.

Run: `uv build`

Expected: source distribution and wheel are created successfully.

- [ ] **Step 7: Run local install smoke test**

Run: `uv tool install --force .`

Run: `wechat-reader-mcp doctor`

Expected: package, cache, and MCP checks pass; browser capability is either PASS or an actionable optional warning.

- [ ] **Step 8: Commit distribution artifacts**

```bash
git add .
git commit -m "docs: add agent installation and client configs"
```

### Task 10: Bounded Live Verification and Release Readiness

**Files:**
- Create: `wechat-reader-mcp/tests/test_live_smoke.py`
- Modify: `wechat-reader-mcp/README.md`

**Interfaces:**
- Consumes: the installed CLI, `ReaderService`, public discovery, and direct article reading.
- Produces: opt-in `live` pytest marker and documented release checklist.

- [ ] **Step 1: Add an opt-in live smoke test**

Require `WECHAT_READER_RUN_LIVE=1`. Perform at most one account discovery with `limit=1` and one direct article read using a maintainer-supplied public URL environment variable. Skip, rather than fail, when variables are absent.

- [ ] **Step 2: Verify default tests never execute live traffic**

Run: `uv run pytest -v -m "not live"`

Expected: PASS and no live provider calls.

- [ ] **Step 3: Run the bounded live test when a test URL is available**

Run: `uv run pytest tests/test_live_smoke.py -v -m live`

Expected: one discovery request and one article read at most; failures are reported with typed error codes and do not trigger retries beyond the designed fallback.

- [ ] **Step 4: Perform client smoke checks**

Install the local repository into Codex, Claude, and Qoder using the checked-in templates. In each client, verify `get_reader_status`, one direct URL read, one account listing, and a one-item selection. Record only pass/fail and sanitized error categories in the release checklist.

- [ ] **Step 5: Run final verification**

Run: `uv run pytest -v -m "not live"`

Run: `uv build`

Run: `git status --short`

Expected: tests pass, packages build, and only intentional release-checklist edits remain.

- [ ] **Step 6: Commit release readiness**

```bash
git add tests/test_live_smoke.py README.md
git commit -m "test: add bounded live smoke coverage"
```
