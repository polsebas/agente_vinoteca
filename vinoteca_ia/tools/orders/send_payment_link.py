"""Envío de link de pago (Fase 2 del Two-Phase Commit).

Esta tool solo debe invocarse después de que la orden esté en estado APROBADA.
El endpoint `/pedido/{id}/aprobar` cambia el estado y dispara `acontinue_run()`,
que permite al agente invocar esta tool automáticamente al retomar.
"""

from __future__ import annotations

import os
from uuid import UUID

import httpx
from agno.tools import tool

from core.idempotency import IdempotencyManager
from schemas.order import EstadoOrden
from schemas.tool_responses import PaymentLinkResponse, ResultadoTool
from storage.postgres import execute, fetchrow


@tool(requires_confirmation=True)
async def enviar_link_pago(order_id: str) -> PaymentLinkResponse:
    """Generar y persistir el link de pago de una orden APROBADA.

    Usá esta tool como PASO FINAL del flujo de pedido, únicamente cuando:
    - La orden existe en la DB en estado APROBADA.
    - Ya fue confirmada vía `/pedido/{id}/aprobar`.

    Esta tool también tiene `requires_confirmation=True` como segunda barrera
    de seguridad: aun cuando el run se reanuda, el framework pide confirmación
    antes de golpear el proveedor de pagos. Es deliberado: prevenimos cobros
    dobles por race conditions.

    La idempotencia se calcula sobre `order_id`: una orden nunca genera dos
    links de pago distintos.

    Args:
        order_id: UUID de la orden (como string).

    Returns:
        PaymentLinkResponse con `payment_link` o error explicativo.
    """
    try:
        oid = UUID(order_id)
    except ValueError as exc:
        return PaymentLinkResponse(
            resultado=ResultadoTool.ERROR,
            order_id=UUID(int=0),
            mensaje=f"UUID inválido: {exc}",
        )

    row = await fetchrow(
        "SELECT id, total_ars, estado FROM pedidos WHERE id = $1",
        oid,
    )
    if row is None:
        return PaymentLinkResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            order_id=oid,
            mensaje="Orden inexistente.",
        )
    if row["estado"] != EstadoOrden.APROBADA.value:
        return PaymentLinkResponse(
            resultado=ResultadoTool.ERROR,
            order_id=oid,
            mensaje=(
                f"Orden en estado {row['estado']}: solo se envía link cuando "
                f"está APROBADA."
            ),
        )

    idem = IdempotencyManager()
    idem_key = IdempotencyManager.build_key("payment_link", str(oid))
    cached = await idem.get(idem_key)
    if cached and cached.status == "ok":
        return PaymentLinkResponse.model_validate_json(cached.resultado_json)

    link = await _request_payment_link(oid, row["total_ars"])

    await execute(
        "UPDATE pedidos SET payment_link = $1 WHERE id = $2",
        link,
        oid,
    )

    response = PaymentLinkResponse(
        resultado=ResultadoTool.OK,
        order_id=oid,
        payment_link=link,
    )
    await idem.put(idem_key, response.model_dump_json(), status="ok")
    return response


async def _request_payment_link(order_id: UUID, total: float | int) -> str:
    """Llama al proveedor (MercadoPago) o devuelve un mock en desarrollo."""
    if os.environ.get("MERCADOPAGO_MOCK_ENABLED", "true").lower() == "true":
        return f"https://mock.mercadopago.test/pay/{order_id}"

    token = os.environ.get("MERCADOPAGO_ACCESS_TOKEN", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.mercadopago.com/checkout/preferences",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "items": [
                    {
                        "title": f"Orden {order_id}",
                        "quantity": 1,
                        "unit_price": float(total),
                    }
                ],
                "external_reference": str(order_id),
            },
        )
        resp.raise_for_status()
        return resp.json()["init_point"]
