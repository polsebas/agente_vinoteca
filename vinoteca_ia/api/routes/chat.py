"""
POST /chat — punto de entrada de conversación con SSE streaming.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.correlation import generar, set_current
from core.guardrails import (
    RESPUESTA_BLOQUEADA_JAILBREAK,
    RESPUESTA_BLOQUEADA_PII,
    verificar_entrada,
)
from core.orchestrator import Orchestrator
from schemas.agent_io import SessionRequest
from schemas.session_state import SessionState, TurnoHistorial

router = APIRouter()
_orchestrator = Orchestrator()


class ChatInput(BaseModel):
    mensaje: str
    session_id: str | None = None


@router.post("/chat", tags=["Agente"])
async def chat(body: ChatInput, request: Request) -> StreamingResponse:
    canal = getattr(request.state, "canal", "web")

    session_id = body.session_id or generar(canal)
    correlation_id = generar(canal)
    set_current(correlation_id)

    guardrail = verificar_entrada(body.mensaje)
    if guardrail.bloqueado:
        respuesta_bloqueada = (
            RESPUESTA_BLOQUEADA_PII
            if guardrail.tipo == "pii"
            else RESPUESTA_BLOQUEADA_JAILBREAK
        )

        async def stream_bloqueado():
            payload = json.dumps({
                "session_id": session_id,
                "correlation_id": correlation_id,
                "respuesta": respuesta_bloqueada,
                "requiere_aprobacion": False,
                "bloqueado": True,
                "razon": guardrail.tipo,
            })
            yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_bloqueado(), media_type="text/event-stream")

    state = SessionState(
        session_id=session_id,
        correlation_id=correlation_id,
        canal=canal,
    )

    session_req = SessionRequest(
        mensaje=body.mensaje,
        session_id=session_id,
        correlation_id=correlation_id,
        canal=canal,
    )

    async def stream_respuesta():
        try:
            response = await _orchestrator.procesar(session_req, state)

            payload = json.dumps({
                "session_id": response.session_id,
                "correlation_id": response.correlation_id,
                "respuesta": response.respuesta,
                "agente": response.agente,
                "requiere_aprobacion": response.requiere_aprobacion,
                "pedido_id": response.pedido_id,
                "finalizado": response.finalizado,
            })
            yield f"data: {payload}\n\n"

        except Exception as e:
            error_payload = json.dumps({
                "session_id": session_id,
                "correlation_id": correlation_id,
                "respuesta": "Lo siento, ocurrió un error procesando tu consulta. Por favor intentá de nuevo.",
                "error": str(e),
                "finalizado": True,
            })
            yield f"data: {error_payload}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_respuesta(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Correlation-ID": correlation_id,
        },
    )
