"""Inicialización de agentes Agno 2.5: constituciones, tools, T y output_schema."""

from __future__ import annotations

from pathlib import Path

from agno.agent import Agent

from agents.constitution import PROMPTS_DIR, load_constitution
from agents.events_agent import EVENTS_TEMPERATURE, get_events_agent
from agents.inventory_agent import INVENTORY_TEMPERATURE, get_inventory_agent
from agents.judge_agent import JUDGE_TEMPERATURE, get_judge_agent
from agents.orders_agent import ORDERS_TEMPERATURE, get_orders_agent
from agents.router_agent import ROUTER_TEMPERATURE, get_router_agent
from agents.sommelier_agent import SOMMELIER_TEMPERATURE, get_sommelier_agent
from agents.support_agent import SUPPORT_TEMPERATURE, get_support_agent
from schemas.agent_io import (
    EventsResponse,
    InventoryResponse,
    OrderResponse,
    RouterOutput,
    SommelierResponse,
    SupportResponse,
)
from schemas.judge_rubric import JudgeEvaluationResult

_FACTORIES = (
    get_router_agent,
    get_sommelier_agent,
    get_orders_agent,
    get_inventory_agent,
    get_support_agent,
    get_events_agent,
    get_judge_agent,
)

_PROMPT_FILES = (
    "router_v1.md",
    "sommelier_v1.md",
    "orders_v1.md",
    "inventory_v1.md",
    "support_v1.md",
    "events_v1.md",
    "judge_v1.md",
    "enricher_v1.md",
)


def _tool_names(agent: Agent) -> set[str]:
    return {t.name for t in (agent.tools or [])}


def test_siete_factories_devuelven_agent():
    for factory in _FACTORIES:
        agent = factory()
        assert isinstance(agent, Agent)
        assert agent.name.startswith("agente_")
        assert isinstance(agent.instructions, str)
        assert agent.instructions.strip()
        assert agent.description


def test_constituciones_no_vacias():
    for filename in _PROMPT_FILES:
        text = load_constitution(filename)
        assert len(text) > 80, filename
        assert (PROMPTS_DIR / filename).exists()
        assert Path(PROMPTS_DIR / filename).read_text(encoding="utf-8").strip() == text


def test_router_contrato_y_temperatura():
    agent = get_router_agent()
    assert agent.output_schema is RouterOutput
    assert agent.model.temperature == ROUTER_TEMPERATURE == 0.0
    assert _tool_names(agent) == set()


def test_sommelier_tools_privilegio_minimo_y_t07():
    agent = get_sommelier_agent()
    assert agent.output_schema is SommelierResponse
    assert agent.model.temperature == SOMMELIER_TEMPERATURE == 0.7
    assert _tool_names(agent) == {
        "consultar_stock",
        "buscar_por_maridaje",
        "buscar_por_ocasion",
        "guardar_preferencia",
    }


def test_orders_2pc_tools_y_t00():
    agent = get_orders_agent()
    assert agent.output_schema is OrderResponse
    assert agent.model.temperature == ORDERS_TEMPERATURE == 0.0
    assert _tool_names(agent) == {
        "verificar_stock_exacto",
        "calcular_orden",
        "crear_orden",
        "enviar_link_pago",
        "consultar_estado_pedido",
    }


def test_inventory_sql_tools_y_t00():
    agent = get_inventory_agent()
    assert agent.output_schema is InventoryResponse
    assert agent.model.temperature == INVENTORY_TEMPERATURE == 0.0
    assert _tool_names(agent) == {
        "consultar_stock",
        "consultar_precio",
        "comparar_anadas",
        "consultar_zona_entrega",
    }


def test_support_tools_y_t04():
    agent = get_support_agent()
    assert agent.output_schema is SupportResponse
    assert agent.model.temperature == SUPPORT_TEMPERATURE == 0.4
    assert _tool_names(agent) == {
        "escalar_a_humano",
        "buscar_faq",
        "registrar_reclamo",
    }


def test_events_tools_y_t00():
    agent = get_events_agent()
    assert agent.output_schema is EventsResponse
    assert agent.model.temperature == EVENTS_TEMPERATURE == 0.0
    assert _tool_names(agent) == {"consultar_eventos", "reservar_evento"}


def test_judge_sin_tools_rubrica_y_t00():
    agent = get_judge_agent()
    assert agent.output_schema is JudgeEvaluationResult
    assert agent.model.temperature == JUDGE_TEMPERATURE == 0.0
    assert _tool_names(agent) == set()


def test_factory_acepta_modelo_inyectado():
    from agno.models.openai import OpenAIChat

    custom = OpenAIChat(id="gpt-4o-mini", temperature=0.0)
    agent = get_router_agent(model=custom)
    assert agent.model is custom
