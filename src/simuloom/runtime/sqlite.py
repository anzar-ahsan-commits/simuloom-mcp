from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from simuloom.runtime.models import RuntimeMapping


class SQLiteRuntimeStore:
    persistent = True
    storage = "sqlite"

    def __init__(self, path: Path, journal_limit: int = 1_000) -> None:
        if journal_limit < 1:
            raise ValueError("journal_limit must be positive")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.journal_limit = journal_limit
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def _initialize(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_mappings (
                    simulation_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (simulation_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS runtime_scenarios (
                    scenario_name TEXT PRIMARY KEY,
                    simulation_id TEXT NOT NULL,
                    state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    simulation_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runtime_events_simulation
                    ON runtime_events (simulation_id, id);
                """
            )
            row = self._connection.execute(
                "SELECT value FROM runtime_metadata WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO runtime_metadata (key, value) VALUES ('schema_version', '1')"
                )
            elif row[0] != "1":
                raise RuntimeError(f"Unsupported native runtime schema version: {row[0]}")

    def close(self) -> None:
        self._connection.close()

    def clear(self) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM runtime_mappings")
            self._connection.execute("DELETE FROM runtime_scenarios")
            self._connection.execute("DELETE FROM runtime_events")

    def mappings(self, simulation_id: str) -> list[RuntimeMapping]:
        rows = self._connection.execute(
            "SELECT payload FROM runtime_mappings WHERE simulation_id = ? ORDER BY ordinal",
            (simulation_id,),
        ).fetchall()
        return [RuntimeMapping.model_validate_json(row[0]) for row in rows]

    def replace_mappings(self, simulation_id: str, mappings: list[RuntimeMapping]) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM runtime_mappings WHERE simulation_id = ?", (simulation_id,)
            )
            self._connection.executemany(
                "INSERT INTO runtime_mappings (simulation_id, ordinal, payload) VALUES (?, ?, ?)",
                [
                    (simulation_id, index, mapping.model_dump_json())
                    for index, mapping in enumerate(mappings)
                ],
            )

    def scenario_names(self, simulation_id: str | None = None) -> list[str]:
        if simulation_id is None:
            rows = self._connection.execute(
                "SELECT scenario_name FROM runtime_scenarios ORDER BY scenario_name"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT scenario_name FROM runtime_scenarios "
                "WHERE simulation_id = ? ORDER BY scenario_name",
                (simulation_id,),
            ).fetchall()
        return [row[0] for row in rows]

    def scenario_state(self, scenario_name: str) -> str | None:
        row = self._connection.execute(
            "SELECT state FROM runtime_scenarios WHERE scenario_name = ?", (scenario_name,)
        ).fetchone()
        return row[0] if row is not None else None

    def ensure_scenario_state(self, simulation_id: str, scenario_name: str, state: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO runtime_scenarios "
                "(scenario_name, simulation_id, state) VALUES (?, ?, ?)",
                (scenario_name, simulation_id, state),
            )

    def set_scenario_state(self, scenario_name: str, state: str) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE runtime_scenarios SET state = ? WHERE scenario_name = ?",
                (state, scenario_name),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Scenario is not deployed: {scenario_name}")

    def append_event(self, simulation_id: str, event: dict[str, Any]) -> None:
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
        with self._connection:
            self._connection.execute(
                "INSERT INTO runtime_events (simulation_id, payload) VALUES (?, ?)",
                (simulation_id, payload),
            )
            self._connection.execute(
                "DELETE FROM runtime_events WHERE simulation_id = ? AND id NOT IN "
                "(SELECT id FROM runtime_events WHERE simulation_id = ? "
                "ORDER BY id DESC LIMIT ?)",
                (simulation_id, simulation_id, self.journal_limit),
            )

    def events(self, simulation_id: str | None = None) -> list[dict[str, Any]]:
        if simulation_id is None:
            rows = self._connection.execute(
                "SELECT payload FROM runtime_events ORDER BY id"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT payload FROM runtime_events WHERE simulation_id = ? ORDER BY id",
                (simulation_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def clear_events(self, simulation_id: str | None = None) -> None:
        with self._connection:
            if simulation_id is None:
                self._connection.execute("DELETE FROM runtime_events")
            else:
                self._connection.execute(
                    "DELETE FROM runtime_events WHERE simulation_id = ?", (simulation_id,)
                )
