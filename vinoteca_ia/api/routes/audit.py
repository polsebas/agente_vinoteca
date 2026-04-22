"""Endpoint admin para disparar la auditoría on-demand.

En producción el disparo principal es el job nocturno (`jobs/nightly_audit.py`
vía cron o el scheduler de AgentOS). Este endpoint es útil para:
- Debug en staging.
- Re-auditar una ventana tras un incidente.
- Testing de integración del agente juez.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import admin_rate_limiter, require_admin_token
from jobs.nightly_audit import correr_auditor
from schemas.audit import AuditReport

router = APIRouter(tags=["admin"])


class AuditRequest(BaseModel):
    """Parámetros del disparo manual."""

    horas_atras: int = Field(default=24, ge=1, le=168)


@router.post(
    "/admin/auditor/run",
    response_model=AuditReport,
    dependencies=[Depends(require_admin_token), Depends(admin_rate_limiter)],
)
async def disparar_auditor(req: AuditRequest) -> AuditReport:
    """Disparar la corrida del Auditor manualmente (requiere token admin)."""
    return await correr_auditor(horas_atras=req.horas_atras)
