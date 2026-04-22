"""Agente Router: clasifica intención y deriva (sin Team).

Este agente emite un `RouterOutput` estructurado. En la topología real del
sistema, el **ruteo efectivo** lo hace el Team (ver `router_team.py`) con
`mode="route"`, que delega al especialista y devuelve su respuesta
directamente al cliente, cumpliendo el patrón `transfer_task` de Agno.

Este archivo expone además un agente router "puro" (solo clasifica, sin
delegar) para debug, auditoría y pipelines offline que no levantan el Team.
"""

from __future__ import annotations

from pathlib import Path

from agno.agent import Agent

from core.model_provider import get_resilient_model
from schemas.agent_io import RouterOutput

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "router_v1.md"


def _load_constitution() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def crear_agente_router() -> Agent:
    """Construye el agente Router "puro" (solo clasifica, no delega)."""
    primary, fallbacks = get_resilient_model(temperature=0.0)
    return Agent(
        name="agente_router",
        model=primary,
        fallback_models=fallbacks,
        instructions=_load_constitution(),
        output_schema=RouterOutput,
        tool_call_limit=1,
        markdown=False,
    )
