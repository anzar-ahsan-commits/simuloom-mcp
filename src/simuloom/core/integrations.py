from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx


class CircuitStateStore(Protocol):
    def integration_circuit(self, endpoint: str) -> dict[str, int | float]: ...

    def record_integration_failure(
        self, endpoint: str, threshold: int, cooldown_seconds: float, now: float
    ) -> dict[str, int | float]: ...

    def clear_integration_circuit(self, endpoint: str) -> None: ...


class IntegrationDispatcher:
    def __init__(
        self,
        allowed_hosts: frozenset[str],
        signing_key: str | None,
        allow_http: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 3,
        circuit_threshold: int = 3,
        circuit_cooldown_seconds: float = 30,
        circuit_store: CircuitStateStore | None = None,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.signing_key = signing_key.encode() if signing_key else None
        self.allow_http = allow_http
        self.transport = transport
        self.max_attempts = max_attempts
        self.circuit_threshold = circuit_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self.circuit_store = circuit_store
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def validate_endpoint(self, endpoint: str) -> str:
        parsed = urlsplit(endpoint)
        schemes = {"https", "http"} if self.allow_http else {"https"}
        if parsed.scheme not in schemes:
            raise ValueError("Integration endpoints must use HTTPS")
        if parsed.username or parsed.password or not parsed.hostname:
            raise ValueError("Integration endpoint credentials are not allowed")
        host = parsed.hostname.lower().rstrip(".")
        if host not in self.allowed_hosts:
            raise ValueError("Integration endpoint host is not explicitly allowlisted")
        return endpoint

    async def dispatch(
        self,
        integration: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
        signing_key: str | None = None,
    ) -> dict[str, Any]:
        selected_key = signing_key.encode() if signing_key else self.signing_key
        if not selected_key:
            raise RuntimeError("SIMULOOM_INTEGRATION_SIGNING_KEY is required for delivery")
        self.validate_endpoint(integration["endpoint"])
        endpoint = integration["endpoint"]
        circuit = (
            self.circuit_store.integration_circuit(endpoint)
            if self.circuit_store
            else {"open_until": self._open_until.get(endpoint, 0)}
        )
        if float(circuit["open_until"]) > time.time():
            raise RuntimeError("Integration circuit is open; delivery is temporarily paused")
        if event_type not in integration["event_types"]:
            raise ValueError(f"Integration does not subscribe to event type: {event_type}")
        delivery_id = uuid.uuid4().hex
        body = json.dumps(
            {"id": delivery_id, "type": event_type, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(selected_key, body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-SimuLoom-Delivery": delivery_id,
            "X-SimuLoom-Event": event_type,
            "X-SimuLoom-Signature": f"sha256={signature}",
            "Idempotency-Key": delivery_id,
        }
        response: httpx.Response | None = None
        request_error: httpx.RequestError | None = None
        attempts = 0
        async with httpx.AsyncClient(
            timeout=5,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            for attempts in range(1, self.max_attempts + 1):
                try:
                    response = await client.post(endpoint, content=body, headers=headers)
                    request_error = None
                    if response.status_code not in {429} and response.status_code < 500:
                        break
                except httpx.RequestError as exc:
                    request_error = exc
                if attempts < self.max_attempts:
                    await asyncio.sleep(0.1 * (2 ** (attempts - 1)))
        transient_failure = request_error is not None or (
            response is not None and (response.status_code == 429 or response.status_code >= 500)
        )
        if transient_failure:
            if self.circuit_store:
                self.circuit_store.record_integration_failure(
                    endpoint,
                    self.circuit_threshold,
                    self.circuit_cooldown_seconds,
                    time.time(),
                )
            else:
                failures = self._failures.get(endpoint, 0) + 1
                self._failures[endpoint] = failures
                if failures >= self.circuit_threshold:
                    self._open_until[endpoint] = time.time() + self.circuit_cooldown_seconds
            if request_error is not None:
                raise request_error
        else:
            if self.circuit_store:
                self.circuit_store.clear_integration_circuit(endpoint)
            self._failures.pop(endpoint, None)
            self._open_until.pop(endpoint, None)
        if response is None:
            raise RuntimeError("Integration delivery produced no response")
        return {
            "delivery_id": delivery_id,
            "event_type": event_type,
            "status_code": response.status_code,
            "accepted": 200 <= response.status_code < 300,
            "attempts": attempts,
        }
