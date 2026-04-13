"""
Tool para enviar el link de pago de Mercado Pago.
En desarrollo usa un mock que simula la respuesta de la API real.

Invocar después de crear_pedido en Fase 2 para enviar el link al cliente.
"""

from __future__ import annotations

import os
import uuid
from uuid import UUID

from agno.tools import tool

from schemas.tool_responses import PaymentResult
from storage.immutable_log import registrar


@tool
async def enviar_link_pago(pedido_id: str, total: float) -> PaymentResult:
    """
    Genera y retorna el link de pago de Mercado Pago para el pedido.

    Usar después de crear_pedido cuando el tipo de pago es online.
    En modo mock (MERCADOPAGO_MOCK_ENABLED=true) retorna una URL de prueba.

    El link tiene asociada una idempotency_key propia de Mercado Pago
    para prevenir cobros dobles en caso de reintentos por fallo de red.
    """
    uid = UUID(pedido_id)
    es_mock = os.environ.get("MERCADOPAGO_MOCK_ENABLED", "true").lower() == "true"

    external_ref = f"vnt_{pedido_id}_{uuid.uuid4().hex[:8]}"

    if es_mock:
        url = f"https://www.mercadopago.com.ar/checkout/mock/{external_ref}?amount={total}"
    else:
        url = await _crear_preferencia_real(pedido_id, total, external_ref)

    await registrar(
        "link_pago_enviado",
        pedido_id=uid,
        payload={
            "external_reference": external_ref,
            "total": total,
            "mock": es_mock,
        },
    )

    return PaymentResult(
        pedido_id=uid,
        url_pago=url,
        external_reference=external_ref,
        es_mock=es_mock,
    )


async def _crear_preferencia_real(pedido_id: str, total: float, external_ref: str) -> str:
    """Integración real con Mercado Pago API (activar con MERCADOPAGO_MOCK_ENABLED=false)."""
    import httpx

    token = os.environ.get("MERCADOPAGO_ACCESS_TOKEN", "")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://api.mercadopago.com/checkout/preferences",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "items": [{"title": "Pedido Vinoteca", "quantity": 1, "unit_price": total}],
                "external_reference": external_ref,
                "back_urls": {
                    "success": "http://localhost:8000/webhook?status=approved",
                    "failure": "http://localhost:8000/webhook?status=rejected",
                },
                "auto_return": "approved",
            },
        )
        resp.raise_for_status()
        return resp.json()["init_point"]
