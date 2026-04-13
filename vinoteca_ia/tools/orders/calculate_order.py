"""
Tool SQL para calcular el total del pedido en Fase 1 (sin mutaciones).

Invocar después de verificar_stock_exacto y ANTES de presentar el
resumen al cliente. Esta tool NO escribe en base de datos.
"""

from __future__ import annotations

from uuid import UUID

from agno.tools import tool

from schemas.order import TipoEntrega
from schemas.tool_responses import OrderCalculation
from storage.postgres import fetch_all

COSTO_ENVIO = 500.0


@tool
async def calcular_pedido(items: list[dict], tipo_entrega: str = "retiro") -> OrderCalculation:
    """
    Calcula el total del pedido a partir de precios actuales en SQL.
    NO modifica stock ni crea registros. Solo lectura.

    Usar después de verificar_stock_exacto y antes de presentar el
    resumen de confirmación al cliente en Fase 1.

    Parámetros:
        items: Lista de {vino_id: str, cantidad: int}
        tipo_entrega: "retiro" | "envio"
    """
    if not items:
        return OrderCalculation(lineas=[], subtotal=0.0, total=0.0, tipo_entrega=tipo_entrega)

    ids = [UUID(item["vino_id"]) for item in items]
    cantidades = {UUID(item["vino_id"]): item["cantidad"] for item in items}
    placeholders = ", ".join(f"${i+1}" for i in range(len(ids)))

    rows = await fetch_all(
        f"SELECT id, nombre, precio FROM vinos WHERE id IN ({placeholders}) AND activo = true",
        *ids,
    )

    advertencias = []
    lineas = []
    subtotal = 0.0

    for row in rows:
        precio = float(row["precio"])
        if precio <= 0:
            advertencias.append(f"Precio inválido para {row['nombre']}. Omitido del cálculo.")
            continue
        cantidad = cantidades.get(row["id"], 0)
        subtotal_linea = precio * cantidad
        lineas.append({
            "vino_id": str(row["id"]),
            "nombre": row["nombre"],
            "cantidad": cantidad,
            "precio_unitario": precio,
            "subtotal": subtotal_linea,
        })
        subtotal += subtotal_linea

    envio = COSTO_ENVIO if tipo_entrega == TipoEntrega.ENVIO else 0.0
    total = subtotal + envio

    return OrderCalculation(
        lineas=lineas,
        subtotal=round(subtotal, 2),
        envio=round(envio, 2),
        total=round(total, 2),
        tipo_entrega=tipo_entrega,
        advertencias=advertencias,
    )
