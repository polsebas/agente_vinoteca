"""Agente de Soporte: FAQ, reclamos y escalada humana.

Patrón ReAct con fallback agresivo: si dos tools consecutivas fallan,
la constitución instruye escalar a humano automáticamente. El
`tool_call_limit=4` es el circuit breaker final.
"""

from __future__ import annotations

from pathlib import Path

from agno.agent import Agent

from core.model_provider import get_resilient_model
from schemas.agent_io import SupportResponse
from storage.postgres import get_agno_db
from tools.support.escalate_to_human import escalar_a_humano
from tools.support.register_complaint import registrar_reclamo
from tools.support.search_faq import buscar_faq

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "support_v1.md"


def _load_constitution() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def crear_agente_support() -> Agent:
    """Construye una instancia nueva del Support agent."""
    primary, fallbacks = get_resilient_model(temperature=0.0)
    return Agent(
        name="agente_support",
        model=primary,
        fallback_models=fallbacks,
        instructions=_load_constitution(),
        tools=[
            buscar_faq,
            registrar_reclamo,
            escalar_a_humano,
        ],
        output_schema=SupportResponse,
        tool_call_limit=4,
        db=get_agno_db(),
        add_history_to_context=True,
        num_history_runs=4,
        markdown=False,
    )
