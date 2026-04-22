"""Agente de Pedidos: Two-Phase Commit con human-in-the-loop.

El patrón de pausa-reanudación se implementa con:
- `requires_confirmation=True` en las tools `crear_orden` y `enviar_link_pago`
  (definido en las propias tools).
- `acontinue_run()` del agente, invocado desde el endpoint `/aprobar` con
  las ToolExecutions marcadas como aprobadas.

El prompt (`orders_v1.md`) garantiza el orden correcto: stock → cálculo →
resumen → pausa → crear → link.
"""

from __future__ import annotations

from pathlib import Path

from agno.agent import Agent

from core.model_provider import get_resilient_model
from schemas.agent_io import OrderResponse
from storage.postgres import get_agno_db
from tools.orders.calculate_order import calcular_orden
from tools.orders.create_order import crear_orden
from tools.orders.send_payment_link import enviar_link_pago
from tools.orders.verify_stock_exact import verificar_stock_exacto

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "orders_v1.md"


def _load_constitution() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def crear_agente_orders() -> Agent:
    """Construye una instancia nueva del Orders agent.

    Las tools `crear_orden` y `enviar_link_pago` ya vienen con
    `requires_confirmation=True`: el framework Agno pausa el run antes de
    ejecutarlas y emite un evento de pausa. El endpoint `/pedido/{id}/aprobar`
    se encarga de reanudar con `acontinue_run()` pasando la aprobación.
    """
    primary, fallbacks = get_resilient_model(temperature=0.0)
    return Agent(
        name="agente_orders",
        model=primary,
        fallback_models=fallbacks,
        instructions=_load_constitution(),
        tools=[
            verificar_stock_exacto,
            calcular_orden,
            crear_orden,
            enviar_link_pago,
        ],
        output_schema=OrderResponse,
        tool_call_limit=5,
        db=get_agno_db(),
        add_history_to_context=True,
        num_history_runs=3,
        markdown=False,
    )
