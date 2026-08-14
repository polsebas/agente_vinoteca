"""Cálculo determinista de totales (Fase 1 del 2PC). No muta la DB."""

from __future__ import annotations

from decimal import Decimal

from agno.tools import tool

from schemas.order import CalculatedOrder, LineaPedidoSolicitud, OrderLineItem, TipoEntrega
from schemas.tool_responses import CalculatedOrderResponse, ResultadoTool
from storage.postgres import fetch_all

COSTO_ENVIO = Decimal("2500.00")
UMBRAL_ENVIO_GRATIS = Decimal("30000.00")
DESCUENTO_6 = Decimal("0.05")
DESCUENTO_12 = Decimal("0.10")

# Alias histórico.
CalculationResponse = CalculatedOrderResponse


def _parse_lineas(lineas: list) -> list[LineaPedidoSolicitud] | str:
    if not lineas:
        return "Debe proveer al menos una línea."
    try:
        parsed: list[LineaPedidoSolicitud] = []
        for line in lineas:
            if isinstance(line, LineaPedidoSolicitud):
                parsed.append(line)
            else:
                parsed.append(LineaPedidoSolicitud.model_validate(line))
        return parsed
    except (KeyError, ValueError, TypeError) as exc:
        return f"Líneas mal formadas: {exc}"


def _descuento_volumen(botellas: int, subtotal: Decimal) -> Decimal:
    if botellas >= 12:
        return (subtotal * DESCUENTO_12).quantize(Decimal("0.01"))
    if botellas >= 6:
        return (subtotal * DESCUENTO_6).quantize(Decimal("0.01"))
    return Decimal("0.00")


@tool
async def calcular_orden(
    lineas: list[LineaPedidoSolicitud],
    tipo_entrega: TipoEntrega = TipoEntrega.ENVIO_DOMICILIO,
    codigo_postal: str | None = None,
    costo_envio_ars: float | None = None,
) -> CalculatedOrderResponse:
    """Calcular subtotal, descuento por volumen y envío con precios SQL.

    Segundo paso del 2PC, después de `verificar_stock_exacto`. NUNCA dejes
    que el LLM sume. Envío gratis si el subtotal (post-descuento) supera
    $30.000 ARS. Retiro en local = envío $0.

    Args:
        lineas: `producto_id`/`vino_id` + `cantidad`.
        tipo_entrega: domicilio o retiro.
        codigo_postal: usado solo para trazar zona; el costo lo define umbral/retiro.
        costo_envio_ars: override explícito (se ignora en retiro o envío gratis).
    """
    parsed = _parse_lineas(lineas)
    if isinstance(parsed, str):
        return CalculatedOrderResponse(resultado=ResultadoTool.ERROR, mensaje=parsed)

    requested: dict[str, int] = {}
    for sol in parsed:
        requested[sol.producto_id] = requested.get(sol.producto_id, 0) + sol.cantidad

    ids = list(requested.keys())
    placeholders = ", ".join(f"${i + 1}" for i in range(len(ids)))
    rows = await fetch_all(
        f"""
        SELECT id::text AS id, nombre, precio, activo
        FROM vinos
        WHERE id IN ({placeholders})
        """,
        *ids,
    )
    por_id = {str(r["id"]): r for r in rows}

    lineas_calc: list[OrderLineItem] = []
    subtotal = Decimal("0")
    botellas = 0
    for pid, cantidad in requested.items():
        row = por_id.get(pid)
        if row is None or not row["activo"]:
            return CalculatedOrderResponse(
                resultado=ResultadoTool.ERROR,
                mensaje=f"Producto {pid} inexistente o inactivo.",
            )
        precio = row["precio"]
        if precio is None or Decimal(str(precio)) <= 0:
            return CalculatedOrderResponse(
                resultado=ResultadoTool.ERROR,
                mensaje=f"Precio inválido para {pid}.",
            )
        precio_u = Decimal(str(precio)).quantize(Decimal("0.01"))
        sub = (precio_u * Decimal(cantidad)).quantize(Decimal("0.01"))
        subtotal += sub
        botellas += cantidad
        lineas_calc.append(
            OrderLineItem(
                producto_id=pid,
                nombre=row["nombre"] or pid,
                cantidad=cantidad,
                precio_unitario=precio_u,
                subtotal=sub,
            )
        )

    descuento = _descuento_volumen(botellas, subtotal)
    base_envio = subtotal - descuento
    if tipo_entrega == TipoEntrega.RETIRO_LOCAL or base_envio >= UMBRAL_ENVIO_GRATIS:
        envio = Decimal("0.00")
    elif costo_envio_ars is not None:
        envio = Decimal(str(costo_envio_ars)).quantize(Decimal("0.01"))
    else:
        envio = COSTO_ENVIO

    total = (base_envio + envio).quantize(Decimal("0.01"))
    order = CalculatedOrder(
        lineas=lineas_calc,
        subtotal=subtotal.quantize(Decimal("0.01")),
        descuento=descuento,
        costo_envio=envio,
        total=total,
        tipo_entrega=tipo_entrega,
        requiere_confirmacion=True,
    )
    _ = codigo_postal  # zona se evalúa en consultar_zona_entrega
    return CalculatedOrderResponse(resultado=ResultadoTool.OK, order=order)


calcular_pedido = calcular_orden
