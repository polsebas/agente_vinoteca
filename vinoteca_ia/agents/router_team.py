"""Team router: delega al especialista usando `delegate_task_to_member`.

En Agno 2.5, `Team(mode="route")` clasifica y transfiere. La respuesta del
miembro sale al cliente sin re-pasar por el leader.
"""

from __future__ import annotations

from pathlib import Path

from agno.team import Team
from agno.team.mode import TeamMode

from agents.events_agent import get_events_agent
from agents.inventory_agent import get_inventory_agent
from agents.orders_agent import get_orders_agent
from agents.sommelier_agent import get_sommelier_agent
from agents.support_agent import get_support_agent
from core.model_provider import get_resilient_model
from storage.postgres import get_agno_db

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "router_team_leader_v1.md"


def _load_constitution() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def crear_router_team() -> Team:
    """Crea el Team router con los cinco especialistas.

    El leader opera a temperatura 0.0 y `tool_call_limit=1`: clasifica y
    transfiere. Los member_id son kebab-case (`agente-sommelier`, etc.).
    """
    primary, fallbacks = get_resilient_model(temperature=0.0)
    return Team(
        name="vinoteca_router",
        model=primary,
        fallback_models=fallbacks,
        mode=TeamMode.route,
        instructions=_load_constitution(),
        members=[
            get_sommelier_agent(),
            get_inventory_agent(),
            get_orders_agent(),
            get_events_agent(),
            get_support_agent(),
        ],
        tool_call_limit=1,
        db=get_agno_db(),
        add_team_history_to_members=True,
        num_team_history_runs=3,
        markdown=False,
    )
