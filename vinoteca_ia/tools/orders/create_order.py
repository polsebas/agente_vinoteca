"""
Tool SQL para crear el pedido en Fase 2 del Two-Phase Commit.

Invocar ÚNICAMENTE después de que el cliente confirmó explícitamente
el resumen mostrado en Fase 1 y se recibió la señal en /aprobar.
Esta tool MUTA la base de datos: descuenta stock y crea el pedido.
"""

from __future__ import annotations

from uuid import UUID

from agno.tools import tool

from schemas.order import OrderEstado
from schemas.tool_responses import OrderCreationResult
from storage.immutable_log import registrar
from storage.postgres import execute, fetch_one, fetchval, get_pool


@tool
async def crear_pedido(
    session_id: str,
    idempotency_key: str,
    items: list[dict],
    tipo_entrega: str = "retiro",
    direccion: str | None = None,
    notas: str | None = None,
) -> OrderCreationResult:
    """
    Crea el pedido definitivo y descuenta stock. Es una operación destructiva.

    Invocar SOLO en Fase 2, después de:
    1. verificar_stock_exacto devolvió todo_disponible=True
    2. calcular_pedido mostró el resumen al cliente
    3. El cliente confirmó explícitamente
    4. Se recibió la señal en POST /aprobar

    La idempotency_key previene dobles cobros. Si ya existe un pedido
    con esa key, retornar el pedido existente sin crear uno nuevo.
    """
    pool = await get_pool()

    existing = await fetch_one(
        "SELECT id, total, estado FROM pedidos WHERE idempotency_key = $1",
        idempotency_key,
    )
    if existing:
        return OrderCreationResult(
            pedido_id=existing["id"],
            idempotency_key=idempotency_key,
            estado=existing["estado"],
            total=float(existing["total"] or 0),
        )

    ids = [UUID(item["vino_id"]) for item in items]
    cantidades = {UUID(item["vino_id"]): item["cantidad"] for item in items}
    placeholders = ", ".join(f"${i+1}" for i in range(len(ids)))

    rows = await pool.fetch(
        f"SELECT id, nombre, precio FROM vinos WHERE id IN ({placeholders}) AND activo = true",
        *ids,
    ) if pool else []

    subtotal = sum(float(r["precio"]) * cantidades.get(r["id"], 0) for r in rows)
    envio = 500.0 if tipo_entrega == "envio" else 0.0
    total = subtotal + envio

    async with pool.acquire() as conn:
        async with conn.transaction():
            pedido_id = await conn.fetchval(
                """
                INSERT INTO pedidos
                    (session_id, estado, tipo_entrega, direccion, subtotal, total, idempotency_key, notas)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                session_id,
                OrderEstado.CONFIRMADO,
                tipo_entrega,
                direccion,
                round(subtotal, 2),
                round(total, 2),
                idempotency_key,
                notas,
            )

            for row in rows:
                cantidad = cantidades.get(row["id"], 0)
                await conn.execute(
                    """
                    INSERT INTO lineas_pedido (pedido_id, vino_id, cantidad, precio_unitario)
                    VALUES ($1, $2, $3, $4)
                    """,
                    pedido_id,
                    row["id"],
                    cantidad,
                    float(row["precio"]),
                )
                await conn.execute(
                    """
                    UPDATE stock SET cantidad = cantidad - $1, updated_at = NOW()
                    WHERE vino_id = $2 AND cantidad >= $1
                    """,
                    cantidad,
                    row["id"],
                )

    await registrar(
        "pedido_confirmado",
        pedido_id=pedido_id,
        session_id=session_id,
        payload={"idempotency_key": idempotency_key, "total": total},
    )

    return OrderCreationResult(
        pedido_id=pedido_id,
        idempotency_key=idempotency_key,
        estado=OrderEstado.CONFIRMADO,
        total=round(total, 2),
    )
