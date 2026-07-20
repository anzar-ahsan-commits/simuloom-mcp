from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    """Append-only JSONL audit log protected by a cryptographic hash chain."""

    def __init__(self, path: Path, signing_key: str | None = None):
        self.path = path
        self.signing_key = signing_key.encode() if signing_key else None
        self.algorithm = "hmac-sha256" if signing_key else "sha256-chain"
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        verification = self.verify()
        if not verification["valid"]:
            raise RuntimeError(
                f"Audit log integrity check failed at line {verification['error_line']}"
            )
        self._sequence = verification["total_events"]
        self._last_hash = verification["last_hash"]

    def append(
        self,
        *,
        request_id: str,
        subject: str,
        role: str,
        key_id: str | None,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        outcome: str,
    ) -> dict[str, Any]:
        with self._lock:
            event: dict[str, Any] = {
                "sequence": self._sequence + 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "requestId": request_id,
                "subject": subject,
                "role": role,
                "keyId": key_id,
                "method": method,
                "path": path,
                "statusCode": status_code,
                "durationMs": round(duration_ms, 3),
                "outcome": outcome,
                "previousHash": self._last_hash,
                "signatureAlgorithm": self.algorithm,
            }
            event["hash"] = self._sign(event)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
            self._sequence = event["sequence"]
            self._last_hash = event["hash"]
            return event

    def read_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        with self._lock:
            if not self.path.exists():
                return []
            lines = self.path.read_text(encoding="utf-8").splitlines()
            return [json.loads(line) for line in lines[-limit:] if line.strip()]

    def verify(self) -> dict[str, Any]:
        with self._lock:
            return self._verify_unlocked()

    def _verify_unlocked(self) -> dict[str, Any]:
        previous_hash: str | None = None
        total = 0
        if not self.path.exists():
            return {
                "valid": True,
                "total_events": 0,
                "last_hash": None,
                "error_line": None,
            }
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except UnicodeError:
            return {
                "valid": False,
                "total_events": 0,
                "last_hash": None,
                "error_line": 1,
            }
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                stored_hash = event.pop("hash")
            except (json.JSONDecodeError, KeyError, TypeError):
                return {
                    "valid": False,
                    "total_events": total,
                    "last_hash": previous_hash,
                    "error_line": line_number,
                }
            if (
                event.get("previousHash") != previous_hash
                or event.get("signatureAlgorithm") != self.algorithm
                or not hmac.compare_digest(str(stored_hash), self._sign(event))
            ):
                return {
                    "valid": False,
                    "total_events": total,
                    "last_hash": previous_hash,
                    "error_line": line_number,
                }
            total += 1
            previous_hash = stored_hash
        return {
            "valid": True,
            "total_events": total,
            "last_hash": previous_hash,
            "error_line": None,
        }

    def _sign(self, event: dict[str, Any]) -> str:
        payload = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        if self.signing_key:
            return hmac.new(self.signing_key, payload, hashlib.sha256).hexdigest()
        return hashlib.sha256(payload).hexdigest()
