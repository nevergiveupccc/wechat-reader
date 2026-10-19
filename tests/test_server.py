from __future__ import annotations

from typing import Any

import pytest

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import (
    AccountCandidate,
    ArticleContent,
    ArticleReadResult,
    BatchReadResponse,
    DiscoveryMode,
    DiscoveryPage,
    DiscoverySource,
    ErrorCode,
    ReaderError,
    ReaderStatus,
)


def _structured(result: Any) -> dict[str, Any]:
    if isinstance(result, tuple):
        result = result[1]
    assert isinstance(result, dict)
    return result


class FakeService:
    def __init__(self) -> None:
        self.selection_calls = 0

    async def resolve_account(self, query: str) -> list[AccountCandidate]:
        return [
            AccountCandidate(
                name=query,
                account_ref=query,
                source=DiscoverySource.PUBLIC_SEARCH,
            )
        ]

    async def list_recent_articles(
        self,
        account: str,
        limit: int = 10,
        mode: DiscoveryMode = DiscoveryMode.AUTO,
        cursor: str | None = None,
    ) -> DiscoveryPage:
        return DiscoveryPage(
            result_set_id="rs_1",
            account=account,
            requested=limit,
            returned=0,
            discovery_source=DiscoverySource.PUBLIC_SEARCH,
            is_complete=False,
            articles=[],
            warning="Public search may be incomplete.",
        )

    async def read_selected_articles(
        self, result_set_id: str, selections: list[int]
    ) -> BatchReadResponse:
        self.selection_calls += 1
        if any(index > 2 for index in selections):
            raise ReaderException(
                ReaderError(
                    code=ErrorCode.INVALID_SELECTION,
                    message="A selection is outside the stored result set.",
                )
            )
        return BatchReadResponse(
            result_set_id=result_set_id,
            results=[
                ArticleReadResult(
                    index=index,
                    url=f"https://mp.weixin.qq.com/s/{index}",
                    article=ArticleContent(
                        title=f"Article {index}",
                        account="Alpha Lab",
                        url=f"https://mp.weixin.qq.com/s/{index}",
                        markdown="Body",
                    ),
                )
                for index in selections
            ],
        )

    async def read_article_url(self, url: str) -> ArticleReadResult:
        return ArticleReadResult(
            url=url,
            article=ArticleContent(
                title="Direct",
                account="Alpha Lab",
                url=url,
                markdown="Body",
            ),
        )

    def get_status(self) -> ReaderStatus:
        return ReaderStatus(
            version="0.1.0",
            cache_available=True,
            browser_available=False,
            login_status="not_configured",
            providers=[DiscoverySource.PUBLIC_SEARCH, DiscoverySource.DIRECT_URL],
        )


@pytest.mark.asyncio
async def test_server_registers_exact_five_tools_and_returns_json_data() -> None:
    from wechat_reader_mcp.server import create_mcp_server

    server = create_mcp_server(FakeService)
    tools = await server.list_tools()

    assert {tool.name for tool in tools} == {
        "resolve_account",
        "list_recent_articles",
        "read_selected_articles",
        "read_article_url",
        "get_reader_status",
    }
    result = _structured(await server.call_tool("get_reader_status", {}))
    assert result["version"] == "0.1.0"
    assert result["providers"] == ["public_search", "direct_url"]


@pytest.mark.parametrize(
    "selections",
    [
        [],
        [0],
        [-1],
        [1, 1],
        [True],
        ["1"],
        list(range(1, 12)),
    ],
)
def test_selection_validation_rejects_invalid_values(selections: list[Any]) -> None:
    from wechat_reader_mcp.server import validate_selections

    with pytest.raises(ReaderException) as caught:
        validate_selections(selections)
    assert caught.value.error.code is ErrorCode.INVALID_SELECTION


@pytest.mark.parametrize("selections", [[1], [2, 1], list(range(1, 11))])
def test_selection_validation_accepts_one_to_ten_unique_indices(
    selections: list[int],
) -> None:
    from wechat_reader_mcp.server import validate_selections

    assert validate_selections(selections) == selections


@pytest.mark.asyncio
async def test_invalid_selection_never_reaches_service() -> None:
    from wechat_reader_mcp.server import create_mcp_server

    service = FakeService()
    server = create_mcp_server(lambda: service)

    result = _structured(
        await server.call_tool(
            "read_selected_articles",
            {"result_set_id": "rs_1", "selections": [1, 1]},
        )
    )

    assert result["error"]["code"] == "invalid_selection"
    assert service.selection_calls == 0


@pytest.mark.asyncio
async def test_index_outside_result_set_is_a_stable_error_payload() -> None:
    from wechat_reader_mcp.server import create_mcp_server

    server = create_mcp_server(FakeService)
    result = _structured(
        await server.call_tool(
            "read_selected_articles",
            {"result_set_id": "rs_1", "selections": [3]},
        )
    )

    assert result["error"] == {
        "code": "invalid_selection",
        "message": "A selection is outside the stored result set.",
        "retryable": False,
        "details": None,
    }


def test_stdio_startup_setup_writes_no_stdout(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from wechat_reader_mcp import server as server_module

    calls: list[str] = []

    class DummyServer:
        def run(self, transport: str) -> None:
            calls.append(transport)

    monkeypatch.setattr(
        server_module,
        "create_mcp_server",
        lambda service_factory: DummyServer(),
    )

    server_module.run_stdio()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert calls == ["stdio"]
