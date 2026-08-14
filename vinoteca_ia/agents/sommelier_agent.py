"""Agente Sommelier: recomendación narrativa (T=0.7) anclada a tools."""

from __future__ import annotations

from agno.agent import Agent
from agno.models.base import Model

from agents.constitution import make_agent
from schemas.agent_io import SommelierResponse
from storage.postgres import get_agno_db
from tools.catalog.consult_stock import consultar_stock
from tools.catalog.search_by_occasion import buscar_por_ocasion
from tools.catalog.search_by_pairing import buscar_por_maridaje
from tools.customer.save_preference import guardar_preferencia

SOMMELIER_TEMPERATURE = 0.7
SOMMELIER_TOOLS = [
    consultar_stock,
    buscar_por_maridaje,
    buscar_por_ocasion,
    guardar_preferencia,
]


def get_sommelier_agent(model: Model | None = None) -> Agent:
    """Factory Agno 2.5: Sommelier con RAG cualitativo + stock SQL."""
    return make_agent(
        name="agente_sommelier",
        description="Recomienda vinos por ocasión, regalo y maridaje.",
        prompt_file="sommelier_v1.md",
        temperature=SOMMELIER_TEMPERATURE,
        model=model,
        tools=SOMMELIER_TOOLS,
        output_schema=SommelierResponse,
        tool_call_limit=7,
        db=get_agno_db(),
        add_history_to_context=True,
        num_history_runs=5,
    )


crear_agente_sommelier = get_sommelier_agent
