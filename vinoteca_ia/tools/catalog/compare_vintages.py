"""Comparación de añadas de una misma etiqueta. Solo SQL."""

from __future__ import annotations

from decimal import Decimal

from agno.tools import tool

from schemas.tool_responses import ResultadoTool, VintageComparisonResponse, VintageItem
from storage.postgres import fetch_all


@tool
async def comparar_anadas(etiqueta: str, bodega: str | None = None) -> VintageComparisonResponse:
    """Listar añadas de una etiqueta ordenadas por año, con precio SQL.

    Usá esta tool cuando el cliente compara cosechas ("el 2019 vs el 2021")
    o pide "todas las añadas de X". NUNCA uses RAG: año y precio salen de SQL.

    Args:
        etiqueta: Nombre (o fragmento) del vino.
        bodega: Filtro opcional de bodega.

    Returns:
        VintageComparisonResponse ordenado por añada descendente.
    """
    if not etiqueta.strip():
        return VintageComparisonResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La etiqueta no puede estar vacía.",
        )

    args: list = [f"%{etiqueta.strip()}%"]
    bodega_sql = ""
    if bodega and bodega.strip():
        args.append(f"%{bodega.strip()}%")
        bodega_sql = "AND bodega ILIKE $2"

    rows = await fetch_all(
        f"""
        SELECT id::text AS id, nombre, bodega, anada, precio, activo
        FROM vinos
        WHERE nombre ILIKE $1 {bodega_sql}
          AND activo = TRUE
          AND precio IS NOT NULL AND precio > 0
          AND anada IS NOT NULL
        ORDER BY anada DESC
        """,
        *args,
    )
    items = [
        VintageItem(
            producto_id=str(row["id"]),
            nombre=row["nombre"],
            bodega=row["bodega"] or "",
            anada=int(row["anada"]),
            precio=Decimal(str(row["precio"])),
            activo=bool(row["activo"]),
        )
        for row in rows
    ]
    if not items:
        return VintageComparisonResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            mensaje="No hay añadas activas para esa etiqueta.",
        )
    return VintageComparisonResponse(resultado=ResultadoTool.OK, items=items)
