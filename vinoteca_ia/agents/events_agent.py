"""Agente de Eventos: agenda de catas y reserva atómica de cupo (T=0.0)."""

from __future__ import annotations

from agno.agent import Agent
from agno.models.base import Model

from agents.constitution import make_agent
from schemas.agent_io import EventsResponse
from storage.postgres import get_agno_db
from tools.events.consult_events import consultar_eventos
from tools.events.reserve_event import reservar_evento

EVENTS_TEMPERATURE = 0.0
EVENTS_TOOLS = [
    consultar_eventos,
    reservar_evento,
]


def get_events_agent(model: Model | None = None) -> Agent:
    """Factory Agno 2.5: eventos y cupos vía SQL."""
    return make_agent(
        name="agente_events",
        description="Lista catas y reserva asientos con control de cupo.",
        prompt_file="events_v1.md",
        temperature=EVENTS_TEMPERATURE,
        model=model,
        tools=EVENTS_TOOLS,
        output_schema=EventsResponse,
        tool_call_limit=4,
        db=get_agno_db(),
        add_history_to_context=True,
        num_history_runs=3,
    )


crear_agente_events = get_events_agent
