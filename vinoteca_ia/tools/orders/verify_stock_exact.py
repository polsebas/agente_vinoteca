"""
Tool SQL para verificación exacta de stock en Fase 1 del Two-Phase Commit.

Invocar como primer paso del agente de Pedidos antes de calcular el total.
Verifica que cada ítem tenga la cantidad solicitada disponible. Sin este
paso, nunca avanzar a calculate_order.
"""

from __future__ import annotations

from uuid import UUID

from agno.tools import tool
from pydantic import BaseModel

from storage.postgres import fetch_all


class ItemVerificacion(BaseModel):
    vino_id: str
    cantidad: int


class ResultadoVerificacion(BaseModel):
    todo_disponible: bool
    faltantes: list[dict]
    mensaje: str


@tool
async def verificar_stock_exacto(items: list[dict]) -> ResultadoVerificacion:
    """
    Verifica disponibilidad exacta de stock para todos los ítems del carrito.

    Usar como PRIMER paso en Fase 1 del Two-Phase Commit, antes de calcular
    el total o presentar el resumen al cliente. Si hay faltantes, informar
    al cliente y no avanzar.

    Parámetros:
        items: Lista de {vino_id: str, cantidad: int}
    """
    if not items:
        return ResultadoVerificacion(
            todo_disponible=False,
            faltantes=[],
            mensaje="No hay ítems para verificar.",
        )

    ids = [UUID(item["vino_id"]) for item in items]
    cantidades = {UUID(item["vino_id"]): item["cantidad"] for item in items}
    placeholders = ", ".join(f"${i+1}" for i in range(len(ids)))

    rows = await fetch_all(
        f"""
        SELECT v.id, v.nombre, COALESCE(s.cantidad, 0) as cantidad
        FROM vinos v
        LEFT JOIN stock s ON s.vino_id = v.id
        WHERE v.id IN ({placeholders}) AND v.activo = true
        """,
        *ids,
    )

    faltantes = []
    for row in rows:
        solicitado = cantidades.get(row["id"], 0)
        disponible = row["cantidad"]
        if disponible < solicitado:
            faltantes.append({
                "vino_id": str(row["id"]),
                "nombre": row["nombre"],
                "solicitado": solicitado,
                "disponible": disponible,
            })

    if faltantes:
        nombres = ", ".join(f["nombre"] for f in faltantes)
        return ResultadoVerificacion(
            todo_disponible=False,
            faltantes=faltantes,
            mensaje=f"Stock insuficiente para: {nombres}. Por favor modificá las cantidades.",
        )

    return ResultadoVerificacion(
        todo_disponible=True,
        faltantes=[],
        mensaje="Stock verificado. Todos los ítems están disponibles.",
    )
