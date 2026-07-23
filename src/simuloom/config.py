from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _boolean_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True, slots=True)
class Settings:
    workspace: Path
    runtime: str
    wiremock_url: str
    native_runtime_url: str
    native_runtime_store: str
    native_runtime_db: Path
    native_journal_limit: int
    auth_enabled: bool
    api_keys_json: str = field(repr=False)
    audit_signing_key: str | None = field(repr=False)
    platform_db: Path
    integration_allowed_hosts: frozenset[str]
    integration_signing_key: str | None = field(repr=False)
    integration_allow_http: bool
    secrets_master_key: str | None = field(repr=False)
    ai_enabled: bool
    ai_base_url: str
    ai_model: str

    @classmethod
    def from_env(cls) -> Settings:
        runtime = os.getenv("SIMULOOM_RUNTIME", "wiremock").strip().lower()
        if runtime not in {"wiremock", "native"}:
            raise ValueError("SIMULOOM_RUNTIME must be wiremock or native")
        native_store = os.getenv("SIMULOOM_NATIVE_RUNTIME_STORE", "sqlite").strip().lower()
        if native_store not in {"sqlite", "memory"}:
            raise ValueError("SIMULOOM_NATIVE_RUNTIME_STORE must be sqlite or memory")
        try:
            journal_limit = int(os.getenv("SIMULOOM_NATIVE_JOURNAL_LIMIT", "1000"))
        except ValueError as exc:
            raise ValueError("SIMULOOM_NATIVE_JOURNAL_LIMIT must be an integer") from exc
        if not 1 <= journal_limit <= 100_000:
            raise ValueError("SIMULOOM_NATIVE_JOURNAL_LIMIT must be between 1 and 100000")
        workspace = Path(os.getenv("SIMULOOM_WORKSPACE", "workspace")).resolve()
        return cls(
            workspace=workspace,
            runtime=runtime,
            wiremock_url=os.getenv("WIREMOCK_URL", "http://localhost:8080").rstrip("/"),
            native_runtime_url=os.getenv(
                "SIMULOOM_NATIVE_RUNTIME_URL", "http://localhost:8000/runtime"
            ).rstrip("/"),
            native_runtime_store=native_store,
            native_runtime_db=Path(
                os.getenv(
                    "SIMULOOM_NATIVE_RUNTIME_DB",
                    str(workspace / "runtime" / "native.db"),
                )
            ).resolve(),
            native_journal_limit=journal_limit,
            auth_enabled=_boolean_env("SIMULOOM_AUTH_ENABLED"),
            api_keys_json=os.getenv("SIMULOOM_API_KEYS", "{}"),
            audit_signing_key=os.getenv("SIMULOOM_AUDIT_SIGNING_KEY") or None,
            platform_db=Path(
                os.getenv("SIMULOOM_PLATFORM_DB", str(workspace / "runtime" / "platform.db"))
            ).resolve(),
            integration_allowed_hosts=frozenset(
                host.strip().lower().rstrip(".")
                for host in os.getenv("SIMULOOM_INTEGRATION_ALLOWED_HOSTS", "").split(",")
                if host.strip()
            ),
            integration_signing_key=os.getenv("SIMULOOM_INTEGRATION_SIGNING_KEY") or None,
            integration_allow_http=_boolean_env("SIMULOOM_INTEGRATION_ALLOW_HTTP"),
            secrets_master_key=os.getenv("SIMULOOM_SECRETS_MASTER_KEY") or None,
            ai_enabled=_boolean_env("SIMULOOM_AI_ENABLED"),
            ai_base_url=os.getenv("SIMULOOM_AI_BASE_URL", "http://localhost:11434"),
            ai_model=os.getenv("SIMULOOM_AI_MODEL", "qwen3:8b"),
        )
