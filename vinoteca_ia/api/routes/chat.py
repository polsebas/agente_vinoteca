"""Chat endpoint con streaming SSE.

El cliente envía un mensaje y recibe un stream de eventos del Team router.
Si el Team llega a una tool con `requires_confirmation=True` (ej. `crear_orden`),
el stream emite un evento `paused` con el `run_id` del Team y la lista de
tool executions pendientes. El cliente debe llamar a `/pedido/{run_id}/aprobar`
con el token de aprobación para continuar.

Diseño del stream:
- `event: token`   → chunks intermedios (content, eventos, etc.).
- `event: paused`  → HitL requerido. Payload con `run_id`, `session_id`,
  `pending_tools` y `member` cuando la pausa viene de un miembro del Team.
- `event: done`    → cierre ordenado.
- `event: error`   → mensaje genérico (detalle interno queda en logs).
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.router_team import crear_router_team
from api.deps import chat_rate_limiter, optional_chat_key

logger = logging.getLogger("vinoteca.api.chat")

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Entrada del cliente al canal de chat."""

    mensaje: str = Field(..., min_length=1, description="Texto del usuario.")
    session_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="ID de conversación persistente.",
    )
    cliente_id: str | None = Field(
        default=None, description="Si el cliente está identificado."
    )


def _sse(event: str, data: dict) -> bytes:
    """Formatea un evento SSE compatible con EventSource nativo."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode()


@router.post(
    "/chat",
    dependencies=[Depends(optional_chat_key), Depends(chat_rate_limiter)],
)
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Endpoint principal: stream SSE del turno del agente."""
    team = crear_router_team()

    async def event_stream():
        run_id: str | None = None
        paused_emitted = False
        stream = team.arun(
            input=req.mensaje,
            session_id=req.session_id,
            user_id=req.cliente_id,
            stream=True,
            stream_events=True,
        )
        try:
            async for ev in stream:
                if await request.is_disconnected():
                    break

                run_id = getattr(ev, "run_id", None) or run_id
                event_name = getattr(ev, "event", type(ev).__name__)
                payload: dict = {"event": event_name}

                content = getattr(ev, "content", None)
                if content is not None:
                    payload["content"] = (
                        content.model_dump() if isinstance(content, BaseModel) else str(content)
                    )

                is_paused = getattr(ev, "is_paused", False) or "Paused" in event_name
                if is_paused and not paused_emitted:
                    paused_emitted = True
                    yield _sse(
                        "paused",
                        _build_paused_payload(ev, run_id, req.session_id),
                    )
                    break

                yield _sse("token", payload)

            if not paused_emitted:
                yield _sse("done", {"run_id": run_id, "session_id": req.session_id})
        except Exception as exc:
            logger.exception("Error en stream /chat session=%s: %s", req.session_id, exc)
            yield _sse(
                "error",
                {"message": "Ocurrió un error procesando el mensaje. Reintentá en un momento."},
            )
        finally:
            aclose = getattr(stream, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except Exception as close_exc:
                    logger.debug("aclose() del stream falló: %s", close_exc)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_paused_payload(event, run_id: str | None, session_id: str) -> dict:
    """Construye el payload del evento `paused` con contexto HitL completo.

    Estructura:
    - `run_id`: el run_id del Team (el que el cliente envía a /aprobar).
    - `component_type`: "team" cuando la pausa vino desde el router (caso productivo).
    - `pending_tools`: lista de tools a confirmar con su miembro asociado si aplica.

    Agno propaga las `RunRequirement` desde los miembros al Team con
    `member_agent_id`/`member_agent_name`/`member_run_id` ya populados.
    """
    pending_tools: list[dict] = []

    for req in getattr(event, "requirements", None) or []:
        te = getattr(req, "tool_execution", None)
        if te is None:
            continue
        pending_tools.append(
            {
                "tool_call_id": getattr(te, "tool_call_id", None),
                "tool_name": getattr(te, "tool_name", None),
                "tool_args": getattr(te, "tool_args", None),
                "member_agent_id": getattr(req, "member_agent_id", None),
                "member_agent_name": getattr(req, "member_agent_name", None),
                "member_run_id": getattr(req, "member_run_id", None),
            }
        )

    if not pending_tools:
        for t in getattr(event, "tools", None) or []:
            if getattr(t, "is_paused", False) or getattr(t, "requires_confirmation", False):
                pending_tools.append(
                    {
                        "tool_call_id": getattr(t, "tool_call_id", None),
                        "tool_name": getattr(t, "tool_name", None),
                        "tool_args": getattr(t, "tool_args", None),
                    }
                )

    return {
        "run_id": run_id,
        "session_id": session_id,
        "component_type": "team",
        "pending_tools": pending_tools,
    }
