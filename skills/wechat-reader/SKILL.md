---
name: wechat-reader
description: Use when a user provides a WeChat Official Account name or an mp.weixin.qq.com article URL and asks to find, list, read, or summarize public article content.
---

# WeChat Reader

Use the `wechat-reader` MCP server. Preserve the user's list-then-select workflow.

## Route the request

- For one `mp.weixin.qq.com` article URL, call `read_article_url(url)` directly. Summarize the returned article or report its typed error. Do not invent a background task or poll unless the tool actually returns one.
- For an Official Account name, call `resolve_account(query)` only when identity is ambiguous or needs confirmation. Then call `list_recent_articles(account, limit, mode="auto")`, with a maximum of 10.
- Show the numbered titles, dates when present, discovery source, and completeness warning. Describe them as “recently discovered public articles.” Results may be incomplete.
- Stop and wait for the user to choose article numbers. Never automatically read all listed articles merely because the user requested speed or a summary of the account.
- After the user chooses, call `read_selected_articles(result_set_id, selections)` with the exact result-set ID and 1–10 unique integer indices. If the conversation already contains a valid result set and explicit selections, read them without listing again.

Report each selected article's outcome; preserve partial successes when another selection fails. Do not claim results are the official latest unless the returned source is official and explicitly complete.

On `login_required`, explain that optional local WeRead login is needed and ask the user to run `wechat-reader-mcp login`. QR login and session data remain local. Never request cookies or tokens. On CAPTCHA or rate limiting, stop and request normal user interaction; do not bypass verification. Respect access permission and do not use this workflow for bulk scraping.
