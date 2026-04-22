"""Dependencias HTTP compartidas: autenticación por token y rate limiting.

- `require_approval_token`: obligatorio en `/pedido/{run_id}/aprobar`.
- `require_admin_token`: obligatorio en `/admin/*`.
- `optional_chat_key`: si `CHAT_API_KEY` está definido, exige header; si no, deja
  pasar en modo dev (comportamiento previo).
- `RateLimiter`: sliding window vía Redis `INCR`+TTL. Si Redis no responde,
  failopen (log warning): preferimos disponibilidad del chat a un lockout total.
"""

from __future__ import annotations

import logging
import os

from fastapi import Header, HTTPException, Request

from core.idempotency import _get_client as _redis_client

logger = logging.getLogger("vinoteca.api.deps")


def _const_eq(a: str | None, b: str | None) -> bool:
    """Comparación de strings resistente a timing trivial (longitud + xor)."""
    if a is None or b is None or len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b, strict=True):
        result |= ord(x) ^ ord(y)
    return result == 0


async def require_approval_token(
    x_approval_token: str | None = Header(default=None),
) -> None:
    """Exige header `X-Approval-Token` igual a `APPROVAL_API_TOKEN` del entorno.

    Si la variable no está seteada, rechaza todas las requests con 503: el
    endpoint es destructivo y no debe quedar abierto por olvido de configuración.
    """
    expected = os.environ.get("APPROVAL_API_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Aprobación deshabilitada: configurá APPROVAL_API_TOKEN.",
        )
    if not _const_eq(x_approval_token, expected):
        raise HTTPException(status_code=401, detail="Token de aprobación inválido.")


async def require_admin_token(
    x_admin_token: str | None = Header(default=None),
) -> None:
    """Exige header `X-Admin-Token` igual a `ADMIN_API_TOKEN`."""
    expected = os.environ.get("ADMIN_API_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Endpoint admin deshabilitado: falta ADMIN_API_TOKEN.",
        )
    if not _const_eq(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Token admin inválido.")


async def optional_chat_key(
    x_chat_key: str | None = Header(default=None),
) -> None:
    """Si `CHAT_API_KEY` está definido, el header es obligatorio; si no, pasa."""
    expected = os.environ.get("CHAT_API_KEY")
    if not expected:
        return
    if not _const_eq(x_chat_key, expected):
        raise HTTPException(status_code=401, detail="API key inválida.")


class RateLimiter:
    """Sliding-window simple por bucket `scope:identity` con TTL en Redis."""

    def __init__(self, scope: str, limit: int, window_seconds: int) -> None:
        self.scope = scope
        self.limit = limit
        self.window = window_seconds

    async def __call__(self, request: Request) -> None:
        identity = _client_identity(request)
        key = f"rl:{self.scope}:{identity}"
        try:
            client = _redis_client()
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, self.window)
            if count > self.limit:
                ttl = await client.ttl(key)
                raise HTTPException(
                    status_code=429,
                    detail=f"Demasiadas requests. Reintentá en {max(ttl, 1)}s.",
                    headers={"Retry-After": str(max(ttl, 1))},
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Rate limiter failopen (%s): %s", self.scope, exc)


def _client_identity(request: Request) -> str:
    """Resuelve la identidad del cliente: API key > IP real > IP directa."""
    chat_key = request.headers.get("X-Chat-Key")
    approval_token = request.headers.get("X-Approval-Token")
    admin_token = request.headers.get("X-Admin-Token")
    token = chat_key or approval_token or admin_token
    if token:
        return f"tok:{hash(token) & 0xFFFFFFFF:x}"
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded:
        return f"ip:{forwarded}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


chat_rate_limiter = RateLimiter(
    scope="chat",
    limit=int(os.environ.get("RATE_LIMIT_CHAT_PER_MIN", "30")),
    window_seconds=60,
)
approval_rate_limiter = RateLimiter(
    scope="approval",
    limit=int(os.environ.get("RATE_LIMIT_APPROVAL_PER_MIN", "20")),
    window_seconds=60,
)
admin_rate_limiter = RateLimiter(
    scope="admin",
    limit=int(os.environ.get("RATE_LIMIT_ADMIN_PER_MIN", "5")),
    window_seconds=60,
)
