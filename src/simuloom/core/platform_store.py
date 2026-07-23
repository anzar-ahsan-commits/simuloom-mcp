from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PLATFORM_SCHEMA_VERSION = 5


class PlatformStore:
    """Durable metadata store shared by modern control-plane capabilities."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._migrate()
        self._recover_interrupted_jobs()

    def _migrate(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            current = self.schema_version()
            if current > PLATFORM_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Platform schema version {current} is newer than supported version "
                    f"{PLATFORM_SCHEMA_VERSION}"
                )
            if current < 1:
                self._connection.executescript(
                    """
                    CREATE TABLE platform_workspaces (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL,
                        created_at TEXT NOT NULL, created_by TEXT NOT NULL
                    );
                    CREATE TABLE platform_memberships (
                        workspace_id TEXT NOT NULL REFERENCES platform_workspaces(id)
                            ON DELETE CASCADE,
                        subject TEXT NOT NULL,
                        role TEXT NOT NULL CHECK (role IN ('viewer', 'operator', 'admin')),
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (workspace_id, subject)
                    );
                    CREATE TABLE platform_jobs (
                        id TEXT PRIMARY KEY, workspace_id TEXT, kind TEXT NOT NULL,
                        status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                        payload TEXT NOT NULL, result TEXT, error TEXT,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE platform_integrations (
                        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
                        endpoint TEXT NOT NULL, event_types TEXT NOT NULL, secret_ref TEXT,
                        enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
                    );
                    CREATE TABLE platform_secrets (
                        workspace_id TEXT NOT NULL, name TEXT NOT NULL, ciphertext BLOB NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        PRIMARY KEY (workspace_id, name)
                    );
                    CREATE TABLE platform_metrics (
                        name TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0
                    );
                    INSERT INTO schema_migrations (version) VALUES (1);
                    """
                )
            if current < 2:
                self._connection.executescript(
                    """
                    CREATE TABLE platform_integration_circuits (
                        endpoint TEXT PRIMARY KEY,
                        failures INTEGER NOT NULL DEFAULT 0,
                        open_until REAL NOT NULL DEFAULT 0
                    );
                    INSERT INTO schema_migrations (version) VALUES (2);
                    """
                )
            if current < 3:
                self._connection.executescript(
                    """
                    CREATE TABLE platform_ai_threads (
                        id TEXT PRIMARY KEY, simulation_id TEXT NOT NULL,
                        title TEXT NOT NULL, owner TEXT NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE platform_ai_messages (
                        id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL REFERENCES platform_ai_threads(id)
                            ON DELETE CASCADE,
                        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                        content TEXT NOT NULL, actions TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE platform_ai_actions (
                        id TEXT PRIMARY KEY,
                        message_id TEXT NOT NULL REFERENCES platform_ai_messages(id)
                            ON DELETE CASCADE,
                        thread_id TEXT NOT NULL REFERENCES platform_ai_threads(id)
                            ON DELETE CASCADE,
                        kind TEXT NOT NULL, arguments TEXT NOT NULL, summary TEXT NOT NULL,
                        risk TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'proposed',
                        result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE INDEX platform_ai_messages_thread_idx
                        ON platform_ai_messages(thread_id, created_at);
                    CREATE INDEX platform_ai_actions_thread_idx
                        ON platform_ai_actions(thread_id, created_at);
                    INSERT INTO schema_migrations (version) VALUES (3);
                    """
                )
            if current < 4:
                self._connection.executescript(
                    """
                    CREATE TABLE platform_settings (
                        name TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    INSERT INTO schema_migrations (version) VALUES (4);
                    """
                )
            if current < 5:
                self._connection.executescript(
                    """
                    ALTER TABLE platform_ai_threads
                        ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
                    INSERT INTO schema_migrations (version) VALUES (5);
                    """
                )

    def _recover_interrupted_jobs(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE platform_jobs SET status = 'queued', progress = 0, "
                "error = 'Job was requeued after a process restart', "
                "updated_at = CURRENT_TIMESTAMP WHERE status = 'running'"
            )

    def schema_version(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
        return int(row[0])

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            self._connection.execute("SELECT 1").fetchone()
            mode = self._connection.execute("PRAGMA journal_mode").fetchone()[0]
            return {
                "ready": True,
                "schema_version": self.schema_version(),
                "supported_schema_version": PLATFORM_SCHEMA_VERSION,
                "journal_mode": str(mode).lower(),
            }

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def increment_metric(self, name: str, amount: int = 1) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO platform_metrics (name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = value + excluded.value",
                (name, amount),
            )

    def metrics_snapshot(self) -> dict[str, int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT name, value FROM platform_metrics ORDER BY name"
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def get_setting(self, name: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM platform_settings WHERE name = ?", (name,)
            ).fetchone()
        return str(row[0]) if row else None

    def set_setting(self, name: str, value: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO platform_settings (name, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (name, value, now),
            )

    def create_workspace(self, name: str, creator: str) -> dict[str, Any]:
        workspace_id = f"ws-{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO platform_workspaces (id, name, created_at, created_by) "
                "VALUES (?, ?, ?, ?)",
                (workspace_id, name, now, creator),
            )
            self._connection.execute(
                "INSERT INTO platform_memberships "
                "(workspace_id, subject, role, created_at) VALUES (?, ?, 'admin', ?)",
                (workspace_id, creator, now),
            )
        return self.get_workspace(workspace_id)

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, name, created_at, created_by FROM platform_workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Workspace not found: {workspace_id}")
        return dict(row)

    def list_workspaces(self, subject: str, include_all: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            if include_all:
                rows = self._connection.execute(
                    "SELECT id, name, created_at, created_by FROM platform_workspaces "
                    "ORDER BY name, id"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT w.id, w.name, w.created_at, w.created_by "
                    "FROM platform_workspaces w JOIN platform_memberships m "
                    "ON m.workspace_id = w.id "
                    "WHERE m.subject = ? ORDER BY w.name, w.id",
                    (subject,),
                ).fetchall()
        return [dict(row) for row in rows]

    def membership_role(self, workspace_id: str, subject: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT role FROM platform_memberships WHERE workspace_id = ? AND subject = ?",
                (workspace_id, subject),
            ).fetchone()
        return str(row[0]) if row else None

    def list_members(self, workspace_id: str) -> list[dict[str, Any]]:
        self.get_workspace(workspace_id)
        with self._lock:
            rows = self._connection.execute(
                "SELECT subject, role, created_at FROM platform_memberships "
                "WHERE workspace_id = ? ORDER BY subject",
                (workspace_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_member(self, workspace_id: str, subject: str, role: str) -> dict[str, Any]:
        self.get_workspace(workspace_id)
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO platform_memberships (workspace_id, subject, role, created_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(workspace_id, subject) "
                "DO UPDATE SET role = excluded.role",
                (workspace_id, subject, role, now),
            )
        return next(item for item in self.list_members(workspace_id) if item["subject"] == subject)

    def remove_member(self, workspace_id: str, subject: str) -> None:
        with self._lock, self._connection:
            current = self._connection.execute(
                "SELECT role FROM platform_memberships WHERE workspace_id = ? AND subject = ?",
                (workspace_id, subject),
            ).fetchone()
            if current is None:
                raise KeyError(f"Workspace member not found: {subject}")
            if current[0] == "admin":
                admins = self._connection.execute(
                    "SELECT COUNT(*) FROM platform_memberships "
                    "WHERE workspace_id = ? AND role = 'admin'",
                    (workspace_id,),
                ).fetchone()[0]
                if admins == 1:
                    raise ValueError("A workspace must retain at least one admin")
            self._connection.execute(
                "DELETE FROM platform_memberships WHERE workspace_id = ? AND subject = ?",
                (workspace_id, subject),
            )

    def create_integration(
        self,
        workspace_id: str,
        name: str,
        endpoint: str,
        event_types: list[str],
        secret_ref: str | None = None,
    ) -> dict[str, Any]:
        integration_id = f"int-{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO platform_integrations "
                "(id, workspace_id, name, endpoint, event_types, secret_ref, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    integration_id,
                    workspace_id,
                    name,
                    endpoint,
                    json.dumps(event_types),
                    secret_ref,
                    now,
                ),
            )
        return self.get_integration(integration_id)

    def get_integration(self, integration_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, workspace_id, name, endpoint, event_types, secret_ref, enabled, "
                "created_at "
                "FROM platform_integrations WHERE id = ?",
                (integration_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Integration not found: {integration_id}")
        item = dict(row)
        item["event_types"] = json.loads(item["event_types"])
        item["enabled"] = bool(item["enabled"])
        return item

    def list_integrations(self, workspace_id: str) -> list[dict[str, Any]]:
        self.get_workspace(workspace_id)
        with self._lock:
            rows = self._connection.execute(
                "SELECT id FROM platform_integrations WHERE workspace_id = ? ORDER BY name, id",
                (workspace_id,),
            ).fetchall()
        return [self.get_integration(str(row[0])) for row in rows]

    def delete_integration(self, integration_id: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM platform_integrations WHERE id = ?", (integration_id,)
            )
        if cursor.rowcount != 1:
            raise KeyError(f"Integration not found: {integration_id}")

    def integration_circuit(self, endpoint: str) -> dict[str, int | float]:
        with self._lock:
            row = self._connection.execute(
                "SELECT failures, open_until FROM platform_integration_circuits WHERE endpoint = ?",
                (endpoint,),
            ).fetchone()
        return {
            "failures": int(row[0]) if row else 0,
            "open_until": float(row[1]) if row else 0,
        }

    def record_integration_failure(
        self, endpoint: str, threshold: int, cooldown_seconds: float, now: float
    ) -> dict[str, int | float]:
        with self._lock, self._connection:
            current = self.integration_circuit(endpoint)
            failures = int(current["failures"]) + 1
            open_until = now + cooldown_seconds if failures >= threshold else 0
            self._connection.execute(
                "INSERT INTO platform_integration_circuits (endpoint, failures, open_until) "
                "VALUES (?, ?, ?) ON CONFLICT(endpoint) DO UPDATE SET "
                "failures = excluded.failures, open_until = excluded.open_until",
                (endpoint, failures, open_until),
            )
        return {"failures": failures, "open_until": open_until}

    def clear_integration_circuit(self, endpoint: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM platform_integration_circuits WHERE endpoint = ?", (endpoint,)
            )

    def put_secret(self, workspace_id: str, name: str, ciphertext: bytes) -> dict[str, Any]:
        self.get_workspace(workspace_id)
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO platform_secrets "
                "(workspace_id, name, ciphertext, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(workspace_id, name) DO UPDATE SET "
                "ciphertext = excluded.ciphertext, updated_at = excluded.updated_at",
                (workspace_id, name, ciphertext, now, now),
            )
        return next(item for item in self.list_secrets(workspace_id) if item["name"] == name)

    def list_secrets(self, workspace_id: str) -> list[dict[str, Any]]:
        self.get_workspace(workspace_id)
        with self._lock:
            rows = self._connection.execute(
                "SELECT name, created_at, updated_at FROM platform_secrets "
                "WHERE workspace_id = ? ORDER BY name",
                (workspace_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def secret_ciphertext(self, workspace_id: str, name: str) -> bytes:
        with self._lock:
            row = self._connection.execute(
                "SELECT ciphertext FROM platform_secrets WHERE workspace_id = ? AND name = ?",
                (workspace_id, name),
            ).fetchone()
        if row is None:
            raise KeyError(f"Secret not found: {name}")
        return bytes(row[0])

    def delete_secret(self, workspace_id: str, name: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM platform_secrets WHERE workspace_id = ? AND name = ?",
                (workspace_id, name),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"Secret not found: {name}")

    def create_job(self, workspace_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_workspace(workspace_id)
        job_id = f"job-{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO platform_jobs "
                "(id, workspace_id, kind, status, progress, payload, created_at, updated_at) "
                "VALUES (?, ?, ?, 'queued', 0, ?, ?, ?)",
                (job_id, workspace_id, kind, json.dumps(payload), now, now),
            )
        return self.get_job(job_id)

    def claim_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE platform_jobs SET status = 'running', progress = 10, error = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'queued'",
                (job_id,),
            )
        return self.get_job(job_id) if cursor.rowcount == 1 else None

    def claim_next_job(self) -> dict[str, Any] | None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT id FROM platform_jobs WHERE status = 'queued' "
                "ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            cursor = self._connection.execute(
                "UPDATE platform_jobs SET status = 'running', progress = 10, error = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'queued'",
                (row[0],),
            )
        return self.get_job(str(row[0])) if cursor.rowcount == 1 else None

    def update_job(
        self,
        job_id: str,
        status: str,
        progress: int,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE platform_jobs SET status = ?, progress = ?, result = ?, error = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    status,
                    progress,
                    json.dumps(result) if result is not None else None,
                    error,
                    now,
                    job_id,
                ),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"Job not found: {job_id}")
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, workspace_id, kind, status, progress, payload, result, error, "
                "created_at, updated_at FROM platform_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        item["result"] = json.loads(item["result"]) if item["result"] else None
        return item

    def list_jobs(self, workspace_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self.get_workspace(workspace_id)
        with self._lock:
            rows = self._connection.execute(
                "SELECT id FROM platform_jobs WHERE workspace_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            ).fetchall()
        return [self.get_job(str(row[0])) for row in rows]

    def create_ai_thread(self, simulation_id: str, title: str, owner: str) -> dict[str, Any]:
        thread_id = f"chat-{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO platform_ai_threads "
                "(id, simulation_id, title, owner, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (thread_id, simulation_id, title, owner, now, now),
            )
        return self.get_ai_thread(thread_id)

    def get_ai_thread(self, thread_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, simulation_id, title, owner, archived, created_at, updated_at "
                "FROM platform_ai_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"AI conversation not found: {thread_id}")
        item = dict(row)
        item["archived"] = bool(item["archived"])
        item["messages"] = self.list_ai_messages(thread_id)
        return item

    def list_ai_threads(
        self, owner: str, include_all: bool = False, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        with self._lock:
            archived_filter = "" if include_archived else " WHERE archived = 0"
            if include_all:
                rows = self._connection.execute(
                    "SELECT id FROM platform_ai_threads"
                    + archived_filter
                    + " ORDER BY updated_at DESC LIMIT 100"
                ).fetchall()
            else:
                archived_clause = "" if include_archived else " AND archived = 0"
                rows = self._connection.execute(
                    "SELECT id FROM platform_ai_threads WHERE owner = ? "
                    + archived_clause
                    + " ORDER BY updated_at DESC LIMIT 100",
                    (owner,),
                ).fetchall()
        return [self.get_ai_thread(str(row[0])) for row in rows]

    def update_ai_thread(
        self, thread_id: str, title: str | None = None, archived: bool | None = None
    ) -> dict[str, Any]:
        self.get_ai_thread(thread_id)
        updates: list[str] = []
        values: list[Any] = []
        if title is not None:
            updates.append("title = ?")
            values.append(title)
        if archived is not None:
            updates.append("archived = ?")
            values.append(int(archived))
        if not updates:
            return self.get_ai_thread(thread_id)
        updates.append("updated_at = ?")
        values.append(datetime.now(UTC).isoformat())
        values.append(thread_id)
        with self._lock, self._connection:
            self._connection.execute(
                f"UPDATE platform_ai_threads SET {', '.join(updates)} WHERE id = ?", values
            )
        return self.get_ai_thread(thread_id)

    def delete_ai_thread(self, thread_id: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM platform_ai_threads WHERE id = ?", (thread_id,)
            )
        if cursor.rowcount != 1:
            raise KeyError(f"AI conversation not found: {thread_id}")

    def add_ai_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.get_ai_thread(thread_id)
        message_id = f"msg-{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC).isoformat()
        stored_actions: list[dict[str, Any]] = []
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO platform_ai_messages "
                "(id, thread_id, role, content, actions, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, thread_id, role, content, "[]", now),
            )
            for action in actions or []:
                action_id = f"act-{uuid.uuid4().hex[:16]}"
                stored = {**action, "id": action_id, "status": "proposed", "result": None}
                stored_actions.append(stored)
                self._connection.execute(
                    "INSERT INTO platform_ai_actions "
                    "(id, message_id, thread_id, kind, arguments, summary, risk, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?)",
                    (
                        action_id,
                        message_id,
                        thread_id,
                        action["kind"],
                        json.dumps(action.get("arguments", {})),
                        action["summary"],
                        action["risk"],
                        now,
                        now,
                    ),
                )
            self._connection.execute(
                "UPDATE platform_ai_messages SET actions = ? WHERE id = ?",
                (json.dumps(stored_actions), message_id),
            )
            self._connection.execute(
                "UPDATE platform_ai_threads SET updated_at = ? WHERE id = ?", (now, thread_id)
            )
        return next(item for item in self.list_ai_messages(thread_id) if item["id"] == message_id)

    def list_ai_messages(self, thread_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, thread_id, role, content, actions, created_at "
                "FROM platform_ai_messages WHERE thread_id = ? ORDER BY created_at, id",
                (thread_id,),
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["actions"] = json.loads(item["actions"])
        return items

    def get_ai_action(self, action_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, message_id, thread_id, kind, arguments, summary, risk, status, "
                "result, created_at, updated_at FROM platform_ai_actions WHERE id = ?",
                (action_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"AI action not found: {action_id}")
        item = dict(row)
        item["arguments"] = json.loads(item["arguments"])
        item["result"] = json.loads(item["result"]) if item["result"] else None
        return item

    def update_ai_action(
        self, action_id: str, status: str, result: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE platform_ai_actions SET status = ?, result = ?, updated_at = ? "
                "WHERE id = ?",
                (status, json.dumps(result) if result is not None else None, now, action_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"AI action not found: {action_id}")
            action = self.get_ai_action(action_id)
            message_actions = self._connection.execute(
                "SELECT id FROM platform_ai_actions WHERE message_id = ? ORDER BY created_at, id",
                (action["message_id"],),
            ).fetchall()
            rendered = [self.get_ai_action(str(row[0])) for row in message_actions]
            self._connection.execute(
                "UPDATE platform_ai_messages SET actions = ? WHERE id = ?",
                (json.dumps(rendered), action["message_id"]),
            )
        return self.get_ai_action(action_id)

    def claim_ai_action(self, action_id: str) -> dict[str, Any] | None:
        """Atomically claim a proposed action so it can execute at most once."""
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE platform_ai_actions SET status = 'approved', updated_at = ? "
                "WHERE id = ? AND status = 'proposed'",
                (now, action_id),
            )
        return self.get_ai_action(action_id) if cursor.rowcount == 1 else None
