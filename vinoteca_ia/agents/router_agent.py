"""
Agente Enrutador: clasifica la intención y deriva al especialista.
1 paso máximo. Temperatura 0.0. Confianza mínima 0.85.
"""

from __future__ import annotations

import os

from agno.agent import Agent
from agno.models.anthropic import Claude

from schemas.agent_io import RouterOutput


def crear_agente_router() -> Agent:
    constitution = _cargar_constitucion()

    return Agent(
        name="agente_router",
        model=Claude(
            id=os.environ.get("LLM_PRIMARY", "claude-3-5-sonnet-20241022"),
            temperature=0.0,
        ),
        instructions=constitution,
        response_model=RouterOutput,
        show_tool_calls=False,
        markdown=False,
    )


def _cargar_constitucion() -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", "router_v1.md")
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return (
            "Clasificá el mensaje en: recomendacion, maridaje, consulta_inventario, "
            "pedido, soporte, evento. Confianza mínima 0.85."
        )
