"""Verificación autoritativa de stock (Fase 1 del 2PC). NO muta la DB."""

from __future__ import annotations

from agno.tools import tool

from schemas.order import LineaPedidoSolicitud
from schemas.tool_responses import ResultadoTool, VerifyStockResponse
from schemas.wine_catalog import StockInfo
from storage.postgres import fetch_all


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


@tool
async def verificar_stock_exacto(
    session_id: str,
    lineas: list[LineaPedidoSolicitud],
) -> VerifyStockResponse:
    """Verificar si hay stock exacto para las líneas, sin reservar.

    Primer paso del 2PC. Solo LECTURA: `cantidad_disponible - reservado >= cantidad`.
    Si falta stock, no sigas a `calcular_orden` ni `crear_orden`.

    Args:
        session_id: ID de la conversación (tracing; no se escribe en DB).
        lineas: `producto_id`/`vino_id` + `cantidad`.
    """
    parsed = _parse_lineas(lineas)
    if isinstance(parsed, str):
        return VerifyStockResponse(
            resultado=ResultadoTool.ERROR,
            todos_disponibles=False,
            mensaje=parsed,
        )

    requested: dict[str, int] = {}
    for sol in parsed:
        requested[sol.producto_id] = requested.get(sol.producto_id, 0) + sol.cantidad

    ids = list(requested.keys())
    placeholders = ", ".join(f"${i + 1}" for i in range(len(ids)))
    rows = await fetch_all(
        f"""
        SELECT v.id::text AS id,
               v.nombre,
               GREATEST(
                   COALESCE(s.cantidad_disponible, 0) - COALESCE(s.reservado, 0),
                   0
               ) AS disponible,
               COALESCE(s.ubicacion, 'deposito_principal') AS ubicacion,
               v.activo
        FROM vinos v
        LEFT JOIN stock s ON s.producto_id = v.id
        WHERE v.id IN ({placeholders})
        """,
        *ids,
    )
    por_id = {str(r["id"]): r for r in rows}

    items: list[StockInfo] = []
    faltantes: list[str] = []
    for pid, wanted in requested.items():
        row = por_id.get(pid)
        if row is None or not row["activo"]:
            faltantes.append(pid)
            continue
        disponible = int(row["disponible"] or 0)
        ok = disponible >= wanted
        items.append(
            StockInfo(
                vino_id=pid,
                nombre=row["nombre"] or pid,
                disponible=ok,
                cantidad=disponible,
                ubicacion=row["ubicacion"] or "deposito_principal",
            )
        )
        if not ok:
            faltantes.append(pid)

    todos = bool(items) and not faltantes
    return VerifyStockResponse(
        resultado=ResultadoTool.OK,
        todos_disponibles=todos,
        items=items,
        faltantes=faltantes,
        mensaje=None if todos else "Stock insuficiente en una o más líneas.",
    )
