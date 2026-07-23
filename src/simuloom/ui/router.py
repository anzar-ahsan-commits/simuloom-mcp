from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

STATIC_ROOT = Path(__file__).parent / "static"
ui_router = APIRouter(include_in_schema=False)


@ui_router.get("/", response_class=RedirectResponse)
def root_console_redirect() -> RedirectResponse:
    return RedirectResponse("/ui", status_code=307)


@ui_router.get("/ui", response_class=FileResponse)
@ui_router.get("/ui/", response_class=FileResponse)
def operator_console() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html", media_type="text/html")


class ConsoleSecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/ui"):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (
                            b"content-security-policy",
                            b"default-src 'self'; img-src 'self' data:; "
                            b"style-src 'self'; script-src 'self'; connect-src 'self'; "
                            b"base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                        ),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
