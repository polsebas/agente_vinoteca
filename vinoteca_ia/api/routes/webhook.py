"""Webhooks de Mercado Pago y WhatsApp."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from core.orchestrator import get_orchestrator
from schemas.api import WhatsAppInbound
from schemas.order import EstadoOrden
from storage.immutable_log import registrar
from storage.postgres import execute, fetch_all, fetchrow

logger = logging.getLogger("vinoteca.api.webhook")

router = APIRouter()

_ESTADOS_TERMINALES = {
    EstadoOrden.PAGADA.value,
    EstadoOrden.FALLIDA.value,
    EstadoOrden.CANCELADA.value,
}


@router.post("/webhook", status_code=status.HTTP_200_OK, tags=["Pagos"])
@router.post("/webhook/mercadopago", status_code=status.HTTP_200_OK, tags=["Pagos"])
async def mercadopago_webhook(request: Request) -> JSONResponse:
    """Receptor de callbacks de Mercado Pago (real o mock)."""
    es_mock = os.environ.get("MERCADOPAGO_MOCK_ENABLED", "true").lower() == "true"
    external_ref, mp_status = await _extraer_mp(request, es_mock)
    if es_mock and not external_ref:
        mp_status = request.query_params.get("status", mp_status or "approved")
        external_ref = request.query_params.get("external_reference", "")
    if not external_ref:
        return JSONResponse({"ok": False, "detail": "external_reference inválido"}, status_code=400)
    return await _procesar_resultado(external_ref, mp_status or "approved")


@router.post("/webhook/whatsapp", status_code=status.HTTP_200_OK, tags=["WhatsApp"])
async def whatsapp_webhook(request: Request) -> JSONResponse:
    """Inbound WhatsApp: rutea por el orquestador y responde el texto."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "detail": "Payload inválido"}, status_code=400)

    texto, session_id, cliente_id = _extraer_whatsapp(body)
    if not texto:
        return JSONResponse({"ok": True, "detail": "Evento ignorado"})

    orch = get_orchestrator()
    resp = await orch.process_turn(
        session_id,
        texto,
        canal="whatsapp",
        cliente_id=cliente_id,
    )
    return JSONResponse(
        {
            "ok": True,
            "session_id": resp.session_id,
            "respuesta": resp.respuesta,
            "agente": resp.agente,
            "correlation_id": resp.correlation_id,
        },
        headers={"X-Correlation-ID": resp.correlation_id},
    )


async def _extraer_mp(request: Request, es_mock: bool) -> tuple[str, str]:
    q_ref = request.query_params.get("external_reference", "")
    q_status = request.query_params.get("status", "")
    if q_ref:
        return q_ref, q_status or "approved"
    try:
        body = await request.json()
    except Exception:
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    action = str(body.get("action") or "")
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    ref = str(body.get("external_reference") or "") or str(data.get("external_reference") or "")
    mp_status = str(body.get("status") or data.get("status") or "")
    if not es_mock and action and action not in ("payment.created", "payment.updated") and not ref:
        return "", ""
    return ref, mp_status


def _extraer_whatsapp(body: dict) -> tuple[str, str, str | None]:
    inbound = WhatsAppInbound.model_validate(body)
    texto = (inbound.mensaje or inbound.text or "").strip()
    session_id = inbound.session_id or inbound.from_number or ""
    if texto:
        return texto, session_id or "wa-anon", inbound.from_number

    try:
        msg = body["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError, TypeError):
        return "", "", None
    texto = str((msg.get("text") or {}).get("body") or "").strip()
    from_num = str(msg.get("from") or "wa-anon")
    return texto, f"wa_{from_num}", from_num


async def _procesar_resultado(external_ref: str, mp_status: str) -> JSONResponse:
    pedido = await _buscar_pedido(external_ref)
    if not pedido:
        return JSONResponse({"ok": False, "detail": "Pedido no encontrado"}, status_code=404)

    pedido_id = str(pedido["id"])
    estado_actual = str(pedido["estado"])
    aprobado = mp_status in {"approved", "accredited"}
    nuevo_estado = EstadoOrden.PAGADA.value if aprobado else EstadoOrden.FALLIDA.value

    if estado_actual in _ESTADOS_TERMINALES:
        return JSONResponse(
            {
                "ok": True,
                "pedido_id": pedido_id,
                "estado": estado_actual,
                "idempotent": True,
            }
        )

    await execute(
        "UPDATE pedidos SET estado = $1 WHERE id = $2",
        nuevo_estado,
        pedido_id,
    )
    await _ajustar_reservas(pedido_id, aprobado=aprobado)
    await registrar(
        f"pago_{mp_status}",
        pedido_id=pedido_id,
        session_id=pedido["session_id"],
        payload={"external_reference": external_ref, "mp_status": mp_status},
    )
    return JSONResponse({"ok": True, "pedido_id": pedido_id, "estado": nuevo_estado})


async def _buscar_pedido(external_ref: str) -> object | None:
    candidatos: list[str] = []
    if external_ref.startswith("vnt_"):
        resto = external_ref.split("_", 1)[1]
        candidatos.extend([resto, external_ref])
    candidatos.append(external_ref)
    seen: set[str] = set()
    for cid in candidatos:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        try:
            pedido = await fetchrow(
                "SELECT id, estado, session_id FROM pedidos WHERE id = $1",
                cid,
            )
        except Exception:
            continue
        if pedido:
            return pedido
    return None


async def _ajustar_reservas(pedido_id: str, *, aprobado: bool) -> None:
    """PAGADA consume `reservado`; FALLIDA restaura disponible."""
    try:
        lineas = await fetch_all(
            "SELECT producto_id, cantidad FROM pedido_lineas WHERE pedido_id = $1",
            pedido_id,
        )
    except Exception as exc:
        logger.warning("No se pudieron leer líneas de %s: %s", pedido_id, exc)
        return
    for linea in lineas:
        pid = str(linea["producto_id"])
        qty = int(linea["cantidad"])
        if aprobado:
            await execute(
                """
                UPDATE stock
                SET reservado = GREATEST(reservado - $1, 0),
                    updated_at = NOW()
                WHERE producto_id = $2
                """,
                qty,
                pid,
            )
        else:
            await execute(
                """
                UPDATE stock
                SET cantidad_disponible = cantidad_disponible + $1,
                    reservado = GREATEST(reservado - $1, 0),
                    updated_at = NOW()
                WHERE producto_id = $2
                """,
                qty,
                pid,
            )
