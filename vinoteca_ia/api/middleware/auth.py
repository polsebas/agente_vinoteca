"""
Autenticación de canales mediante Bearer token en el header X-Channel-Token.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

_TOKENS: dict[str, str] = {
    "web": os.environ.get("CHANNEL_TOKEN_WEB", "token_web_dev"),
}

_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        token = request.headers.get("X-Channel-Token") or request.headers.get("Authorization", "").removeprefix("Bearer ")

        if not token or token not in _TOKENS.values():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de canal inválido o ausente.",
            )

        canal = next((c for c, t in _TOKENS.items() if t == token), "desconocido")
        request.state.canal = canal
        return await call_next(request)
