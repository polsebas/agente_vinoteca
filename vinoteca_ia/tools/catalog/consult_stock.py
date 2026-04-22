"""Consulta de stock autoritativa vía SQL."""

from __future__ import annotations

from uuid import UUID

from agno.tools import tool

from schemas.tool_responses import ResultadoTool, StockResponse
from schemas.wine_catalog import StockInfo
from storage.postgres import fetch_all


@tool
async def consultar_stock(vino_ids: list[str]) -> StockResponse:
    """Consultar disponibilidad y cantidad de uno o más vinos por su UUID.

    Usá esta tool cuando:
    - El cliente pregunta si un vino está disponible o cuántas unidades quedan.
    - Antes de confirmar una recomendación con intención de compra.
    - Antes de presentar un resumen de pedido al cliente.

    NUNCA uses RAG/vectores para stock: la única fuente válida es esta tool.
    Siempre llamá a esta tool antes de afirmar disponibilidad al cliente.

    Args:
        vino_ids: Lista de UUIDs (como strings) de vinos a consultar.

    Returns:
        StockResponse con la lista de StockInfo y el flag `todos_disponibles`.
    """
    if not vino_ids:
        return StockResponse(
            resultado=ResultadoTool.OK,
            items=[],
            todos_disponibles=False,
            mensaje="Sin IDs para consultar",
        )

    try:
        ids = [UUID(v) for v in vino_ids]
    except ValueError as exc:
        return StockResponse(
            resultado=ResultadoTool.ERROR,
            mensaje=f"UUID inválido: {exc}",
        )

    placeholders = ", ".join(f"${i + 1}" for i in range(len(ids)))
    rows = await fetch_all(
        f"""
        SELECT v.id, v.nombre,
               COALESCE(s.cantidad, 0) AS cantidad,
               COALESCE(s.ubicacion, 'deposito_principal') AS ubicacion
        FROM vinos v
        LEFT JOIN stock s ON s.vino_id = v.id
        WHERE v.id IN ({placeholders}) AND v.activo = TRUE
        """,
        *ids,
    )

    items = [
        StockInfo(
            vino_id=row["id"],
            nombre=row["nombre"],
            disponible=row["cantidad"] > 0,
            cantidad=row["cantidad"],
            ubicacion=row["ubicacion"],
        )
        for row in rows
    ]
    return StockResponse(
        resultado=ResultadoTool.OK,
        items=items,
        todos_disponibles=bool(items) and all(i.disponible for i in items),
    )
