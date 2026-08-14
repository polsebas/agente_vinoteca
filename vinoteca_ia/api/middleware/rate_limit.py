"""Rate limiting por IP/sesión con sliding window en Redis (fail-open)."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.idempotency import rate_limit_check

_RATE_LIMIT_PREFIXES = ("/chat", "/pedido", "/webhook/whatsapp")


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not any(path == p or path.startswith(p + "/") for p in _RATE_LIMIT_PREFIXES):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        canal = getattr(request.state, "canal", "web")
        session = request.headers.get("X-Session-Id", "")
        identifier = f"{canal}:{session or client_ip}"

        permitido = await rate_limit_check(identifier, max_requests=60, window=60)
        if not permitido:
            return JSONResponse(
                {"detail": "Demasiadas solicitudes. Por favor esperá un momento."},
                status_code=429,
            )

        return await call_next(request)
