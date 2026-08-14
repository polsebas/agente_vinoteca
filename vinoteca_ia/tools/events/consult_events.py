"""Consulta SQL de catas y eventos próximos. Nunca RAG."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from agno.tools import tool

from schemas.tool_responses import EventoItem, EventsListResponse, ResultadoTool
from storage.postgres import fetch_all


@tool
async def consultar_eventos(limite: int = 10) -> EventsListResponse:
    """Listar catas y eventos futuros con cupo y precio.

    Usá esta tool cuando el cliente pregunta por degustaciones, fechas o
    disponibilidad de asientos. Los cupos salen de SQL.
    """
    limite = max(1, min(limite, 50))
    rows = await fetch_all(
        """
        SELECT id, titulo, descripcion, fecha, precio,
               cupo_total, cupo_disponible, activo
        FROM eventos
        WHERE activo = TRUE
          AND fecha >= NOW()
          AND cupo_disponible > 0
        ORDER BY fecha ASC
        LIMIT $1
        """,
        limite,
    )
    eventos = [
        EventoItem(
            id=str(r["id"]),
            titulo=r["titulo"],
            descripcion=r["descripcion"],
            fecha=r["fecha"] if isinstance(r["fecha"], datetime) else datetime.now(UTC),
            precio=Decimal(str(r["precio"] or 0)),
            cupo_total=int(r["cupo_total"] or 0),
            cupo_disponible=int(r["cupo_disponible"] or 0),
            activo=bool(r["activo"]),
        )
        for r in rows
    ]
    if not eventos:
        return EventsListResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            mensaje="No hay eventos próximos con cupo.",
        )
    return EventsListResponse(resultado=ResultadoTool.OK, eventos=eventos)
