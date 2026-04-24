"""
Agente de Inventario: consultas exactas de stock y precio via SQL exclusivamente.
Temperatura 0.0. Sin RAG. Sin creatividad.
"""

from __future__ import annotations

import os

from agno.agent import Agent

from core.model_provider import get_resilient_model
from tools.catalog.consult_price import consultar_precio
from tools.catalog.consult_stock import consultar_stock


def crear_agente_inventario() -> Agent:
    constitution = _cargar_constitucion()
    primary, fallbacks = get_resilient_model(temperature=0.0)

    return Agent(
        name="agente_inventario",
        model=primary,
        fallback_models=fallbacks,
        instructions=constitution,
        tools=[consultar_stock, consultar_precio],
        show_tool_calls=True,
        markdown=False,
    )


def _cargar_constitucion() -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", "inventory_v1.md")
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return "Sos el agente de inventario. Solo usás SQL para consultar precios y stock."
