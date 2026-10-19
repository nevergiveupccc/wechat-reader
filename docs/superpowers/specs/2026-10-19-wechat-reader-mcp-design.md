# WeChat Reader MCP Design

Date: 2026-10-19

## 1. Purpose

Build a distributable local MCP server that lets Codex, Claude, Qoder, and other MCP-capable agents discover and read public WeChat Official Account articles.

The primary user flows are:

1. Provide an article URL and read that article.
2. Provide an Official Account name or related link, view up to ten recently discovered article titles, then select one to ten articles to read.
3. Continue to the next page of results without scanning the account's full history.
4. Clone a GitHub repository and let an agent install, configure, and verify the MCP server after the user approves required permissions.

The system must report the origin and completeness of every discovery result. It must never present public-search results as an official, complete account history.

## 2. Product Boundaries

### Included in version 1

- Read public `mp.weixin.qq.com` article URLs.
- Extract title, account, publication time when available, canonical URL, and Markdown body.
- Resolve an account name or related link into account candidates.
- List at most ten recently discovered articles per page.
- Let the user select one to ten articles from a result set for full reading.
- Support public discovery without login.
- Support an optional local browser login for enhanced discovery.
- Provide Codex, Claude, and Qoder configuration templates.
- Support Git clone plus local installation on developer machines.
- Provide `login`, `logout`, and `doctor` commands.
- Cache result sets and article content locally.
- Return explicit partial failures and source-quality metadata.

### Excluded from version 1

- Crawling or mirroring an account's complete history.
- Scheduled subscriptions, daily briefs, or notifications.
- Embeddings, vector databases, or RAG.
- Hosted multi-user service deployment.
- Shared browser sessions or shared WeChat credentials.
- Bypassing captchas, access controls, anti-bot measures, or protocol protections.
- High-volume or commercial harvesting and redistribution.
- Video downloading or advanced multimedia analysis.

## 3. Platform and Distribution Strategy

The project will be a standalone GitHub repository named `wechat-reader-mcp`. It will expose a standard local stdio MCP server so all supported agents share the same implementation.

Initial installation from source:

```powershell
git clone <repository-url>
cd wechat-reader-mcp
uv sync
uv run wechat-reader-mcp doctor
```

After the source distribution is stable, the same package can be published to PyPI and launched with `uvx wechat-reader-mcp`.

The repository will include human-readable installation instructions, agent-oriented installation instructions, operating-system installers, and per-client MCP configuration examples. Agents may perform clone, install, configuration, and verification steps, but user approval remains required for filesystem, command-execution, browser-login, and MCP trust prompts.

Recommended repository structure:

```text
wechat-reader-mcp/
├── src/wechat_reader_mcp/
│   ├── server.py
│   ├── tools/
│   ├── discovery/
│   ├── extraction/
│   ├── models/
│   └── storage/
├── skills/wechat-reader/
├── clients/
│   ├── codex/
│   ├── claude/
│   └── qoder/
├── scripts/
│   ├── install.ps1
│   └── install.sh
├── tests/
├── AGENT_INSTALL.md
├── README.md
├── LICENSE
└── pyproject.toml
```

## 4. Architecture

The implementation is divided into isolated layers:

1. **MCP transport layer** registers tools, validates parameters, and serializes stable response models.
2. **Account resolution layer** distinguishes article URLs, account-related links, and account-name queries.
3. **Discovery layer** queries one or more providers and normalizes candidate articles.
4. **Extraction layer** fetches a selected article and converts its public HTML to structured Markdown.
5. **Browser session layer** manages optional local authenticated discovery and browser-based extraction fallback.
6. **Storage layer** maintains short-lived result sets, cached article bodies, settings, and browser profiles.
7. **Client adapters** contain configuration examples and workflow instructions but no content-fetching logic.

Client-specific differences must remain outside the core discovery and extraction packages.

## 5. Discovery Modes and Accuracy

WeChat does not expose a general public API that accepts an arbitrary account name and returns that account's official latest articles. Official publishing and material APIs require the target account's own credentials or explicit authorization and therefore cannot implement universal account discovery.

Version 1 uses the following modes:

- `public_search`: default zero-configuration discovery through publicly available indexes. Results may be incomplete or delayed.
- `authenticated_search`: optional browser-based discovery using a user-controlled local login session. It can improve freshness but may still be incomplete and can require re-login.
- `official_authorized`: reserved response source for a future connector where the account owner authorizes official API access.
- `direct_url`: used when the user provides the article URL directly.

`auto` mode checks for a usable authenticated session first and otherwise uses public search. If authenticated discovery fails, it may fall back once to public search. The response must disclose the source used, the requested and returned counts, and whether completeness is known.

Public or authenticated discovery results are described as "recently discovered public articles," not "the official latest ten," unless an authorized official source can prove completeness.

## 6. MCP Tool Contract

### `resolve_account`

Accepts an account name or related URL and returns zero or more account candidates. Ambiguous matches must be presented for user confirmation.

### `list_recent_articles`

Inputs:

```json
{
  "account": "机器之心",
  "limit": 10,
  "mode": "auto",
  "cursor": null
}
```

