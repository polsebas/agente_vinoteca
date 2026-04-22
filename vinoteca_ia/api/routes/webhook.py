"""
POST /webhook — receptor de notificaciones de Mercado Pago (real o mock).
Actualiza el estado del pedido según el resultado del pago.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from schemas.order import EstadoOrden
from storage.immutable_log import registrar
from storage.postgres import execute, fetchrow

router = APIRouter()


class MPWebhookPayload(BaseModel):
    type: str | None = None
    action: str | None = None
    data: dict | None = None
    external_reference: str | None = None
    status: str | None = None


@router.post("/webhook", status_code=status.HTTP_200_OK, tags=["Pagos"])
async def mercadopago_webhook(request: Request) -> JSONResponse:
    """
    Receptor de callbacks de Mercado Pago.
    En modo mock acepta GET /webhook?status=approved&external_reference=...
    """
    es_mock = os.environ.get("MERCADOPAGO_MOCK_ENABLED", "true").lower() == "true"

    if es_mock:
        mp_status = request.query_params.get("status", "approved")
        external_ref = request.query_params.get("external_reference", "")
        return await _procesar_resultado(external_ref, mp_status)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "detail": "Payload inválido"}, status_code=400)

    action = body.get("action", "")
    if action not in ("payment.created", "payment.updated"):
        return JSONResponse({"ok": True, "detail": "Evento ignorado"})

    payment_data = body.get("data", {})
    external_ref = payment_data.get("external_reference", "")
    mp_status = payment_data.get("status", "")

    return await _procesar_resultado(external_ref, mp_status)


async def _procesar_resultado(external_ref: str, mp_status: str) -> JSONResponse:
    if not external_ref or not external_ref.startswith("vnt_"):
        return JSONResponse({"ok": False, "detail": "external_reference inválido"}, status_code=400)

    partes = external_ref.split("_")
    if len(partes) < 2:
        return JSONResponse({"ok": False, "detail": "Formato de referencia inválido"}, status_code=400)

    pedido_id_str = partes[1]

    try:
        pedido = await fetchrow(
            "SELECT id, estado, session_id FROM pedidos WHERE id = $1::uuid",
            pedido_id_str,
        )
    except Exception:
        return JSONResponse({"ok": False, "detail": "Pedido no encontrado"}, status_code=404)

    if not pedido:
        return JSONResponse({"ok": False, "detail": "Pedido no encontrado"}, status_code=404)

    nuevo_estado = (
        EstadoOrden.PAGADA.value if mp_status == "approved" else EstadoOrden.FALLIDA.value
    )

    await execute(
        "UPDATE pedidos SET estado = $1, updated_at = NOW() WHERE id = $2",
        nuevo_estado,
        pedido["id"],
    )

    await registrar(
        f"pago_{mp_status}",
        pedido_id=pedido["id"],
        session_id=pedido["session_id"],
        payload={"external_reference": external_ref, "mp_status": mp_status},
    )

    return JSONResponse({"ok": True, "pedido_id": str(pedido["id"]), "estado": nuevo_estado})
