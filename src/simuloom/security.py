from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from simuloom.core.audit import AuditLog


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


ROLE_LEVEL = {Role.VIEWER: 10, Role.OPERATOR: 20, Role.ADMIN: 30}
_bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth")
_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="ApiKeyAuth")
BearerCredential = Security(_bearer_scheme)
ApiKeyCredential = Security(_api_key_scheme)


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    role: Role
    key_id: str | None


_current_principal: ContextVar[Principal | None] = ContextVar("simuloom_principal", default=None)


class AccessController:
    def __init__(self, enabled: bool, api_keys_json: str):
        self.enabled = enabled
        self._keys = self._parse_keys(api_keys_json)
        if enabled and not self._keys:
            raise ValueError("SIMULOOM_AUTH_ENABLED requires at least one configured API key")
        if enabled and any(len(secret) < 16 for secret, _ in self._keys):
            raise ValueError("Every enabled API key must contain at least 16 characters")

    def authenticate(self, headers: dict[str, str]) -> Principal | None:
        if not self.enabled:
            return Principal("local-development", Role.ADMIN, None)
        supplied = self._extract_key(headers)
        if supplied is None:
            return None
        for secret, principal in self._keys:
            if hmac.compare_digest(supplied, secret):
                return principal
        return None

    @staticmethod
    def _extract_key(headers: dict[str, str]) -> str | None:
        authorization = headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            value = authorization[7:].strip()
            return value or None
        value = headers.get("x-api-key", "").strip()
        return value or None

    @staticmethod
    def _parse_keys(api_keys_json: str) -> list[tuple[str, Principal]]:
        try:
            payload = json.loads(api_keys_json)
        except json.JSONDecodeError as exc:
            raise ValueError("SIMULOOM_API_KEYS must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("SIMULOOM_API_KEYS must be a JSON object")
        parsed: list[tuple[str, Principal]] = []
        for secret, identity in payload.items():
            if not isinstance(secret, str) or not secret:
                raise ValueError("Every configured API key must be a non-empty string")
            if not isinstance(identity, dict):
                raise ValueError("Every API key identity must be an object")
            subject = identity.get("subject")
            if not isinstance(subject, str) or not subject.strip():
                raise ValueError("Every API key identity requires a subject")
            try:
                role = Role(identity.get("role"))
            except ValueError as exc:
                raise ValueError(f"Invalid role configured for subject {subject}") from exc
            key_id = hashlib.sha256(secret.encode()).hexdigest()[:12]
            parsed.append((secret, Principal(subject.strip(), role, key_id)))
        return parsed


def role_allows(actual: Role, required: Role) -> bool:
    return ROLE_LEVEL[actual] >= ROLE_LEVEL[required]


def require_role(required: Role):
    def dependency(
        request: Request,
        _bearer: HTTPAuthorizationCredentials | None = BearerCredential,
        _api_key: str | None = ApiKeyCredential,
    ) -> Principal:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not role_allows(principal.role, required):
            raise HTTPException(
                status_code=403,
                detail=f"The {required.value} role is required for this operation",
            )
        return principal

    return dependency


def require_current_role(required: Role) -> Principal:
    principal = _current_principal.get()
    if principal is None:
        raise PermissionError("No authenticated MCP principal is available")
    if not role_allows(principal.role, required):
        raise PermissionError(f"The {required.value} role is required for this MCP operation")
    return principal


class AuthAuditMiddleware:
    def __init__(self, app: ASGIApp, controller: AccessController, audit_log: AuditLog):
        self.app = app
        self.controller = controller
        self.audit_log = audit_log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not (path.startswith("/api/v1") or path.startswith("/mcp")):
            await self.app(scope, receive, send)
            return
        if path == "/api/v1/health":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        principal = self.controller.authenticate(headers)
        supplied_request_id = headers.get("x-request-id", "").strip()
        request_id = (
            supplied_request_id
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", supplied_request_id)
            else uuid.uuid4().hex
        )
        started = time.perf_counter()
        if principal is None:
            response = JSONResponse(
                {"detail": "A valid Bearer token or X-API-Key is required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer", "X-Request-ID": request_id},
            )
            await response(scope, receive, send)
            self._audit(request_id, None, scope, 401, started, outcome="denied")
            return
        scope.setdefault("state", {})["principal"] = principal
        status_code = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = response_headers
            await send(message)

        token = _current_principal.set(principal)
        try:
            await self.app(scope, receive, send_with_status)
        finally:
            _current_principal.reset(token)
            outcome = "allowed" if status_code < 400 else "failed"
            self._audit(request_id, principal, scope, status_code, started, outcome)

    def _audit(
        self,
        request_id: str,
        principal: Principal | None,
        scope: Scope,
        status_code: int,
        started: float,
        outcome: str,
    ) -> None:
        self.audit_log.append(
            request_id=request_id,
            subject=principal.subject if principal else "unauthenticated",
            role=principal.role.value if principal else "none",
            key_id=principal.key_id if principal else None,
            method=scope.get("method", "UNKNOWN"),
            path=scope.get("path", ""),
            status_code=status_code,
            duration_ms=(time.perf_counter() - started) * 1_000,
            outcome=outcome,
        )
