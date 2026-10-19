"""Stable public data contracts shared by the MCP, CLI, and providers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DiscoverySource(StrEnum):
    """Where an article or account result was discovered."""

    PUBLIC_SEARCH = "public_search"
    AUTHENTICATED_SEARCH = "authenticated_search"
    OFFICIAL_AUTHORIZED = "official_authorized"
    DIRECT_URL = "direct_url"


class DiscoveryMode(StrEnum):
    """Discovery strategy requested by a caller."""

    AUTO = "auto"
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"


class ErrorCode(StrEnum):
    """Machine-readable failures exposed by the MCP boundary."""

    INVALID_URL = "invalid_url"
    UNSUPPORTED_URL = "unsupported_url"
    AMBIGUOUS_ACCOUNT = "ambiguous_account"
    NO_DISCOVERY_RESULTS = "no_discovery_results"
    LOGIN_REQUIRED = "login_required"
    LOGIN_EXPIRED = "login_expired"
    RATE_LIMITED_OR_CAPTCHA = "rate_limited_or_captcha"
    ARTICLE_UNAVAILABLE = "article_unavailable"
    UNSUPPORTED_PAGE = "unsupported_page"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    RESULT_SET_EXPIRED = "result_set_expired"
    INVALID_SELECTION = "invalid_selection"
    INTERNAL_ERROR = "internal_error"


class ReaderModel(BaseModel):
    """Base class that rejects accidental public-contract drift."""

    model_config = ConfigDict(extra="forbid")


class ReaderError(ReaderModel):
    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool = False
    details: dict[str, Any] | None = None


class AccountCandidate(ReaderModel):
    name: str = Field(min_length=1)
    account_ref: str = Field(min_length=1)
    source: DiscoverySource
    profile_url: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ArticleSummary(ReaderModel):
    index: int = Field(gt=0)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    account: str = Field(min_length=1)
    published_at: datetime | None = None
    digest: str | None = None
    source: DiscoverySource = DiscoverySource.PUBLIC_SEARCH


class ArticleContent(ReaderModel):
    title: str = Field(min_length=1)
    account: str = Field(min_length=1)
    url: str = Field(min_length=1)
    markdown: str = Field(min_length=1)
    published_at: datetime | None = None
    images: list[str] = Field(default_factory=list)
    source: DiscoverySource = DiscoverySource.DIRECT_URL


class DiscoveryPage(ReaderModel):
    result_set_id: str = Field(min_length=1)
    account: str = Field(min_length=1)
    requested: int = Field(ge=1, le=10)
    returned: int = Field(ge=0, le=10)
    discovery_source: DiscoverySource
    is_complete: bool
    articles: list[ArticleSummary]
    warning: str | None = None
    next_cursor: str | None = None

    @model_validator(mode="after")
    def returned_matches_articles(self) -> Self:
        if self.returned != len(self.articles):
            raise ValueError("returned must equal the number of articles")
        if self.returned > self.requested:
            raise ValueError("returned cannot exceed requested")
        return self


class ArticleReadResult(ReaderModel):
    index: int | None = Field(default=None, gt=0)
    url: str = Field(min_length=1)
    article: ArticleContent | None = None
    error: ReaderError | None = None

    @model_validator(mode="after")
    def has_exactly_one_outcome(self) -> Self:
        if (self.article is None) == (self.error is None):
            raise ValueError("exactly one of article or error is required")
        return self


class BatchReadResponse(ReaderModel):
    result_set_id: str | None = None
    results: list[ArticleReadResult] = Field(min_length=1, max_length=10)


class ReaderStatus(ReaderModel):
    version: str = Field(min_length=1)
    cache_available: bool
    browser_available: bool
    login_status: str = Field(min_length=1)
    providers: list[DiscoverySource]
    warnings: list[str] = Field(default_factory=list)
