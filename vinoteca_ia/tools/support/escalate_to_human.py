"""Escalada a operador humano con notificación."""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
from agno.tools import tool

from schemas.tool_responses import EscalationResponse, ResultadoTool
from storage.postgres import execute


@tool
async def escalar_a_humano(
    session_id: str,
    cliente_id: str | None,
    motivo: str,
    urgencia: str = "media",
) -> EscalationResponse:
    """Escalar la conversación a un operador humano.

    Usá esta tool cuando:
    - El cliente pide explícitamente hablar con alguien.
    - Se produjeron 2 fallos consecutivos de tools sin progreso.
    - Es un reclamo de fraude, cobro duplicado, o producto vencido.
    - No podés resolver el caso con las tools disponibles.

    La tool crea un ticket de escalada Y notifica al operador por webhook.
    Úsala con prudencia: escalar sin haber intentado otras tools es mala UX.
    Siempre le decís al cliente, en el mensaje de respuesta, que ya notificaste
    al equipo y qué puede esperar como próximo paso.

    Args:
        session_id: ID de la sesión actual.
        cliente_id: ID del cliente (puede ser None).
        motivo: Descripción breve del motivo de escalada.
        urgencia: "baja" | "media" | "alta" (default: "media").

    Returns:
        EscalationResponse con `ticket_id` y `operador_notificado=True` si el
        webhook respondió OK.
    """
    if not motivo.strip():
        return EscalationResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="Motivo de escalada vacío.",
        )
    if urgencia not in {"baja", "media", "alta"}:
        return EscalationResponse(
            resultado=ResultadoTool.ERROR,
            mensaje=f"Urgencia inválida: {urgencia}.",
        )

    ticket_id = str(uuid4())
    await execute(
        """
        INSERT INTO tickets_soporte (
            id, session_id, cliente_id, categoria, descripcion,
            urgencia, estado, created_at
        ) VALUES ($1,$2,$3,'escalada',$4,$5,'abierto', NOW())
        """,
        ticket_id,
        session_id,
        cliente_id,
        motivo,
        urgencia,
    )

    notificado = await _notificar_operador(ticket_id, motivo, urgencia)
    return EscalationResponse(
        resultado=ResultadoTool.OK,
        ticket_id=ticket_id,
        operador_notificado=notificado,
    )


async def _notificar_operador(ticket_id: str, motivo: str, urgencia: str) -> bool:
    webhook = os.environ.get("OPERATOR_WEBHOOK_URL")
    if not webhook:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                webhook,
                json={"ticket_id": ticket_id, "motivo": motivo, "urgencia": urgencia},
            )
            return 200 <= resp.status_code < 300
    except Exception:
        return False
