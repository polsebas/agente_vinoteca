"""
Rate limiting por IP + canal usando Redis.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from core.idempotency import rate_limit_check

_RATE_LIMIT_PATHS = {"/chat", "/aprobar"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path not in _RATE_LIMIT_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        canal = getattr(request.state, "canal", "web")
        identifier = f"{canal}:{client_ip}"

        permitido = await rate_limit_check(identifier, max_requests=60, window=60)
        if not permitido:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes. Por favor esperá un momento.",
            )

        return await call_next(request)
