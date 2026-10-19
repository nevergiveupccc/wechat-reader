from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wechat_reader_mcp.errors import ReaderException
from wechat_reader_mcp.models import ArticleContent, ArticleSummary, ErrorCode


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def _summary() -> ArticleSummary:
    return ArticleSummary(
        index=1,
        title="Cached title",
        url="https://mp.weixin.qq.com/s/cached",
        account="Example Account",
    )


def _article() -> ArticleContent:
    return ArticleContent(
        title="Cached title",
        account="Example Account",
        url="https://mp.weixin.qq.com/s/cached",
        markdown="# Cached title\n\nBody",
    )


def test_platform_paths_are_derived_from_platformdirs(monkeypatch: pytest.MonkeyPatch) -> None:
    from wechat_reader_mcp import config

    calls: list[tuple[str, str]] = []

    def fake_path(kind: str):
        def resolve(app_name: str, app_author: str) -> Path:
            calls.append((kind, app_name))
            assert app_author == "wechat-reader-mcp"
            return Path("C:/portable") / kind / app_name

        return resolve

    monkeypatch.setattr(config, "user_cache_path", fake_path("cache"))
    monkeypatch.setattr(config, "user_data_path", fake_path("data"))
    monkeypatch.setattr(config, "user_log_path", fake_path("logs"))

    paths = config.AppPaths.from_platform("custom-reader")

    assert paths.cache_dir == Path("C:/portable/cache/custom-reader")
    assert paths.data_dir == Path("C:/portable/data/custom-reader")
    assert paths.log_dir == Path("C:/portable/logs/custom-reader")
    assert paths.browser_profile_dir == paths.data_dir / "browser-profile"
    assert calls == [
        ("cache", "custom-reader"),
        ("data", "custom-reader"),
        ("logs", "custom-reader"),
    ]


def test_settings_use_documented_ttl_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from wechat_reader_mcp.config import Settings

    monkeypatch.delenv("WECHAT_READER_RESULT_TTL_MINUTES", raising=False)
    monkeypatch.delenv("WECHAT_READER_ARTICLE_TTL_HOURS", raising=False)

    settings = Settings.from_env()

    assert settings.result_ttl == timedelta(minutes=30)
    assert settings.article_ttl == timedelta(hours=24)


def test_result_set_expires_at_exactly_thirty_minutes(tmp_path: Path) -> None:
    from wechat_reader_mcp.storage import SqliteStore

    clock = MutableClock(datetime(2026, 10, 19, tzinfo=UTC))
    store = SqliteStore(tmp_path / "cache.sqlite3", clock=clock)
    result_set_id = store.save_result_set([_summary()])

    clock.advance(timedelta(minutes=30))

    with pytest.raises(ReaderException) as caught:
        store.get_result_set(result_set_id)
    assert caught.value.error.code is ErrorCode.RESULT_SET_EXPIRED


def test_article_cache_expires_at_exactly_twenty_four_hours(tmp_path: Path) -> None:
    from wechat_reader_mcp.storage import SqliteStore

    clock = MutableClock(datetime(2026, 10, 19, tzinfo=UTC))
    store = SqliteStore(tmp_path / "cache.sqlite3", clock=clock)
    article = _article()
    store.put_article(article)
    assert store.get_article(article.url) == article

    clock.advance(timedelta(hours=24))

    assert store.get_article(article.url) is None


def test_purge_expired_removes_both_cache_types(tmp_path: Path) -> None:
    from wechat_reader_mcp.storage import SqliteStore

    clock = MutableClock(datetime(2026, 10, 19, tzinfo=UTC))
    store = SqliteStore(tmp_path / "nested" / "cache.sqlite3", clock=clock)
    store.save_result_set([_summary()])
    store.put_article(_article())

    clock.advance(timedelta(hours=24))

    assert store.purge_expired() == 2
    assert (tmp_path / "nested" / "cache.sqlite3").exists()
