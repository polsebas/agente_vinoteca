"""Aprobación humana de pedidos pausados (Fase 2 del 2PC).

Cuando `/chat` emite un evento `paused`, un operador autorizado llama a este
endpoint con `X-Approval-Token` para reanudar el Team.

Contrato con Agno (validado contra `agno.team._tools._propagate_member_pause`):
cuando una tool de un miembro lleva `requires_confirmation=True`, Agno propaga
la `RunRequirement` al `TeamRunOutput`. Por eso el `run_id` del evento `paused`
es el del Team, y la reanudación se hace sobre el Team (no sobre el miembro):
internamente, `team.acontinue_run` agrupa requirements por `member_agent_id` y
reanuda cada miembro. La vía correcta es mutar `run.requirements[*]` con
`req.confirm()` / `req.reject(note=...)`, no mutar `run.tools`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agents.router_team import crear_router_team
from api.deps import approval_rate_limiter, require_approval_token

logger = logging.getLogger("vinoteca.api.approve")

router = APIRouter(tags=["orders"])


class ApproveRequest(BaseModel):
    """Decisión explícita del aprobador."""

    aprobar: bool = Field(..., description="True para continuar, False para rechazar.")
    session_id: str = Field(..., description="Session_id original del chat.")
    nota: str | None = Field(default=None, description="Nota del aprobador.")


@router.post(
    "/pedido/{run_id}/aprobar",
    dependencies=[Depends(require_approval_token), Depends(approval_rate_limiter)],
)
async def aprobar_pedido(run_id: str, req: ApproveRequest) -> dict:
    """Reanudar un run pausado con la decisión humana."""
    team = crear_router_team()
    run = await team.aget_run_output(run_id=run_id, session_id=req.session_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run_id {run_id} no existe")

    requirements = getattr(run, "requirements", None) or []
    pendientes = [r for r in requirements if getattr(r, "needs_confirmation", False)]
    if not pendientes:
        raise HTTPException(
            status_code=409,
            detail="El run no tiene requerimientos de confirmación pendientes.",
        )

    for requirement in pendientes:
        if req.aprobar:
            requirement.confirm()
        else:
            requirement.reject(note=req.nota)

    try:
        final = await team.acontinue_run(
            run_response=run,
            session_id=req.session_id,
            stream=False,
        )
    except Exception as exc:
        logger.exception("Fallo al reanudar run %s: %s", run_id, exc)
        raise HTTPException(
            status_code=502,
            detail="No se pudo reanudar el pedido. Reintentá en breve.",
        ) from exc

    content = getattr(final, "content", None)
    payload = content.model_dump() if hasattr(content, "model_dump") else str(content)
    return {
        "run_id": run_id,
        "session_id": req.session_id,
        "aprobado": req.aprobar,
        "resultado": payload,
    }
