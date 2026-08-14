"""Agente Router: clasifica intención y emite `RouterOutput` (sin Team).

El ruteo productivo lo hace el Team (`router_team.py`). Este agente puro
sirve para debug, auditoría y el orquestador PRAO.
"""

from __future__ import annotations

from agno.agent import Agent
from agno.models.base import Model

from agents.constitution import make_agent
from schemas.agent_io import RouterOutput

ROUTER_TEMPERATURE = 0.0


def get_router_agent(model: Model | None = None) -> Agent:
    """Factory Agno 2.5: Router a T=0.0 con `output_schema=RouterOutput`."""
    return make_agent(
        name="agente_router",
        description="Clasifica la intención del cliente en clases cerradas y deriva.",
        prompt_file="router_v1.md",
        temperature=ROUTER_TEMPERATURE,
        model=model,
        output_schema=RouterOutput,
        tool_call_limit=1,
    )


crear_agente_router = get_router_agent
