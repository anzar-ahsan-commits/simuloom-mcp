import sqlite3
from pathlib import Path

import pytest

from simuloom.core.platform_store import PLATFORM_SCHEMA_VERSION, PlatformStore


def test_platform_store_initializes_migration_managed_schema(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path / "runtime" / "platform.db")

    assert store.diagnostics() == {
        "ready": True,
        "schema_version": PLATFORM_SCHEMA_VERSION,
        "supported_schema_version": PLATFORM_SCHEMA_VERSION,
        "journal_mode": "wal",
    }
    with sqlite3.connect(store.path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "schema_migrations",
        "platform_workspaces",
        "platform_memberships",
        "platform_jobs",
        "platform_integrations",
        "platform_secrets",
        "platform_metrics",
        "platform_integration_circuits",
    } <= tables


def test_platform_store_reopens_without_reapplying_migrations(tmp_path: Path) -> None:
    path = tmp_path / "platform.db"
    first = PlatformStore(path)
    first.close()

    second = PlatformStore(path)

    assert second.schema_version() == PLATFORM_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2


def test_platform_store_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "platform.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.execute("INSERT INTO schema_migrations (version) VALUES (999)")

    with pytest.raises(RuntimeError, match="newer than supported"):
        PlatformStore(path)
