"""Consulta SQL del estado de un pedido (cabecera + líneas)."""

from __future__ import annotations

from decimal import Decimal

from agno.tools import tool

from schemas.order import OrderStatusLine, OrderStatusResponse, TipoEntrega
from storage.postgres import fetch_all, fetchrow


@tool
async def consultar_estado_pedido(pedido_id: str) -> OrderStatusResponse:
    """Consultar estado, total, tipo de entrega y líneas de un pedido.

    Usá esta tool cuando el cliente pregunta por su compra o después de HitL.
    """
    if not pedido_id.strip():
        return OrderStatusResponse(
            pedido_id=pedido_id,
            estado="no_encontrado",
            encontrado=False,
        )

    pedido = await fetchrow(
        """
        SELECT id, estado, total, tipo_entrega
        FROM pedidos
        WHERE id = $1
        """,
        pedido_id,
    )
    if not pedido:
        return OrderStatusResponse(
            pedido_id=pedido_id,
            estado="no_encontrado",
            encontrado=False,
        )

    lineas_rows = await fetch_all(
        """
        SELECT lp.cantidad, lp.precio_unitario, lp.subtotal,
               COALESCE(lp.nombre, v.nombre) AS nombre
        FROM pedido_lineas lp
        LEFT JOIN vinos v ON v.id = lp.producto_id
        WHERE lp.pedido_id = $1
        """,
        pedido_id,
    )
    tipo: TipoEntrega | None = None
    if pedido["tipo_entrega"]:
        try:
            tipo = TipoEntrega(pedido["tipo_entrega"])
        except ValueError:
            tipo = None

    total_raw = pedido["total"]
    return OrderStatusResponse(
        pedido_id=str(pedido["id"]),
        estado=pedido["estado"],
        total=Decimal(str(total_raw)) if total_raw is not None else None,
        tipo_entrega=tipo,
        lineas=[
            OrderStatusLine(
                nombre=r["nombre"] or "",
                cantidad=int(r["cantidad"]),
                precio_unitario=Decimal(str(r["precio_unitario"])),
                subtotal=Decimal(str(r["subtotal"])),
            )
            for r in lineas_rows
        ],
        encontrado=True,
    )
