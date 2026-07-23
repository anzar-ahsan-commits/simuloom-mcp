from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from simuloom.api.routes import router
from simuloom.api.runtime import runtime_router
from simuloom.container import access_controller, audit_log
from simuloom.core.audit import AuditLog
from simuloom.mcp.server import mcp
from simuloom.security import AccessController, AuthAuditMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


def create_app(
    controller: AccessController | None = None,
    request_audit_log: AuditLog | None = None,
) -> FastAPI:
    application = FastAPI(
        title="SimuLoom",
        version="0.12.0",
        description="Contract-driven service virtualization, scenarios, and synthetic test data.",
        lifespan=lifespan,
    )
    selected_controller = controller or access_controller
    selected_audit_log = request_audit_log or audit_log
    application.state.audit_log = selected_audit_log
    application.include_router(router)
    application.include_router(runtime_router)
    application.mount("/mcp", mcp.streamable_http_app())
    application.add_middleware(
        AuthAuditMiddleware,
        controller=selected_controller,
        audit_log=selected_audit_log,
    )
    return application


app = create_app()


def run() -> None:
    uvicorn.run("simuloom.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
