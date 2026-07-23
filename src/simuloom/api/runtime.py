from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from simuloom.container import service

runtime_router = APIRouter(prefix="/runtime")


@runtime_router.api_route(
    "/{simulation_id}/{service_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def invoke_native_runtime(
    simulation_id: str, service_path: str, request: Request
) -> JSONResponse:
    body: Any = None
    if request.headers.get("content-type", "").split(";", 1)[0].strip() == "application/json":
        try:
            body = await request.json()
        except ValueError:
            body = None
    path = f"/{service_path}"
    if request.url.query:
        path = f"{path}?{request.url.query}"
    observation = await service.runtime.execute(
        request.method,
        path,
        body,
        dict(request.headers),
        simulation_id,
    )
    safe_headers = {
        name: value
        for name, value in observation.headers.items()
        if name.lower() not in {"content-length", "transfer-encoding", "connection"}
    }
    return JSONResponse(
        content=observation.body,
        status_code=observation.status_code,
        headers=safe_headers,
    )
