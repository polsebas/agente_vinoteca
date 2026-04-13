"""
Tool SQL para consultar el estado actual de un pedido.

Invocar cuando el cliente pregunta por el estado de su compra o
cuando el agente necesita verificar si un pedido fue aprobado.
"""

from __future__ import annotations

from uuid import UUID

from agno.tools import tool
from pydantic import BaseModel

from storage.postgres import fetch_all, fetch_one


class OrderStatus(BaseModel):
    pedido_id: UUID
    estado: str
    total: float | None
    tipo_entrega: str | None
    lineas: list[dict]
    encontrado: bool


@tool
async def consultar_estado_pedido(pedido_id: str) -> OrderStatus:
    """
    Consulta el estado actual de un pedido por su ID.

    Usar cuando:
    - El cliente pregunta en qué estado está su pedido.
    - El agente necesita verificar si el pago fue procesado.
    - Verificar el resultado después de una aprobación HitL.
    """
    uid = UUID(pedido_id)
    pedido = await fetch_one(
        "SELECT id, estado, total, tipo_entrega FROM pedidos WHERE id = $1",
        uid,
    )

    if not pedido:
        return OrderStatus(
            pedido_id=uid,
            estado="no_encontrado",
            total=None,
            tipo_entrega=None,
            lineas=[],
            encontrado=False,
        )

    lineas_rows = await fetch_all(
        """
        SELECT lp.cantidad, lp.precio_unitario, lp.subtotal, v.nombre
        FROM lineas_pedido lp
        JOIN vinos v ON v.id = lp.vino_id
        WHERE lp.pedido_id = $1
        """,
        uid,
    )

    return OrderStatus(
        pedido_id=uid,
        estado=pedido["estado"],
        total=float(pedido["total"]) if pedido["total"] else None,
        tipo_entrega=pedido["tipo_entrega"],
        lineas=[
            {
                "nombre": r["nombre"],
                "cantidad": r["cantidad"],
                "precio_unitario": float(r["precio_unitario"]),
                "subtotal": float(r["subtotal"]),
            }
            for r in lineas_rows
        ],
        encontrado=True,
    )
