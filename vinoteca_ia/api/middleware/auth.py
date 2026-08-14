"""Autenticación de canales mediante Bearer / X-Channel-Token.

Por default el middleware es passthrough (`CHANNEL_AUTH_REQUIRED` unset):
`/chat` y `/webhook` siguen públicos. Si se activa el flag, exige un token
conocido salvo en paths de salud y docs.
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_TOKENS: dict[str, str] = {
    "web": os.environ.get("CHANNEL_TOKEN_WEB", "token_web_dev"),
    "whatsapp": os.environ.get("CHANNEL_TOKEN_WHATSAPP", "token_wa_dev"),
}

_PUBLIC_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/webhook",
    "/chat",
)


def _auth_required() -> bool:
    return os.environ.get("CHANNEL_AUTH_REQUIRED", "").lower() in {"1", "true", "yes", "on"}


def _is_public(path: str) -> bool:
    for prefix in _PUBLIC_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if _is_public(request.url.path) or not _auth_required():
            if not getattr(request.state, "canal", None):
                request.state.canal = "web"
            return await call_next(request)

        raw = request.headers.get("X-Channel-Token") or request.headers.get("Authorization", "")
        token = raw.removeprefix("Bearer ").strip()
        if not token or token not in _TOKENS.values():
            return JSONResponse(
                {"detail": "Token de canal inválido o ausente."},
                status_code=401,
            )

        request.state.canal = next((c for c, t in _TOKENS.items() if t == token), "desconocido")
        return await call_next(request)
