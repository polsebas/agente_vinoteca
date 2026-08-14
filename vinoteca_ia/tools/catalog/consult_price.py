"""Consulta de precios autoritativa vía SQL. Nunca RAG ni estimación."""

from __future__ import annotations

from decimal import Decimal

from agno.tools import tool

from schemas.tool_responses import PrecioItem, PriceResponse, ResultadoTool
from storage.postgres import fetch_all


@tool
async def consultar_precio(
    producto_ids: list[str] | None = None,
    vino_ids: list[str] | None = None,
    nombre: str | None = None,
) -> PriceResponse:
    """Consultar el precio actual en ARS de uno o más vinos.

    Usá esta tool cuando el cliente pregunta el precio, antes de recomendar
    mencionando un valor, o antes de calcular un pedido. JAMÁS inventes
    precios: si no aparece acá, decile que lo verificás con el equipo.

    Args:
        producto_ids: IDs de catálogo (TEXT). Preferido.
        vino_ids: Alias de `producto_ids`.
        nombre: Fragmento de etiqueta si todavía no tenés el ID.

    Returns:
        PriceResponse con precios vigentes (precio > 0, producto activo).
    """
    ids = [str(i) for i in (producto_ids or vino_ids or []) if i]
    etiqueta = (nombre or "").strip()
    if not ids and not etiqueta:
        return PriceResponse(resultado=ResultadoTool.OK, items=[])

    clauses = ["activo = TRUE"]
    args: list = []
    if ids:
        placeholders = ", ".join(f"${i + 1}" for i in range(len(ids)))
        clauses.append(f"id IN ({placeholders})")
        args.extend(ids)
    if etiqueta:
        args.append(f"%{etiqueta}%")
        clauses.append(f"nombre ILIKE ${len(args)}")
    rows = await fetch_all(
        f"""
        SELECT id::text AS id, nombre, precio, anada, activo
        FROM vinos
        WHERE {" AND ".join(clauses)}
        ORDER BY nombre
        LIMIT 20
        """,
        *args,
    )

    items: list[PrecioItem] = []
    for row in rows:
        precio = row["precio"]
        if precio is None:
            continue
        precio_dec = Decimal(str(precio))
        if precio_dec <= 0:
            continue
        nombre = row["nombre"]
        if not nombre:
            continue
        items.append(
            PrecioItem(
                vino_id=str(row["id"]),
                nombre=nombre,
                precio_ars=precio_dec,
                anada=row["anada"],
            )
        )

    if not items:
        return PriceResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            mensaje="No se encontraron vinos activos con precio válido.",
        )
    return PriceResponse(resultado=ResultadoTool.OK, items=items)
