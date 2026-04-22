"""Auditor nocturno: LLM-as-a-Judge sobre los runs de las últimas N horas.

No es un agente conversacional: se ejecuta por un job/scheduler (ver
`jobs/nightly_audit.py`). Tiene su propio `db` compartido (mismo
`PostgresDb`) para que los hallazgos queden ligados a los mismos session_id
que el resto del sistema.
"""

from __future__ import annotations

from pathlib import Path

from agno.agent import Agent

from core.model_provider import get_resilient_model
from schemas.audit import AuditReport
from storage.postgres import get_agno_db
from tools.audit.fetch_runs import listar_runs_auditables
from tools.audit.save_finding import guardar_hallazgo

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "auditor_v1.md"


def _load_constitution() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def crear_agente_auditor() -> Agent:
    """Construye el agente Auditor con sus dos tools.

    - `tool_call_limit=20` porque puede procesar batches grandes.
    - `temperature=0.0`: juez determinista.
    - `output_schema=AuditReport`: el agente devuelve el reporte tipado al
      finalizar; los hallazgos individuales ya se persistieron vía
      `guardar_hallazgo`.
    """
    primary, fallbacks = get_resilient_model(temperature=0.0)
    return Agent(
        name="agente_auditor",
        model=primary,
        fallback_models=fallbacks,
        instructions=_load_constitution(),
        tools=[
            listar_runs_auditables,
            guardar_hallazgo,
        ],
        output_schema=AuditReport,
        tool_call_limit=20,
        db=get_agno_db(),
        markdown=False,
    )
