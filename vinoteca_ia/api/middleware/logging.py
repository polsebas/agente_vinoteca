"""Logging estructurado de requests con correlation_id y timing."""

from __future__ import annotations

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from core.correlation import generate_correlation_id, get_current, set_current

logger = structlog.get_logger()


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("X-Correlation-ID", "").strip()
        session_hint = request.headers.get("X-Session-Id", "http")
        cid = incoming or get_current() or generate_correlation_id(session_hint)
        set_current(cid)
        request.state.correlation_id = cid

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

        header_cid = get_current() or cid
        response.headers.setdefault("X-Correlation-ID", header_cid)

        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            correlation_id=header_cid,
            canal=getattr(request.state, "canal", "unknown"),
        )
        return response
