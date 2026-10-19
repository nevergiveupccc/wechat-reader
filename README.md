# WeChat Reader MCP

让 Codex、Claude Code、Qoder 等支持 MCP 的 Agent 读取微信公众号公开文章。

它支持两种入口：

- 输入公众号名称：先列出最近发现的标题（maximum of 10），由用户选择后再读取 1–10 篇。
- 输入 `https://mp.weixin.qq.com/...` 文章链接：直接提取为干净的 Markdown。

名称检索不是微信官方文章目录。公开搜索和可选的微信读书增强来源都 may be incomplete；输出会携带来源和完整性警告，不会把“搜到的最近文章”冒充“官方最新文章”。

## 快速安装

需要 [Git](https://git-scm.com/) 和 [uv](https://docs.astral.sh/uv/)，Python 3.11–3.13 由 uv 管理。

```text
git clone <GIT_URL>
cd wechat-reader-mcp
```

Windows PowerShell：

```powershell
.\scripts\install.ps1
```

macOS / Linux：

```bash
./scripts/install.sh
```

安装脚本会同步依赖并运行 `wechat-reader-mcp doctor`。默认模式不需要浏览器登录。

## 接入 Agent

项目根目录的 `.mcp.json` 可直接用于支持项目级 MCP 配置的客户端。其他模板位于：

- Codex：`clients/codex/config.toml`
- Claude Code：`clients/claude/mcp.json`
- Qoder：`clients/qoder/mcp.json`

复制对应配置并把 `<REPOSITORY_PATH>` 换成克隆后的绝对路径。优先使用项目级配置；修改用户级配置前应先征得 permission。官方配置参考：[Codex MCP](https://developers.openai.com/learn/docs-mcp)、[Claude Code MCP](https://code.claude.com/docs/en/mcp)、[Qoder MCP](https://docs.qoder.com/cli/mcp-reference)。

如果客户端支持 skills，可把 `skills/wechat-reader` 安装到它的技能目录。该技能会要求 Agent 在名称检索后先展示编号标题并等待用户选择，不会自动读取全部结果。

## 可选：扫码增强模式

增强模式只覆盖用户在微信读书中已关注的公众号，使用微信读书的非公开、未文档化接口，因此仍可能变化或缺失。安装浏览器支持：

```powershell
.\scripts\install.ps1 -Browser
uv run wechat-reader-mcp login
```

```bash
./scripts/install.sh --browser
uv run wechat-reader-mcp login
```

登录时会打开本地浏览器，请用户完成 QR 扫码。会话只保存在本机应用数据目录，MCP 返回值不会包含 cookie、token 或本地路径。遇到 CAPTCHA 时工具会停止并提示用户在可见浏览器中处理，不绕过验证。退出登录：

```text
uv run wechat-reader-mcp logout
```

## Agent 中的预期流程

用户说“看看某公众号最近文章”时：

1. 必要时用 `resolve_account` 消除同名歧义。
2. 用 `list_recent_articles` 获取 1–10 条，并展示编号、标题、来源及“不完整”提示。
3. 等用户选择编号。
4. 用 `read_selected_articles` 读取所选 1–10 篇并总结；单篇失败不会吞掉其他成功结果。

用户给出文章链接时，直接调用 `read_article_url`。

## 能力边界

- 微信没有面向此用途的公开官方文章目录 API；本项目只能做公开内容的尽力发现。
- 不承诺找全公众号或历史文章，也不支持一次抓取上千篇。
- 不绕过登录、风控、付费墙、删除状态或访问控制。
- 请遵守内容版权、平台条款和合理频率；只处理你有权访问和使用的内容。

## 排查

```text
uv run wechat-reader-mcp doctor
uv run pytest -v -m "not live"
```

`doctor` 只报告 Python、包、缓存、可选浏览器和网络状态，不输出敏感信息。公开搜索失效时仍可使用直接文章链接；增强来源失败时 `auto` 模式会尝试回退公开搜索并明确标注来源。

## 开发

```text
uv sync --group dev
uv run pytest -v -m "not live"
uv build
```

### 有界在线冒烟测试

默认测试绝不访问实时公众号来源。维护者可以显式提供一个公众号名称和一条自己有权访问的公开文章链接；一次测试最多执行一次名称列表请求（`limit=1`）和一次直接读取：

```text
WECHAT_READER_RUN_LIVE=1
WECHAT_READER_LIVE_ACCOUNT=<ACCOUNT_NAME>
WECHAT_READER_LIVE_ARTICLE_URL=<PUBLIC_ARTICLE_URL>
uv run pytest tests/test_live_smoke.py -v -m live
```

### 发布检查表

- [x] Windows 安装脚本与隔离安装后的 `doctor` 已验证。
- [x] JSON/TOML 客户端模板可解析，离线测试和包构建通过。
- [ ] 使用维护者提供的公开测试输入运行有界在线测试。
- [ ] 在 Codex 中确认 `get_reader_status`、直接链接、列标题和单篇选择。
- [ ] 在 Claude Code 中完成同样的四项客户端检查。
- [ ] 在 Qoder 中完成同样的四项客户端检查。

客户端检查需要修改各客户端配置并可能发起真实网络请求，因此不由安装脚本静默执行。记录时只保存通过/失败和脱敏后的错误类别。

许可证：MIT。
