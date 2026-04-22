"""Consulta de precios autoritativa vía SQL."""

from __future__ import annotations

from uuid import UUID

from agno.tools import tool

from schemas.tool_responses import PrecioItem, PriceResponse, ResultadoTool
from storage.postgres import fetch_all


@tool
async def consultar_precio(vino_ids: list[str]) -> PriceResponse:
    """Consultar el precio actual en ARS de uno o más vinos.

    Usá esta tool cuando:
    - El cliente pregunta explícitamente el precio de un vino.
    - Antes de recomendar un vino mencionando su precio.
    - Antes de calcular un pedido.

    JAMÁS inventes ni estimes precios. Si no aparece en esta tool, decile
    al cliente que vas a verificar con el equipo. El LLM no tiene licencia
    para producir precios por su cuenta.

    Args:
        vino_ids: Lista de UUIDs (como strings) de vinos.

    Returns:
        PriceResponse con precios y añadas vigentes.
    """
    if not vino_ids:
        return PriceResponse(resultado=ResultadoTool.OK, items=[])

    try:
        ids = [UUID(v) for v in vino_ids]
    except ValueError as exc:
        return PriceResponse(
            resultado=ResultadoTool.ERROR,
            mensaje=f"UUID inválido: {exc}",
        )

    placeholders = ", ".join(f"${i + 1}" for i in range(len(ids)))
    rows = await fetch_all(
        f"""
        SELECT id, nombre, precio_ars, anada_actual
        FROM vinos
        WHERE id IN ({placeholders}) AND activo = TRUE
        """,
        *ids,
    )

    if not rows:
        return PriceResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            mensaje="No se encontraron vinos activos para los IDs dados.",
        )

    items = [
        PrecioItem(
            vino_id=row["id"],
            nombre=row["nombre"],
            precio_ars=row["precio_ars"],
            anada=row["anada_actual"],
        )
        for row in rows
    ]
    return PriceResponse(resultado=ResultadoTool.OK, items=items)