Rules:

- `limit` defaults to 10 and may not exceed 10.
- `cursor` retrieves the next page without scanning all history.
- Results are deduplicated and sorted by publication time when trustworthy timestamps exist.
- A short-lived `result_set_id` is returned so later selections cannot silently shift.

Representative response:

```json
{
  "result_set_id": "rs_abc123",
  "account": "机器之心",
  "requested": 10,
  "returned": 8,
  "discovery_source": "public_search",
  "is_complete": false,
  "warning": "公开搜索可能未覆盖该公众号全部最新文章",
  "articles": []
}
```

### `read_selected_articles`

Accepts a `result_set_id` and one to ten selected indices. Each article is processed independently so one failure does not discard successful reads from the same batch.

### `read_article_url`

Reads one public article URL directly without first creating a discovery list.

### `get_reader_status`

Reports server version, cache status, browser availability, login-session health, and configured discovery providers without exposing credentials or cookies.

## 7. Interaction Flow

For an account name:

```text
User supplies account
  -> resolve account
  -> discover at most ten articles
  -> present numbered titles, dates, sources, and completeness warning
  -> user selects one to ten indices
  -> read selected articles
  -> agent summarizes, compares, or extracts requested information
```

For a direct URL:

```text
User supplies article URL
  -> validate URL
  -> extract article
  -> return structured metadata and Markdown body
```

## 8. Login and Secret Handling

Login is controlled through local CLI commands:

```text
wechat-reader-mcp login
wechat-reader-mcp logout
wechat-reader-mcp doctor
```

`login` opens a local browser and lets the user scan the QR code. Browser profiles and cookies remain in the operating system's application-data directory. They must never be committed, returned by MCP tools, printed in logs, or exposed to the agent context.

The project will not accept cookies pasted into prompts or configuration files. Expired sessions produce a re-login instruction. The project will not automate captcha solving or circumvent account protections.

## 9. Extraction, Fallback, and Error Handling

Article extraction first performs a lightweight HTTP fetch with a normal browser user agent. It verifies the presence of a recognized article container before considering the fetch successful. HTML is sanitized and converted to Markdown while preserving meaningful links and image URLs.

If lightweight extraction fails for a page that may be browser-readable, the implementation may perform one browser-based fallback. If that also fails, it returns a typed error with the original URL and reason.

Discovery follows the same bounded-fallback rule: authenticated search may fall back once to public search. The server must not retry indefinitely, fabricate missing articles, or silently replace one account with another.

Typed error categories include:

- invalid or unsupported URL;
- ambiguous account;
- no discovery results;
- login required or expired;
- rate limited or captcha encountered;
- article deleted or unavailable;
- page structure unsupported;
- network or timeout failure;
- result set expired.

Logs go to stderr or a log file so they cannot corrupt stdio MCP messages.

## 10. Storage and Rate Limits

- Result sets expire after 30 minutes.
- Extracted article bodies expire after 24 hours by default.
- Cache durations are configurable.
- Browser sessions follow the browser profile's lifetime.
- Article requests are rate limited to human-reading speeds.
- Online test and retry paths use bounded request counts.

The cache is local and is not a permanent article archive.

## 11. Testing Strategy

- Unit tests cover URL classification, account matching, deduplication, sorting, limits, cursor behavior, cache expiry, and error mapping.
- Fixture tests cover several saved WeChat article page variants without live network traffic.
- MCP contract tests validate stable inputs, outputs, partial failures, and the hard limit of ten articles.
- Limited live smoke tests query one account and read one article; they are excluded from ordinary unit-test runs.
- Installation tests exercise clone-to-diagnosis workflows on Windows, macOS, and Linux where CI runners are available.
- Client smoke tests verify listing and reading from Codex, Claude, and Qoder.
- Security tests verify that cookies, QR data, browser profiles, and local absolute paths do not appear in Git-tracked files, logs, or MCP responses.

## 12. Version 1 Acceptance Criteria

1. A user can give the GitHub URL to Qoder, approve required prompts, and have it clone, install, register, and diagnose the MCP server.
2. Codex, Claude, and Qoder can invoke the same MCP tool contracts.
3. A valid public article URL returns structured metadata and Markdown content.
4. An account query returns at most ten recently discovered articles with source and completeness metadata.
5. The user can select any one to ten articles from a result set.
6. Expired login, unavailable articles, empty search results, and rate limits produce explicit errors rather than invented content.
7. One failed article does not discard other successful articles in the same batch.
8. Default automated tests do not generate high-volume traffic to WeChat or public search providers.

## 13. Implementation Constraints

- The core is Python and packaged through `pyproject.toml` for `uv`/`uvx` usage.
- The stdio server must write protocol data only to stdout.
- All paths must be resolved through platform-appropriate user data and cache directories.
- Provider interfaces must allow public and authenticated discovery implementations to change without altering MCP contracts.
- Client templates must not contain secrets or machine-specific absolute paths.
- The project is intended for personal, educational, and research use with public content. Documentation must remind users to respect platform terms and article copyright.
