"""
POST /pedido/{pedido_id}/aprobar — señal HitL que desbloquea la Fase 2 del Two-Phase Commit.
Este endpoint es la única forma de ejecutar una transacción de compra.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from agents.orders_agent import ejecutar_fase_2
from schemas.order import OrderEstado
from storage.immutable_log import registrar
from storage.postgres import execute, fetch_one

router = APIRouter()


class AprobacionRequest(BaseModel):
    aprobado: bool = True
    operador_id: str | None = None
    notas: str | None = None


class AprobacionResponse(BaseModel):
    ok: bool
    pedido_id: str
    mensaje: str
    url_pago: str | None = None
    total: float | None = None


@router.post("/pedido/{pedido_id}/aprobar", response_model=AprobacionResponse, tags=["Pedidos"])
async def aprobar_pedido(
    pedido_id: UUID,
    body: AprobacionRequest,
    request: Request,
) -> AprobacionResponse:
    """
    Señal HitL para ejecutar la Fase 2 del Two-Phase Commit.
    Solo puede activarse una vez por pedido. Idempotente por idempotency_key.
    """
    pedido = await fetch_one(
        "SELECT id, estado, total, session_id, idempotency_key FROM pedidos WHERE id = $1",
        pedido_id,
    )

    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pedido {pedido_id} no encontrado.",
        )

    if pedido["estado"] == OrderEstado.CONFIRMADO:
        return AprobacionResponse(
            ok=True,
            pedido_id=str(pedido_id),
            mensaje="Este pedido ya fue confirmado anteriormente.",
            total=float(pedido["total"]) if pedido["total"] else None,
        )

    if pedido["estado"] != OrderEstado.PENDIENTE_APROBACION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El pedido está en estado '{pedido['estado']}' y no puede ser aprobado.",
        )

    if not body.aprobado:
        await execute(
            "UPDATE pedidos SET estado = $1, updated_at = NOW() WHERE id = $2",
            OrderEstado.CANCELADO,
            pedido_id,
        )
        await registrar(
            "pedido_cancelado_por_cliente",
            pedido_id=pedido_id,
            session_id=pedido["session_id"],
            payload={"operador_id": body.operador_id, "notas": body.notas},
        )
        return AprobacionResponse(
            ok=True,
            pedido_id=str(pedido_id),
            mensaje="Pedido cancelado. ¿Podemos ayudarte con algo más?",
        )

    resultado = await ejecutar_fase_2(
        pedido_id=str(pedido_id),
        idempotency_key=pedido["idempotency_key"],
        session_id=pedido["session_id"],
    )

    if not resultado.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=resultado.get("mensaje", "Error al procesar el pedido."),
        )

    return AprobacionResponse(
        ok=True,
        pedido_id=str(pedido_id),
        mensaje=resultado.get("mensaje", "Pedido confirmado."),
        url_pago=resultado.get("url_pago"),
        total=resultado.get("total"),
    )
