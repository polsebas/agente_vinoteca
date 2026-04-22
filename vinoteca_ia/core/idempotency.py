"""Manager de idempotencia para operaciones críticas (crear pedido, cobrar).

Evita cobros dobles frente a reintentos por fallo de red o timeouts.
Usa Redis como backend con TTL configurable. Si la key ya existe, devuelve
el resultado previo cacheado; si no, ejecuta la operación y persiste el
resultado bajo la key.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import redis.asyncio as aioredis
from pydantic import BaseModel, ConfigDict


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
        _client = aioredis.from_url(url, decode_responses=True)
    return _client


class IdempotencyManager:
    """Gestiona claves de idempotencia con TTL sobre Redis."""

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self.ttl_seconds = ttl_seconds or int(
            os.environ.get("IDEMPOTENCY_TTL_SECONDS", "1800")
        )

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
        record = IdempotencyRecord(
            key=key, resultado_json=resultado_json, status=status
        )
        await client.setex(key, self.ttl_seconds, record.model_dump_json())

    async def ping(self) -> bool:
        try:
            return bool(await _get_client().ping())
        except Exception:
            return False

    async def serialize_payload(self, payload: Any) -> str:
        """Serializa Pydantic models u otros tipos a string JSON."""
        if isinstance(payload, BaseModel):
            return payload.model_dump_json()
        return json.dumps(payload, default=str)
