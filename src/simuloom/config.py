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
    wiremock_url: str
    auth_enabled: bool
    api_keys_json: str = field(repr=False)
    audit_signing_key: str | None = field(repr=False)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            workspace=Path(os.getenv("SIMULOOM_WORKSPACE", "workspace")).resolve(),
            wiremock_url=os.getenv("WIREMOCK_URL", "http://localhost:8080").rstrip("/"),
            auth_enabled=_boolean_env("SIMULOOM_AUTH_ENABLED"),
            api_keys_json=os.getenv("SIMULOOM_API_KEYS", "{}"),
            audit_signing_key=os.getenv("SIMULOOM_AUDIT_SIGNING_KEY") or None,
        )
