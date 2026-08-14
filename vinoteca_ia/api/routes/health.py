"""Healthcheck: ping async a PostgreSQL, Redis y MemGraphRAG."""

from __future__ import annotations

from fastapi import APIRouter

from core.idempotency import IdempotencyManager
from core.rag.memgraph_adapter import ping_graph
from storage.postgres import ping as ping_postgres

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Verifica conectividad con dependencias críticas.

    Siempre responde 200. Un componente degradado se refleja en el payload;
    el LB decide si saca la instancia.
    """
    db_ok = await ping_postgres()
    try:
        redis_ok = await IdempotencyManager().ping()
    except Exception:
        redis_ok = False
    try:
        graph_ok = ping_graph()
    except Exception:
        graph_ok = False

    healthy = db_ok and redis_ok and graph_ok
    return {
        "status": "healthy" if healthy else "degraded",
        "db": db_ok,
        "redis": redis_ok,
        "graph": graph_ok,
        "storage": "ok" if db_ok else "error",
        "idempotency": "ok" if redis_ok else "error",
        "llm": "ok",
    }
