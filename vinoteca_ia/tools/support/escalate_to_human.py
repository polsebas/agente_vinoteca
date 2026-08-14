"""Escalada a operador humano con transcripción de sesión."""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
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
    transcript: str | None = None,
) -> EscalationResponse:
    """Escalar a un operador con motivo y transcripción completa.

    Usá esta tool si el cliente pide un humano, hay 2 fallos seguidos de tools,
    o es fraude/cobro duplicado. No escales sin haber intentado FAQ u otras tools.
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
    try:
        await execute(
            """
            INSERT INTO tickets_soporte (
                id, session_id, cliente_id, categoria, descripcion,
                urgencia, estado, transcript, created_at
            ) VALUES ($1,$2,$3,'escalada',$4,$5,'abierto',$6, NOW())
            """,
            ticket_id,
            session_id,
            cliente_id,
            motivo,
            urgencia,
            transcript,
        )
    except asyncpg.UndefinedTableError:
        return EscalationResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="Esquema de tickets no inicializado.",
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
