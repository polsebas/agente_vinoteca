"""Registro de reclamos del cliente."""

from __future__ import annotations

from uuid import uuid4

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
    """Registrar un reclamo formal del cliente en la base de tickets.

    Usá esta tool cuando:
    - El cliente describe un problema con un pedido ya entregado.
    - Reporta un vino defectuoso, entrega demorada, o cargo incorrecto.

    Esta tool NO escala automáticamente a humano. Crea el ticket y devuelve
    su ID para que el cliente pueda referenciarlo. Si el tema es urgente
    (fraude, cargo duplicado, producto vencido), llamá además a
    `escalar_a_humano` en el mismo turno.

    Args:
        session_id: ID de la sesión actual.
        cliente_id: ID del cliente (puede ser None).
        categoria: "entrega", "producto", "cobro", "otro".
        descripcion: Descripción del problema (texto libre del cliente).

    Returns:
        EscalationResponse con el `ticket_id`.
    """
    if not descripcion.strip():
        return EscalationResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La descripción del reclamo no puede estar vacía.",
        )

    ticket_id = str(uuid4())
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
    return EscalationResponse(
        resultado=ResultadoTool.OK,
        ticket_id=ticket_id,
        operador_notificado=False,
    )
