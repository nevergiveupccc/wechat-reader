"""Small local SQLite store for short-lived discovery and article caches."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import (
    ArticleContent,
    ArticleSummary,
    ErrorCode,
    ReaderError,
)

_SUMMARIES = TypeAdapter(list[ArticleSummary])


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqliteStore:
    """Persist public article data with deterministic time-to-live semantics."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        result_ttl: timedelta = timedelta(minutes=30),
        article_ttl: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.database_path = Path(database_path)
        self.result_ttl = result_ttl
        self.article_ttl = article_ttl
        self._clock = clock

    def _now_timestamp(self) -> float:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("SqliteStore clock must return a timezone-aware datetime")
        return now.timestamp()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS result_sets (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                url TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        return connection

    def save_result_set(self, articles: Sequence[ArticleSummary]) -> str:
        result_set_id = f"rs_{uuid4().hex}"
        expires_at = self._now_timestamp() + self.result_ttl.total_seconds()
        payload = _SUMMARIES.dump_json(list(articles)).decode("utf-8")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO result_sets (id, payload, expires_at) VALUES (?, ?, ?)",
                (result_set_id, payload, expires_at),
            )
        return result_set_id

    def get_result_set(self, result_set_id: str) -> list[ArticleSummary]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, expires_at FROM result_sets WHERE id = ?",
                (result_set_id,),
            ).fetchone()
            if row is None or self._now_timestamp() >= row[1]:
                if row is not None:
                    connection.execute(
                        "DELETE FROM result_sets WHERE id = ?", (result_set_id,)
                    )
                raise ReaderException(
                    ReaderError(
                        code=ErrorCode.RESULT_SET_EXPIRED,
                        message="The result set is missing or has expired; search again.",
                        retryable=True,
                    )
                )
        return _SUMMARIES.validate_json(row[0])

    def put_article(self, article: ArticleContent) -> None:
        expires_at = self._now_timestamp() + self.article_ttl.total_seconds()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO articles (url, payload, expires_at) VALUES (?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    payload = excluded.payload,
                    expires_at = excluded.expires_at
                """,
                (article.url, article.model_dump_json(), expires_at),
            )

    def get_article(self, url: str) -> ArticleContent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, expires_at FROM articles WHERE url = ?", (url,)
            ).fetchone()
            if row is None:
                return None
            if self._now_timestamp() >= row[1]:
                connection.execute("DELETE FROM articles WHERE url = ?", (url,))
                return None
        return ArticleContent.model_validate_json(row[0])

    def purge_expired(self) -> int:
        now = self._now_timestamp()
        with self._connect() as connection:
            result_cursor = connection.execute(
                "DELETE FROM result_sets WHERE expires_at <= ?", (now,)
            )
            article_cursor = connection.execute(
                "DELETE FROM articles WHERE expires_at <= ?", (now,)
            )
            return result_cursor.rowcount + article_cursor.rowcount
