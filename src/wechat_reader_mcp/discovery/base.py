"""Interfaces shared by public and authenticated discovery providers."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from wechat_reader_mcp.models import ArticleSummary


class ProviderPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    articles: list[ArticleSummary]
    next_cursor: str | None = None
    is_complete: bool
    warning: str | None = None


class DiscoveryProvider(Protocol):
    async def search(
        self, account: str, limit: int, cursor: str | None = None
    ) -> ProviderPage: ...
