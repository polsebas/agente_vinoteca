"""Reserva atómica de cupo en un evento. SQL + log inmutable."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from agno.tools import tool

from schemas.tool_responses import EventReservationResponse, ResultadoTool
from storage.immutable_log import log_transaction_event
from storage.postgres import get_pool


@tool
async def reservar_evento(
    evento_id: str,
    cliente_id: str | None,
    cantidad: int = 1,
    session_id: str = "",
) -> EventReservationResponse:
    """Reservar asientos si hay cupo. Descuenta `cupo_disponible` en transacción.

    Usá esta tool cuando el cliente confirma lugar en una cata. Si no hay
    cupo, no inventes disponibilidad.
    """
    if cantidad <= 0:
        return EventReservationResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La cantidad debe ser positiva.",
        )
    if not evento_id.strip():
        return EventReservationResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="evento_id vacío.",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id, precio, cupo_disponible, activo
                FROM eventos
                WHERE id = $1
                FOR UPDATE
                """,
                evento_id,
            )
            if row is None or not row["activo"]:
                return EventReservationResponse(
                    resultado=ResultadoTool.NO_ENCONTRADO,
                    evento_id=evento_id,
                    mensaje="Evento inexistente o inactivo.",
                )
            cupo = int(row["cupo_disponible"] or 0)
            if cupo < cantidad:
                return EventReservationResponse(
                    resultado=ResultadoTool.ERROR,
                    evento_id=evento_id,
                    mensaje=f"Cupo insuficiente ({cupo} disponibles).",
                )
            total = (Decimal(str(row["precio"] or 0)) * Decimal(cantidad)).quantize(Decimal("0.01"))
            reserva_id = f"EVT-{uuid4().hex[:8]}"
            await conn.execute(
                """
                UPDATE eventos
                SET cupo_disponible = cupo_disponible - $1
                WHERE id = $2 AND cupo_disponible >= $1
                """,
                cantidad,
                evento_id,
            )
            await conn.execute(
                """
                INSERT INTO eventos_reservas (
                    id, evento_id, cliente_id, cantidad, total, estado, created_at
                ) VALUES ($1,$2,$3,$4,$5,'confirmada', NOW())
                """,
                reserva_id,
                evento_id,
                cliente_id,
                cantidad,
                total,
            )

    await log_transaction_event(
        session_id=session_id,
        accion="reservar_evento",
        payload={"reserva_id": reserva_id, "evento_id": evento_id, "cantidad": cantidad},
        idempotency_key=reserva_id,
        resultado="ok",
    )
    return EventReservationResponse(
        resultado=ResultadoTool.OK,
        reserva_id=reserva_id,
        evento_id=evento_id,
        cantidad=cantidad,
        total=total,
        estado="confirmada",
    )
