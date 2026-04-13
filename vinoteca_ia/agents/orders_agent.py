"""
Agente de Pedidos: Two-Phase Commit con pausa HitL en Fase 1.
Temperatura 0.0. Máxima precisión transaccional.
"""

from __future__ import annotations

import os
import time
import uuid

from agno.agent import Agent
from agno.models.anthropic import Claude

from schemas.order import OrderEstado, OrderResumen
from storage.immutable_log import registrar
from storage.postgres import execute, fetch_one
from tools.orders.calculate_order import calcular_pedido
from tools.orders.check_order_status import consultar_estado_pedido
from tools.orders.create_order import crear_pedido
from tools.orders.send_payment_link import enviar_link_pago
from tools.orders.verify_stock_exact import verificar_stock_exacto


def crear_agente_pedidos() -> Agent:
    constitution = _cargar_constitucion()

    return Agent(
        name="agente_pedidos",
        model=Claude(
            id=os.environ.get("LLM_PRIMARY", "claude-3-5-sonnet-20241022"),
            temperature=0.0,
        ),
        instructions=constitution,
        tools=[
            verificar_stock_exacto,
            calcular_pedido,
            consultar_estado_pedido,
        ],
        show_tool_calls=True,
        markdown=False,
    )


def generar_idempotency_key(session_id: str) -> str:
    ts = int(time.time() * 1000)
    return f"ord_{session_id}_{ts}"


async def ejecutar_fase_1(
    session_id: str,
    items: list[dict],
    tipo_entrega: str = "retiro",
    correlation_id: str = "",
) -> dict:
    """
    Fase 1 del Two-Phase Commit: verifica stock, calcula total, persiste
    pedido en estado 'pendiente_aprobacion' y retorna el resumen al cliente.
    NO muta stock ni cobra.
    """
    idempotency_key = generar_idempotency_key(session_id)

    verificacion = await verificar_stock_exacto.entrypoint(items)
    if not verificacion.todo_disponible:
        return {
            "fase": 1,
            "ok": False,
            "mensaje": verificacion.mensaje,
            "faltantes": verificacion.faltantes,
        }

    calculo = await calcular_pedido.entrypoint(items, tipo_entrega)

    pedido_id = await execute(
        """
        INSERT INTO pedidos (session_id, estado, tipo_entrega, subtotal, total, idempotency_key)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        session_id,
        OrderEstado.PENDIENTE_APROBACION,
        tipo_entrega,
        calculo.subtotal,
        calculo.total,
        idempotency_key,
    )

    await registrar(
        "pedido_fase1_iniciado",
        session_id=session_id,
        correlation_id=correlation_id,
        payload={
            "idempotency_key": idempotency_key,
            "total": calculo.total,
            "items": items,
        },
    )

    lineas_texto = "\n".join(
        f"  • {l['nombre']} x{l['cantidad']} — ${l['precio_unitario']:,.2f}"
        for l in calculo.lineas
    )

    mensaje = (
        f"Tu pedido:\n{lineas_texto}\n\n"
        f"Subtotal: ${calculo.subtotal:,.2f}\n"
        f"{'Envío: $' + str(int(calculo.envio)) if calculo.envio > 0 else 'Retiro sin costo'}\n"
        f"**Total: ${calculo.total:,.2f}**\n\n"
        f"¿Confirmás este pedido? Hacé clic en el botón de confirmación."
    )

    return {
        "fase": 1,
        "ok": True,
        "pedido_id": str(pedido_id) if isinstance(pedido_id, str) else str(pedido_id),
        "idempotency_key": idempotency_key,
        "resumen": calculo.model_dump(),
        "mensaje": mensaje,
        "requiere_aprobacion": True,
    }


async def ejecutar_fase_2(pedido_id: str, idempotency_key: str, session_id: str) -> dict:
    """
    Fase 2: ejecutada solo desde POST /aprobar. Crea el pedido definitivo
    y genera el link de pago.
    """
    pedido = await fetch_one(
        "SELECT id, estado, total, session_id FROM pedidos WHERE id = $1::uuid",
        pedido_id,
    )

    if not pedido or pedido["estado"] != OrderEstado.PENDIENTE_APROBACION:
        return {"ok": False, "mensaje": "Pedido no encontrado o ya procesado."}

    lineas_rows = await fetch_one(
        "SELECT session_id FROM pedidos WHERE id = $1::uuid",
        pedido_id,
    )

    items_rows = await execute(
        "SELECT vino_id, cantidad FROM lineas_pedido WHERE pedido_id = $1::uuid RETURNING *",
        pedido_id,
    )

    resultado = await crear_pedido.entrypoint(
        session_id=pedido["session_id"],
        idempotency_key=idempotency_key,
        items=[],
        tipo_entrega=pedido.get("tipo_entrega", "retiro"),
    )

    link = await enviar_link_pago.entrypoint(
        pedido_id=str(resultado.pedido_id),
        total=float(pedido["total"]),
    )

    return {
        "ok": True,
        "pedido_id": str(resultado.pedido_id),
        "total": resultado.total,
        "url_pago": link.url_pago,
        "mensaje": f"Pedido confirmado. Tu link de pago: {link.url_pago}",
    }


def _cargar_constitucion() -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", "orders_v1.md")
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return "Sos el agente de pedidos. Usás Two-Phase Commit. Temperatura 0.0."
