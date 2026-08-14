"""Manager de idempotencia para operaciones críticas (crear pedido, cobrar).

Evita cobros dobles frente a reintentos por fallo de red o timeouts.
Usa Redis como backend con TTL configurable. Fallback: tabla PostgreSQL
`idempotency_keys` y, si tampoco hay DB, un mapa in-process (tests).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

import redis.asyncio as aioredis
from pydantic import BaseModel, ConfigDict

from storage.postgres import execute, fetchrow

_MEMORY_KEYS: dict[str, float] = {}


class IdempotencyRecord(BaseModel):
    """Resultado cacheado de una operación idempotente."""

    model_config = ConfigDict(extra="forbid")

    key: str
    resultado_json: str
    status: str


_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _client = aioredis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=1.0,
        )
    return _client


def generate_idempotency_key(session_id: str, step: int, payload_str: str) -> str:
    """Clave determinista por sesión + paso PRAO + payload."""
    return IdempotencyManager.build_key(session_id, str(step), payload_str)


async def check_or_set_idempotency_key(key: str, ttl_seconds: int = 1800) -> bool:
    """SET NX con TTL.

    Returns:
        True si la key es nueva (la operación puede ejecutarse).
        False si ya existía (duplicado: no re-ejecutar).
    """
    try:
        client = _get_client()
        was_set = await client.set(key, "1", nx=True, ex=ttl_seconds)
        return bool(was_set)
    except Exception:
        pass

    try:
        await execute(
            "DELETE FROM idempotency_keys WHERE key = $1 AND expires_at < NOW()",
            key,
        )
        row = await fetchrow(
            """
            INSERT INTO idempotency_keys (key, expires_at)
            VALUES ($1, NOW() + ($2 * INTERVAL '1 second'))
            ON CONFLICT (key) DO NOTHING
            RETURNING key
            """,
            key,
            int(ttl_seconds),
        )
        return row is not None
    except Exception:
        return _check_or_set_memory(key, ttl_seconds)


def _check_or_set_memory(key: str, ttl_seconds: int) -> bool:
    now = time.time()
    expires_at = _MEMORY_KEYS.get(key)
    if expires_at is not None and expires_at > now:
        return False
    _MEMORY_KEYS[key] = now + ttl_seconds
    return True


class IdempotencyManager:
    """Gestiona claves de idempotencia con TTL sobre Redis."""

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self.ttl_seconds = ttl_seconds or int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "1800"))

    @staticmethod
    def build_key(*parts: str) -> str:
        """Construye una clave determinista a partir de sus componentes."""
        raw = "|".join(parts)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        return f"idem:{digest}"

    async def get(self, key: str) -> IdempotencyRecord | None:
        client = _get_client()
        raw = await client.get(key)
        if raw is None:
            return None
        data = json.loads(raw)
        return IdempotencyRecord(**data)

    async def put(self, key: str, resultado_json: str, status: str = "ok") -> None:
        client = _get_client()
        record = IdempotencyRecord(key=key, resultado_json=resultado_json, status=status)
        await client.setex(key, self.ttl_seconds, record.model_dump_json())

    async def ping(self) -> bool:
        try:
            return bool(await _get_client().ping())
        except Exception:
            return False


async def rate_limit_check(
    identifier: str,
    max_requests: int = 60,
    window: int = 60,
) -> bool:
    """Sliding window Redis. True = permitido. Fail-open si Redis no responde."""
    key = f"rl:mw:{identifier}"
    try:
        client = _get_client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window)
        return int(count) <= max_requests
    except Exception:
        return True

    async def serialize_payload(self, payload: Any) -> str:
        """Serializa Pydantic models u otros tipos a string JSON."""
        if isinstance(payload, BaseModel):
            return payload.model_dump_json()
        return json.dumps(payload, default=str)
