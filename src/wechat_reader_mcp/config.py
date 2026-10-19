"""Cross-platform runtime paths and environment-based settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from platformdirs import user_cache_path, user_data_path, user_log_path


@dataclass(frozen=True, slots=True)
class AppPaths:
    cache_dir: Path
    data_dir: Path
    log_dir: Path
    browser_profile_dir: Path

    @classmethod
    def from_platform(cls, app_name: str = "wechat-reader-mcp") -> "AppPaths":
        author = "wechat-reader-mcp"
        cache_dir = user_cache_path(app_name, author)
        data_dir = user_data_path(app_name, author)
        return cls(
            cache_dir=cache_dir,
            data_dir=data_dir,
            log_dir=user_log_path(app_name, author),
            browser_profile_dir=data_dir / "browser-profile",
        )


def _positive_number(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    paths: AppPaths
    result_ttl: timedelta
    article_ttl: timedelta

    @property
    def database_path(self) -> Path:
        return self.paths.cache_dir / "reader-cache.sqlite3"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            paths=AppPaths.from_platform(),
            result_ttl=timedelta(
                minutes=_positive_number("WECHAT_READER_RESULT_TTL_MINUTES", "30")
            ),
            article_ttl=timedelta(
                hours=_positive_number("WECHAT_READER_ARTICLE_TTL_HOURS", "24")
            ),
        )
