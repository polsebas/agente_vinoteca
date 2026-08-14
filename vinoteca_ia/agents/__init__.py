"""Capa cognitiva: factory functions de cada agente especialista + el Team router."""

from agents.auditor_agent import crear_agente_auditor
from agents.events_agent import crear_agente_events, get_events_agent
from agents.inventory_agent import crear_agente_inventario, get_inventory_agent
from agents.judge_agent import crear_agente_judge, get_judge_agent
from agents.orders_agent import crear_agente_orders, get_orders_agent
from agents.router_agent import crear_agente_router, get_router_agent
from agents.router_team import crear_router_team
from agents.sommelier_agent import crear_agente_sommelier, get_sommelier_agent
from agents.support_agent import crear_agente_support, get_support_agent

__all__ = [
    "crear_agente_auditor",
    "crear_agente_events",
    "crear_agente_inventario",
    "crear_agente_judge",
    "crear_agente_orders",
    "crear_agente_router",
    "crear_agente_sommelier",
    "crear_agente_support",
    "crear_router_team",
    "get_events_agent",
    "get_inventory_agent",
    "get_judge_agent",
    "get_orders_agent",
    "get_router_agent",
    "get_sommelier_agent",
    "get_support_agent",
]
