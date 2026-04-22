"""Verificación autoritativa de stock + reserva temporal (Fase 1 del 2PC).

A diferencia de `consultar_stock` (informativa), esta tool toma lock por fila
sobre `stock`, considera reservas activas de otras sesiones y, si hay
disponibilidad, **crea una reserva con TTL** atada al `session_id`. El token
de reserva queda implícito en `session_id` (lo consume `crear_orden`).

Sin reserva, entre esta tool y `crear_orden` podría venderse stock a otra
sesión aunque el stock bruto alcance. La reserva cierra ese hueco.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from agno.tools import tool

from schemas.tool_responses import ResultadoTool, VerifyStockResponse
from schemas.wine_catalog import StockInfo
from storage.postgres import get_pool

_TTL_MIN = int(os.environ.get("STOCK_RESERVA_TTL_MIN", "15"))


@tool
async def verificar_stock_exacto(
    session_id: str,
    lineas: list[dict[str, str | int]],
) -> VerifyStockResponse:
    """Verificar y RESERVAR stock para las líneas del pedido.

    Usá esta tool como PRIMER paso obligatorio al preparar un pedido. Si todas
    las líneas tienen stock disponible descontando reservas activas de otras
    sesiones, esta tool crea una reserva con TTL (default 15 min) y devuelve
    `reserva_token`. Si no, devuelve `todos_disponibles=False` con los faltantes.

    Nunca continúes con `calcular_orden` o `crear_orden` si esta tool reporta
    `todos_disponibles=False`. Informá al cliente los faltantes y ofrecé
    alternativas.

    Args:
        session_id: ID de la conversación (mismo que usa el chat). Necesario
            para vincular la reserva al flujo y evitar doble-reserva por reintento.
        lineas: Lista de objetos `{"vino_id": "<uuid>", "cantidad": <int>}`.

    Returns:
        VerifyStockResponse con `todos_disponibles`, `reserva_token` si la
        reserva fue exitosa, y `faltantes` si no.
    """
    if not lineas:
        return VerifyStockResponse(
            resultado=ResultadoTool.ERROR,
            todos_disponibles=False,
            mensaje="Debe proveer al menos una línea.",
        )

    try:
        requested: dict[UUID, int] = {}
        for line in lineas:
            vino_id = UUID(str(line["vino_id"]))
            cantidad = int(line["cantidad"])
            if cantidad <= 0:
                raise ValueError(f"Cantidad debe ser positiva para {vino_id}.")
            requested[vino_id] = requested.get(vino_id, 0) + cantidad
    except (KeyError, ValueError) as exc:
        return VerifyStockResponse(
            resultado=ResultadoTool.ERROR,
            todos_disponibles=False,
            mensaje=f"Líneas mal formadas: {exc}",
        )

    now = datetime.now(UTC)
    expira_en = now + timedelta(minutes=_TTL_MIN)

    vino_ids = list(requested.keys())

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT v.id, v.nombre,
                       COALESCE(s.cantidad, 0) AS cantidad,
                       COALESCE(s.ubicacion, 'deposito_principal') AS ubicacion
                FROM vinos v
                LEFT JOIN stock s ON s.vino_id = v.id
                WHERE v.id = ANY($1::uuid[]) AND v.activo = TRUE
                FOR UPDATE OF s
                """,
                vino_ids,
            )

            reservas_ajenas = await conn.fetch(
                """
                SELECT vino_id,
                       COALESCE(SUM(cantidad), 0)::int AS reservado
                FROM stock_reservas
                WHERE vino_id = ANY($1::uuid[])
                  AND session_id <> $2
                  AND estado = 'activa'
                  AND expira_en > $3
                GROUP BY vino_id
                """,
                vino_ids,
                session_id,
                now,
            )
            reservado_ajeno: dict[UUID, int] = {
                r["vino_id"]: int(r["reservado"]) for r in reservas_ajenas
            }

            items: list[StockInfo] = []
            faltantes: list[UUID] = []
            for row in rows:
                vino_id = row["id"]
                wanted = requested[vino_id]
                cantidad_fisica = row["cantidad"]
                disponible_efectivo = max(
                    cantidad_fisica - reservado_ajeno.get(vino_id, 0),
                    0,
                )
                items.append(
                    StockInfo(
                        vino_id=vino_id,
                        nombre=row["nombre"],
                        disponible=disponible_efectivo >= wanted,
                        cantidad=disponible_efectivo,
                        ubicacion=row["ubicacion"],
                    )
                )
                if disponible_efectivo < wanted:
                    faltantes.append(vino_id)

            for vid in requested:
                if all(i.vino_id != vid for i in items):
                    faltantes.append(vid)

            if faltantes:
                return VerifyStockResponse(
                    resultado=ResultadoTool.OK,
                    todos_disponibles=False,
                    items=items,
                    faltantes=faltantes,
                )

            await conn.execute(
                """
                UPDATE stock_reservas
                SET estado = 'cancelada'
                WHERE session_id = $1 AND estado = 'activa'
                """,
                session_id,
            )

            for vino_id, cantidad in requested.items():
                await conn.execute(
                    """
                    INSERT INTO stock_reservas (
                        reserva_id, vino_id, cantidad, session_id,
                        estado, creada_en, expira_en
                    ) VALUES ($1, $2, $3, $4, 'activa', $5, $6)
                    """,
                    uuid4(),
                    vino_id,
                    cantidad,
                    session_id,
                    now,
                    expira_en,
                )

    return VerifyStockResponse(
        resultado=ResultadoTool.OK,
        todos_disponibles=True,
        items=items,
        reserva_token=session_id,
        reserva_expira_en=expira_en.isoformat(),
    )
