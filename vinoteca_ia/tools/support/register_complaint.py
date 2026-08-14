"""Registro de reclamos del cliente en tickets_soporte."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
from agno.tools import tool

from schemas.tool_responses import EscalationResponse, ResultadoTool
from storage.postgres import execute


@tool
async def registrar_reclamo(
    session_id: str,
    cliente_id: str | None,
    categoria: str,
    descripcion: str,
) -> EscalationResponse:
    """Registrar un reclamo formal (entrega, producto, cobro).

    No escala sola: si es fraude, cargo duplicado o producto vencido,
    llamá también a `escalar_a_humano` en el mismo turno.
    """
    if not descripcion.strip():
        return EscalationResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La descripción del reclamo no puede estar vacía.",
        )
    ticket_id = str(uuid4())
    try:
        await execute(
            """
            INSERT INTO tickets_soporte (
                id, session_id, cliente_id, categoria, descripcion, estado, created_at
            ) VALUES ($1,$2,$3,$4,$5,'abierto', NOW())
            """,
            ticket_id,
            session_id,
            cliente_id,
            categoria,
            descripcion,
        )
    except asyncpg.UndefinedTableError:
        return EscalationResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="Esquema de tickets no inicializado.",
        )
    return EscalationResponse(
        resultado=ResultadoTool.OK,
        ticket_id=ticket_id,
        operador_notificado=False,
    )
