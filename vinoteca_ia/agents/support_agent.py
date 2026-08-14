"""Agente de Soporte: FAQ, reclamos y escalada humana (T=0.4)."""

from __future__ import annotations

from agno.agent import Agent
from agno.models.base import Model

from agents.constitution import make_agent
from schemas.agent_io import SupportResponse
from storage.postgres import get_agno_db
from tools.support.escalate_to_human import escalar_a_humano
from tools.support.register_complaint import registrar_reclamo
from tools.support.search_faq import buscar_faq

SUPPORT_TEMPERATURE = 0.4
SUPPORT_TOOLS = [
    escalar_a_humano,
    buscar_faq,
    registrar_reclamo,
]


def get_support_agent(model: Model | None = None) -> Agent:
    """Factory Agno 2.5: soporte empático con circuit breaker de 4 tools."""
    return make_agent(
        name="agente_support",
        description="Resuelve FAQ, registra reclamos y escala a un operador.",
        prompt_file="support_v1.md",
        temperature=SUPPORT_TEMPERATURE,
        model=model,
        tools=SUPPORT_TOOLS,
        output_schema=SupportResponse,
        tool_call_limit=4,
        db=get_agno_db(),
        add_history_to_context=True,
        num_history_runs=4,
    )


crear_agente_support = get_support_agent
