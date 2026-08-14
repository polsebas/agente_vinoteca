"""Agente de Inventario: precio, stock, añadas y zona de entrega (SQL, T=0.0)."""

from __future__ import annotations

from agno.agent import Agent
from agno.models.base import Model

from agents.constitution import make_agent
from schemas.agent_io import InventoryResponse
from storage.postgres import get_agno_db
from tools.catalog.compare_vintages import comparar_anadas
from tools.catalog.consult_price import consultar_precio
from tools.catalog.consult_stock import consultar_stock
from tools.customer.consult_delivery_zone import consultar_zona_entrega

INVENTORY_TEMPERATURE = 0.0
INVENTORY_TOOLS = [
    consultar_stock,
    consultar_precio,
    comparar_anadas,
    consultar_zona_entrega,
]


def get_inventory_agent(model: Model | None = None) -> Agent:
    """Factory Agno 2.5: inventario determinista, sin RAG."""
    return make_agent(
        name="agente_inventario",
        description="Consulta SQL de stock, precio, añadas y zona de entrega.",
        prompt_file="inventory_v1.md",
        temperature=INVENTORY_TEMPERATURE,
        model=model,
        tools=INVENTORY_TOOLS,
        output_schema=InventoryResponse,
        tool_call_limit=3,
        db=get_agno_db(),
        add_history_to_context=True,
        num_history_runs=3,
    )


crear_agente_inventario = get_inventory_agent
