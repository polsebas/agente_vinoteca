"""Team router: delega al especialista usando el mecanismo `transfer_task`.

En Agno 2.5, `Team(mode="route", ...)` implementa el patrón de "router agent"
donde el leader clasifica la intención y transfiere el turno al miembro
apropiado vía la tool nativa `transfer_task_to_member`. La respuesta del
miembro se devuelve al cliente sin pasar de nuevo por el leader.

Esta es la topología *productiva* — lo que el endpoint `/chat` invoca.
"""

from __future__ import annotations

from pathlib import Path

from agno.team import Team
from agno.team.mode import TeamMode

from agents.orders_agent import crear_agente_orders
from agents.sommelier_agent import crear_agente_sommelier
from agents.support_agent import crear_agente_support
from core.model_provider import get_resilient_model
from storage.postgres import get_agno_db

# No usar `router_v1.md` acá: ese contrato pide JSON RouterOutput y el stream
# del `/chat` lo exponía al cliente. El líder en modo route debe delegar con
# `delegate_task_to_member` (ver prompts/router_team_leader_v1.md).
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "router_team_leader_v1.md"


def _load_constitution() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def crear_router_team() -> Team:
    """Crea el Team router con Sommelier, Orders y Support como miembros.

    El leader opera a temperatura 0.0 y tiene un `tool_call_limit=1`: clasifica
    y transfiere, no itera. La respuesta del miembro sale directo al cliente.

    Los member_id que espera delegate_task_to_member son URL-safe (kebab-case),
    p. ej. 'agente-sommelier' (ver agno.utils.team.get_member_id).
    """
    primary, fallbacks = get_resilient_model(temperature=0.0)
    return Team(
        name="vinoteca_router",
        model=primary,
        fallback_models=fallbacks,
        mode=TeamMode.route,
        instructions=_load_constitution(),
        members=[
            crear_agente_sommelier(),
            crear_agente_orders(),
            crear_agente_support(),
        ],
        tool_call_limit=1,
        db=get_agno_db(),
        add_team_history_to_members=True,
        num_team_history_runs=3,
        markdown=False,
    )
