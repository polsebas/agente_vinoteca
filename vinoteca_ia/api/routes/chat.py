"""Chat endpoint: JSON síncrono o SSE vía `VinotecaOrchestrator.process_turn`.

Si `stream=true` (default) emite eventos SSE. Si el orquestador marca
`requiere_aprobacion`, se agrega un evento `paused` para el flujo HitL.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.deps import chat_rate_limiter, optional_chat_key
from core.correlation import generate_correlation_id, get_current, set_current
from core.orchestrator import get_orchestrator
from schemas.agent_io import AgentResponse
from schemas.api import ChatRequest

logger = logging.getLogger("vinoteca.api.chat")

router = APIRouter(tags=["chat"])


def _sse(event: str, data: dict) -> bytes:
    """Formatea un evento SSE compatible con EventSource nativo."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode()


def _correlation_headers(correlation_id: str) -> dict[str, str]:
    return {
        "X-Correlation-ID": correlation_id,
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }


@router.post(
    "/chat",
    dependencies=[Depends(optional_chat_key), Depends(chat_rate_limiter)],
)
async def chat(req: ChatRequest, request: Request):
    """Endpoint principal: `process_turn` en JSON o stream SSE."""
    cid = generate_correlation_id(req.session_id)
    set_current(cid)
    orch = get_orchestrator()

    if not req.stream:
        try:
            resp = await orch.process_turn(
                req.session_id,
                req.mensaje,
                canal=req.canal,
                cliente_id=req.cliente_id,
            )
        except Exception as exc:
            logger.exception("Error en /chat session=%s: %s", req.session_id, exc)
            return JSONResponse(
                {
                    "detail": "Ocurrió un error procesando el mensaje. Reintentá en un momento.",
                },
                status_code=502,
                headers=_correlation_headers(get_current() or cid),
            )
        return JSONResponse(
            resp.model_dump(mode="json"),
            headers=_correlation_headers(resp.correlation_id or cid),
        )

    async def event_stream():
        try:
            resp = await orch.process_turn(
                req.session_id,
                req.mensaje,
                canal=req.canal,
                cliente_id=req.cliente_id,
            )
            if await request.is_disconnected():
                return
            payload = resp.model_dump(mode="json")
            yield _sse("token", {"content": resp.respuesta, "agente": resp.agente})
            if resp.requiere_aprobacion:
                yield _sse("paused", _paused_payload(resp))
            yield _sse("done", payload)
        except Exception as exc:
            logger.exception("Error en stream /chat session=%s: %s", req.session_id, exc)
            yield _sse(
                "error",
                {"message": "Ocurrió un error procesando el mensaje. Reintentá en un momento."},
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_correlation_headers(get_current() or cid),
    )


def _paused_payload(resp: AgentResponse) -> dict:
    return {
        "run_id": None,
        "session_id": resp.session_id,
        "component_type": "orchestrator",
        "requiere_aprobacion": True,
        "pending_tools": [],
    }
