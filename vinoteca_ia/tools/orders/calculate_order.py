"""Cálculo determinista de totales (sin LLM)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from agno.tools import tool

from schemas.tool_responses import CalculationResponse, ResultadoTool
from storage.postgres import fetch_all


@tool
async def calcular_orden(
    lineas: list[dict[str, str | int]],
    costo_envio_ars: float = 0.0,
) -> CalculationResponse:
    """Calcular subtotal, envío y total de un pedido usando precios actuales de SQL.

    Usá esta tool como segundo paso del armado de un pedido, después de
    `verificar_stock_exacto` y antes de `crear_orden`. El cálculo es puramente
    aritmético: NUNCA dejes que el LLM sume precios por su cuenta.

    Los precios se toman autoritativamente de la tabla `vinos`: si cambiaron
    entre el momento de la recomendación y el armado, el total se recalcula
    con los vigentes.

    Args:
        lineas: Lista de `{"vino_id": "<uuid>", "cantidad": <int>}`.
        costo_envio_ars: Costo de envío a agregar al subtotal.

    Returns:
        CalculationResponse con `subtotal_ars`, `envio_ars`, `total_ars`.
    """
    if not lineas:
        return CalculationResponse(
            resultado=ResultadoTool.ERROR,
            subtotal_ars=Decimal("0"),
            envio_ars=Decimal("0"),
            total_ars=Decimal("0"),
            mensaje="Debe proveer al menos una línea.",
        )

    try:
        requested: dict[UUID, int] = {
            UUID(str(line["vino_id"])): int(line["cantidad"])
            for line in lineas
        }
    except (KeyError, ValueError) as exc:
        return CalculationResponse(
            resultado=ResultadoTool.ERROR,
            subtotal_ars=Decimal("0"),
            envio_ars=Decimal("0"),
            total_ars=Decimal("0"),
            mensaje=f"Líneas mal formadas: {exc}",
        )

    placeholders = ", ".join(f"${i + 1}" for i in range(len(requested)))
    rows = await fetch_all(
        f"""
        SELECT id, precio_ars
        FROM vinos
        WHERE id IN ({placeholders}) AND activo = TRUE
        """,
        *requested.keys(),
    )

    precios: dict[UUID, Decimal] = {row["id"]: row["precio_ars"] for row in rows}
    if len(precios) != len(requested):
        return CalculationResponse(
            resultado=ResultadoTool.ERROR,
            subtotal_ars=Decimal("0"),
            envio_ars=Decimal("0"),
            total_ars=Decimal("0"),
            mensaje="Uno o más vinos no existen o están inactivos.",
        )

    subtotal = sum(
        (precios[vid] * Decimal(cantidad) for vid, cantidad in requested.items()),
        start=Decimal("0"),
    )
    envio = Decimal(str(costo_envio_ars))
    total = subtotal + envio

    return CalculationResponse(
        resultado=ResultadoTool.OK,
        subtotal_ars=subtotal.quantize(Decimal("0.01")),
        envio_ars=envio.quantize(Decimal("0.01")),
        total_ars=total.quantize(Decimal("0.01")),
    )
