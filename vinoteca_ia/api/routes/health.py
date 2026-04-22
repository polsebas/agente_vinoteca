"""Healthcheck liviano: ping a DB y Redis."""

from __future__ import annotations

from fastapi import APIRouter

from core.idempotency import IdempotencyManager
from storage.postgres import ping as ping_postgres

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Verifica conectividad con dependencias críticas.

    Responde 200 con el estado granular de cada backend. Un componente
    degradado se refleja como "error", pero el endpoint siempre responde
    200 (el LB decide si saca la instancia mirando el payload).
    """
    storage_ok = await ping_postgres()
    try:
        redis_ok = await IdempotencyManager().ping()
    except Exception:
        redis_ok = False

    return {
        "status": "ok" if storage_ok else "degraded",
        "storage": "ok" if storage_ok else "error",
        "idempotency": "ok" if redis_ok else "error",
        "llm": "ok",
    }
