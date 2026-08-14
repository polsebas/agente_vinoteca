"""Consulta de stock autoritativa vía SQL. Nunca RAG."""

from __future__ import annotations

from agno.tools import tool

from schemas.tool_responses import ResultadoTool, StockResponse
from schemas.wine_catalog import StockInfo
from storage.postgres import fetch_all


@tool
async def consultar_stock(
    producto_ids: list[str] | None = None,
    vino_ids: list[str] | None = None,
    varietal: str | None = None,
    region: str | None = None,
    nombre: str | None = None,
) -> StockResponse:
    """Consultar disponibilidad y cantidad de vinos por ID o filtro.

    Usá esta tool cuando el cliente pregunta si un vino está disponible,
    cuántas unidades quedan, o antes de armar un pedido. NUNCA uses RAG
    para stock: la única fuente válida es SQL.

    Args:
        producto_ids: IDs de catálogo (TEXT). Preferido.
        vino_ids: Alias de `producto_ids` (compatibilidad).
        varietal: Filtro opcional (malbec, cabernet_sauvignon, …).
        region: Filtro opcional de región.
        nombre: Fragmento de etiqueta si todavía no tenés el ID.

    Returns:
        StockResponse con StockInfo y `todos_disponibles`.
    """
    ids = [str(i) for i in (producto_ids or vino_ids or []) if i]
    etiqueta = (nombre or "").strip()
    if not ids and not varietal and not region and not etiqueta:
        return StockResponse(
            resultado=ResultadoTool.OK,
            items=[],
            todos_disponibles=False,
            mensaje="Sin IDs ni filtros para consultar",
        )

    clauses = ["v.activo = TRUE"]
    args: list = []
    if ids:
        placeholders = ", ".join(f"${i + 1}" for i in range(len(ids)))
        clauses.append(f"v.id IN ({placeholders})")
        args.extend(ids)
    if varietal:
        args.append(varietal)
        clauses.append(f"v.varietal = ${len(args)}")
    if region:
        args.append(f"%{region}%")
        clauses.append(f"v.region ILIKE ${len(args)}")
    if etiqueta:
        args.append(f"%{etiqueta}%")
        clauses.append(f"v.nombre ILIKE ${len(args)}")

    where = " AND ".join(clauses)
    rows = await fetch_all(
        f"""
        SELECT v.id::text AS id,
               v.nombre,
               GREATEST(
                   COALESCE(s.cantidad_disponible, 0) - COALESCE(s.reservado, 0),
                   0
               ) AS cantidad,
               COALESCE(s.ubicacion, 'deposito_principal') AS ubicacion
        FROM vinos v
        LEFT JOIN stock s ON s.producto_id = v.id
        WHERE {where}
        ORDER BY v.nombre
        LIMIT 30
        """,
        *args,
    )

    items: list[StockInfo] = []
    for row in rows:
        cantidad = int(row["cantidad"] or 0)
        nombre = row["nombre"] or ""
        if not nombre:
            continue
        items.append(
            StockInfo(
                vino_id=str(row["id"]),
                nombre=nombre,
                disponible=cantidad > 0,
                cantidad=cantidad,
                ubicacion=row["ubicacion"] or "deposito_principal",
            )
        )
    return StockResponse(
        resultado=ResultadoTool.OK,
        items=items,
        todos_disponibles=bool(items) and all(i.disponible for i in items),
    )
