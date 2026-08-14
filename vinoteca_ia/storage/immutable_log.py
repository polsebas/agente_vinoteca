"""Escritura append-only en `log_inmutable`.

Cada mutación crítica (crear pedido, reservar evento, cobrar) debe dejar
una fila con hash SHA-256 del payload. No hay UPDATE ni DELETE.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from storage.postgres import execute


def _normalize_payload(payload: dict[str, Any] | BaseModel | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    return dict(payload)


def hash_payload(payload: dict[str, Any] | BaseModel | None) -> str:
    """SHA-256 del JSON canónico (claves ordenadas)."""
    data = _normalize_payload(payload)
    canonical = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def log_transaction_event(
    session_id: str,
    accion: str,
    payload: dict[str, Any] | BaseModel,
    idempotency_key: str | None,
    resultado: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Inserta una fila inmutable. No muta filas previas."""
    payload_hash = hash_payload(payload)
    meta = metadata or {}
    await execute(
        """
        INSERT INTO log_inmutable (
            timestamp, session_id, accion, payload_hash,
            idempotency_key, resultado, metadata
        ) VALUES (NOW(), $1, $2, $3, $4, $5, $6::jsonb)
        """,
        session_id,
        accion,
        payload_hash,
        idempotency_key,
        resultado,
        json.dumps(meta, default=str),
    )


async def registrar(
    evento: str,
    *,
    pedido_id: UUID | str | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Compatibilidad: envuelve `log_transaction_event` para callers previos."""
    meta: dict[str, Any] = {}
    if pedido_id is not None:
        meta["pedido_id"] = str(pedido_id)
    if correlation_id:
        meta["correlation_id"] = correlation_id
    await log_transaction_event(
        session_id=session_id or "",
        accion=evento,
        payload=payload or {},
        idempotency_key=None,
        resultado="ok",
        metadata=meta,
    )
