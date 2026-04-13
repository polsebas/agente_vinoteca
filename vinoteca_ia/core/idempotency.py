"""
Idempotency Keys via Redis para prevenir dobles ejecuciones de mutaciones críticas.
TTL por defecto: 1800 segundos (30 minutos).
"""

from __future__ import annotations

import os

import redis.asyncio as aioredis

_redis: aioredis.Redis | None = None
_TTL = int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "1800"))


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


async def adquirir(key: str) -> bool:
    """
    Intenta adquirir el lock de idempotencia.
    Retorna True si lo adquirió (primera vez), False si ya existía (duplicado).
    """
    r = await get_redis()
    result = await r.set(f"idempotency:{key}", "1", nx=True, ex=_TTL)
    return result is not None


async def existe(key: str) -> bool:
    """Comprueba si la key ya fue procesada sin adquirir el lock."""
    r = await get_redis()
    return bool(await r.exists(f"idempotency:{key}"))


async def liberar(key: str) -> None:
    """Libera el lock manualmente (ej: en caso de rollback)."""
    r = await get_redis()
    await r.delete(f"idempotency:{key}")


async def rate_limit_check(identifier: str, max_requests: int = 60, window: int = 60) -> bool:
    """
    Rate limiting por ventana deslizante.
    Retorna True si el request es permitido.
    """
    r = await get_redis()
    rl_key = f"rl:{identifier}"
    current = await r.incr(rl_key)
    if current == 1:
        await r.expire(rl_key, window)
    return current <= max_requests
