"""Capa cognitiva: factory functions de cada agente especialista + el Team router."""

from agents.auditor_agent import crear_agente_auditor
from agents.orders_agent import crear_agente_orders
from agents.router_team import crear_router_team
from agents.sommelier_agent import crear_agente_sommelier
from agents.support_agent import crear_agente_support

__all__ = [
    "crear_agente_auditor",
    "crear_agente_orders",
    "crear_agente_sommelier",
    "crear_agente_support",
    "crear_router_team",
]
