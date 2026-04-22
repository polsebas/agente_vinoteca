"""Agente Sommelier: recomendación de vinos con RAG + SQL.

Patrón ReAct: invoca tools hasta llegar a una recomendación concreta.
- Precios y stock → SQL (tools catalog/consult_*).
- Maridajes y ocasiones → RAG (tools catalog/search_*).
- Memoria del cliente → PostgresDb compartido + tools customer.
"""

from __future__ import annotations

from pathlib import Path

from agno.agent import Agent

from core.model_provider import get_resilient_model
from schemas.agent_io import SommelierResponse
from storage.postgres import get_agno_db
from tools.catalog.consult_price import consultar_precio
from tools.catalog.consult_stock import consultar_stock
from tools.catalog.search_by_occasion import buscar_por_ocasion
from tools.catalog.search_by_pairing import buscar_por_maridaje
from tools.customer.load_context import cargar_contexto_cliente
from tools.customer.save_preference import guardar_preferencia

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "sommelier_v1.md"


def _load_constitution() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def crear_agente_sommelier() -> Agent:
    """Construye una instancia nueva del Sommelier.

    Stateless respecto al agente: la persistencia corre por cuenta del `db`
    de Agno (Postgres) indexado por `session_id` en runtime.
    """
    primary, fallbacks = get_resilient_model(temperature=0.0)
    return Agent(
        name="agente_sommelier",
        model=primary,
        fallback_models=fallbacks,
        instructions=_load_constitution(),
        tools=[
            cargar_contexto_cliente,
            buscar_por_maridaje,
            buscar_por_ocasion,
            consultar_stock,
            consultar_precio,
            guardar_preferencia,
        ],
        output_schema=SommelierResponse,
        tool_call_limit=7,
        db=get_agno_db(),
        add_history_to_context=True,
        num_history_runs=5,
        markdown=False,
    )
