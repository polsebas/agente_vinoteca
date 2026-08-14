"""Envío de link de pago (post-2PC). Expiración 30 minutos."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from agno.tools import tool

from core.idempotency import IdempotencyManager
from schemas.order import EstadoOrden
from schemas.tool_responses import PaymentLinkResponse, ResultadoTool
from storage.immutable_log import log_transaction_event
from storage.postgres import execute, fetchrow

_EXPIRY_MIN = 30


@tool(requires_confirmation=True)
async def enviar_link_pago(order_id: str) -> PaymentLinkResponse:
    """Generar y persistir el link de pago de una orden APROBADA.

    Paso final, solo con orden APROBADA. `requires_confirmation=True` evita
    cobros dobles. El link mock/real expira a los 30 minutos.

    Args:
        order_id: ID TEXT del pedido (ej. PED-a1b2c3d4).
    """
    if not order_id.strip():
        return PaymentLinkResponse(
            resultado=ResultadoTool.ERROR,
            order_id=order_id,
            mensaje="order_id vacío.",
        )

    row = await fetchrow(
        "SELECT id, total, estado FROM pedidos WHERE id = $1",
        order_id,
    )
    if row is None:
        return PaymentLinkResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            order_id=order_id,
            mensaje="Orden inexistente.",
        )
    if row["estado"] != EstadoOrden.APROBADA.value:
        return PaymentLinkResponse(
            resultado=ResultadoTool.ERROR,
            order_id=order_id,
            mensaje=(f"Orden en estado {row['estado']}: solo se envía link cuando está APROBADA."),
        )

    idem = IdempotencyManager()
    idem_key = IdempotencyManager.build_key("payment_link", order_id)
    try:
        cached = await idem.get(idem_key)
        if cached and cached.status == "ok":
            return PaymentLinkResponse.model_validate_json(cached.resultado_json)
    except Exception:
        pass

    total = Decimal(str(row["total"] or 0))
    expira = datetime.now(UTC) + timedelta(minutes=_EXPIRY_MIN)
    link = await _request_payment_link(order_id, total, expira)

    await execute(
        "UPDATE pedidos SET payment_link = $1 WHERE id = $2",
        link,
        order_id,
    )
    await log_transaction_event(
        session_id="",
        accion="enviar_link_pago",
        payload={"order_id": order_id, "expira": expira.isoformat()},
        idempotency_key=idem_key,
        resultado="ok",
        metadata={"pedido_id": order_id},
    )
    response = PaymentLinkResponse(
        resultado=ResultadoTool.OK,
        order_id=order_id,
        payment_link=link,
        mensaje=f"Link válido hasta {expira.isoformat()}",
    )
    try:
        await idem.put(idem_key, response.model_dump_json(), status="ok")
    except Exception:
        pass
    return response


async def _request_payment_link(
    order_id: str,
    total: Decimal,
    expira: datetime,
) -> str:
    if os.environ.get("MERCADOPAGO_MOCK_ENABLED", "true").lower() == "true":
        ts = int(expira.timestamp())
        return f"https://mock.mercadopago.test/pay/{order_id}?exp={ts}"

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
                "external_reference": order_id,
                "expires": True,
                "expiration_date_to": expira.isoformat(),
            },
        )
        resp.raise_for_status()
        return resp.json()["init_point"]
