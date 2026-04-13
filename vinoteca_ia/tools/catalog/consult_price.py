"""
Tool SQL para consultar precio exacto de un vino.

Invocar cuando el usuario pregunta el precio o cuando el agente de
Pedidos necesita calcular el total del carrito. NUNCA obtener precios
desde el vector store — los vectores pueden estar desactualizados.
"""

from __future__ import annotations

from uuid import UUID

from agno.tools import tool

from schemas.tool_responses import PriceQueryResult
from storage.postgres import fetch_one


@tool
async def consultar_precio(vino_id: str) -> PriceQueryResult:
    """
    Consulta el precio actual de un vino por su ID.

    Usar cuando:
    - El usuario pregunta cuánto cuesta un vino específico.
    - El agente de Pedidos necesita el precio para calcular totales.

    El precio siempre viene de SQL. Si el resultado es $0 o nulo,
    es un dato corrupto: marcar como inválido y no usar.
    """
    uid = UUID(vino_id)
    row = await fetch_one(
        "SELECT id, nombre, precio FROM vinos WHERE id = $1 AND activo = true",
        uid,
    )

    if not row:
        return PriceQueryResult(
            vino_id=uid,
            nombre="desconocido",
            precio=0.0,
            valido=False,
            razon_invalido="Vino no encontrado en catálogo activo.",
        )

    precio = float(row["precio"])
    if precio <= 0:
        return PriceQueryResult(
            vino_id=uid,
            nombre=row["nombre"],
            precio=precio,
            valido=False,
            razon_invalido="Precio inválido (cero o negativo). Consultar con administrador.",
        )

    return PriceQueryResult(
        vino_id=uid,
        nombre=row["nombre"],
        precio=precio,
        valido=True,
    )
