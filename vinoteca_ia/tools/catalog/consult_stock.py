"""
Tool SQL para consultar disponibilidad de stock.

Invocar cuando el usuario pregunta si un vino está disponible, cuántas
unidades quedan, o antes de confirmar cualquier recomendación con intención
de compra. NUNCA usar vectores para determinar stock.
"""

from __future__ import annotations

from uuid import UUID

from agno.tools import tool
from pydantic import BaseModel

from schemas.tool_responses import StockQueryResult
from schemas.wine_catalog import StockInfo
from storage.postgres import fetch_all


class ConsultarStockInput(BaseModel):
    vino_ids: list[UUID]


@tool
async def consultar_stock(vino_ids: list[str]) -> StockQueryResult:
    """
    Consulta el stock actual de uno o varios vinos por su ID.

    Usar cuando:
    - El Sumiller necesita verificar disponibilidad antes de recomendar.
    - El cliente pregunta directamente si un vino está disponible.
    - El agente de Pedidos verifica stock en Fase 1 del Two-Phase Commit.

    Parámetros:
        vino_ids: Lista de UUIDs de vinos a consultar.

    Nunca usar RAG para este propósito. La fuente es exclusivamente SQL.
    """
    if not vino_ids:
        return StockQueryResult(items=[], todos_disponibles=False)

    ids = [UUID(v) for v in vino_ids]
    placeholders = ", ".join(f"${i+1}" for i in range(len(ids)))

    rows = await fetch_all(
        f"""
        SELECT v.id, v.nombre, s.cantidad, s.ubicacion
        FROM vinos v
        LEFT JOIN stock s ON s.vino_id = v.id
        WHERE v.id IN ({placeholders}) AND v.activo = true
        """,
        *ids,
    )

    items = [
        StockInfo(
            vino_id=row["id"],
            nombre=row["nombre"],
            disponible=(row["cantidad"] or 0) > 0,
            cantidad=row["cantidad"] or 0,
            ubicacion=row["ubicacion"] or "deposito_principal",
        )
        for row in rows
    ]

    return StockQueryResult(
        items=items,
        todos_disponibles=all(i.disponible for i in items),
    )
