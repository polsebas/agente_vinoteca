"""
Escritura append-only en log_inmutable.
Cada mutación del sistema debe registrarse aquí antes de ejecutarse.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from storage.postgres import execute


async def registrar(
    evento: str,
    *,
    pedido_id: UUID | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """
    Invocar antes o después de cualquier mutación crítica (crear pedido,
    confirmar, cancelar, cobrar, reembolsar).
    """
    await execute(
        """
        INSERT INTO log_inmutable (pedido_id, session_id, correlation_id, evento, payload)
        VALUES ($1, $2, $3, $4, $5)
        """,
        pedido_id,
        session_id,
        correlation_id,
        evento,
        json.dumps(payload or {}),
    )
