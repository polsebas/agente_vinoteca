"""Agente de Pedidos: Two-Phase Commit con human-in-the-loop (T=0.0)."""

from __future__ import annotations

from agno.agent import Agent
from agno.models.base import Model

from agents.constitution import make_agent
from core.idempotency import IdempotencyManager
from schemas.agent_io import OrderResponse
from storage.postgres import get_agno_db
from tools.orders.calculate_order import calcular_orden
from tools.orders.check_order_status import consultar_estado_pedido
from tools.orders.create_order import crear_orden
from tools.orders.send_payment_link import enviar_link_pago
from tools.orders.verify_stock_exact import verificar_stock_exacto

ORDERS_TEMPERATURE = 0.0
ORDERS_TOOLS = [
    verificar_stock_exacto,
    calcular_orden,
    crear_orden,
    enviar_link_pago,
    consultar_estado_pedido,
]


def generar_idempotency_key(session_id: str) -> str:
    """Clave de un solo uso por sesión para operaciones de pedido."""
    digest = IdempotencyManager.build_key("orden", session_id)
    return f"ord_{session_id}_{digest.split(':', 1)[-1][:12]}"


def get_orders_agent(model: Model | None = None) -> Agent:
    """Factory Agno 2.5: Orders 2PC. `crear_orden`/`enviar_link_pago` piden HitL."""
    return make_agent(
        name="agente_orders",
        description="Ejecuta el Two-Phase Commit de pedidos y el link de pago.",
        prompt_file="orders_v1.md",
        temperature=ORDERS_TEMPERATURE,
        model=model,
        tools=ORDERS_TOOLS,
        output_schema=OrderResponse,
        tool_call_limit=5,
        db=get_agno_db(),
        add_history_to_context=True,
        num_history_runs=3,
    )


crear_agente_orders = get_orders_agent
