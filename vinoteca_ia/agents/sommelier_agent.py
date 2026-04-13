"""
Agente Sumiller: recomendación personalizada con RAG + verificación SQL de stock.
Temperatura 0.7 para texto creativo, 0.0 para tools.
"""

from __future__ import annotations

import os

from agno.agent import Agent
from agno.models.anthropic import Claude

from tools.catalog.consult_stock import consultar_stock
from tools.catalog.search_by_occasion import buscar_por_ocasion
from tools.catalog.search_by_pairing import buscar_por_maridaje


def crear_agente_sumiller() -> Agent:
    constitution = _cargar_constitucion()

    return Agent(
        name="agente_sumiller",
        model=Claude(
            id=os.environ.get("LLM_PRIMARY", "claude-3-5-sonnet-20241022"),
            temperature=0.7,
        ),
        instructions=constitution,
        tools=[
            buscar_por_ocasion,
            buscar_por_maridaje,
            consultar_stock,
        ],
        show_tool_calls=True,
        markdown=True,
    )


def _cargar_constitucion() -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", "sommelier_v1.md")
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return (
            "Sos el sommelier virtual. Recomendás vinos personalizados. "
            "Siempre verificás stock antes de recomendar."
        )
