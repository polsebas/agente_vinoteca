"""Fallback determinista cuando el proveedor LLM no está disponible.

Cubre ruteo por heurística y especialistas vía tools SQL/RAG, sin inventar
precios ni stock. Se usa solo ante fallos de billing/proveedor.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from schemas.agent_io import AgenteDestino, AgentResponse, IntentClass, RouterOutput, SessionRequest
from schemas.order import CalculatedOrder
from schemas.session_state import SessionState
from schemas.tool_responses import ResultadoTool

logger = logging.getLogger("vinoteca.llm_fallback")

_PENDING_CALCULATED: dict[str, CalculatedOrder] = {}

_PROVIDER_MARKERS = (
    "429",
    "insufficient_quota",
    "credit",
    "rate limit",
    "too many requests",
    "no credits",
    "credit balance",
    "invalid_api_key",
    "authentication",
    "model provider",
    "error in agent run",
    "anthropic",
    "openai",
)


def is_provider_failure_text(text: str) -> bool:
    blob = (text or "").lower()
    return any(marker in blob for marker in _PROVIDER_MARKERS)


def is_provider_failure(exc: BaseException) -> bool:
    parts: list[str] = []
    current: BaseException | None = exc
    seen = 0
    while current is not None and seen < 6:
        parts.append(str(current))
        parts.append(repr(current))
        parts.extend(str(arg) for arg in getattr(current, "args", ()))
        current = current.__cause__ or current.__context__
        seen += 1
    return is_provider_failure_text(" ".join(parts))


def heuristic_route(mensaje: str) -> RouterOutput:
    """Clasifica sin LLM. Conservador: si no hay señal clara, pide aclaración."""
    texto = mensaje.lower()
    if re.search(r"\bconfirmo\b|\bconfirmá\b|\bconfirmame\b", texto):
        return _route(IntentClass.PEDIDO_DELIVERY, AgenteDestino.ORDERS, "confirmación 2PC")
    if re.search(r"\d+\s*botellas?|\bme quedo\b|\bagregá\b|\bcomprar\b|\bpedido\b", texto):
        return _route(IntentClass.PEDIDO_DELIVERY, AgenteDestino.ORDERS, "intención de compra")
    if re.search(r"cuesta|stock|precio|cu[aá]nto\s+(sale|cuesta|tienen)", texto):
        return _route(
            IntentClass.CONSULTA_STOCK_PRECIO,
            AgenteDestino.INVENTORY,
            "consulta transaccional",
        )
    if re.search(r"cata|degustaci[oó]n|evento", texto):
        return _route(IntentClass.EVENTO_DEGUSTACION, AgenteDestino.EVENTS, "eventos")
    if re.search(r"reclamo|reembolso|no lleg[oó]|queja", texto):
        return _route(IntentClass.SOPORTE_RECLAMO, AgenteDestino.SUPPORT, "soporte")
    if re.search(
        r"asado|recomend|maridaje|regalo|tinto|vino para|qu[eé] vino",
        texto,
    ):
        intent = (
            IntentClass.MARIDAJE
            if "asado" in texto or "maridaje" in texto
            else IntentClass.RECOMENDACION_OCASION
        )
        return _route(intent, AgenteDestino.SOMMELIER, "recomendación / maridaje")
    return RouterOutput(
        intencion=IntentClass.DESCONOCIDO,
        confianza=0.4,
        agente_destino=AgenteDestino.NINGUNO,
        razonamiento="sin señal clara",
        accion_nula=True,
        pregunta_aclaracion=(
            "¿Me podés contar un poco más para ayudarte mejor? "
            "Por ejemplo, ¿estás buscando un vino para regalar, para tomar en casa, "
            "o querés saber el precio de uno específico?"
        ),
    )


def _route(intent: IntentClass, dest: AgenteDestino, razon: str) -> RouterOutput:
    return RouterOutput(
        intencion=intent,
        confianza=0.9,
        agente_destino=dest,
        razonamiento=razon,
        accion_nula=False,
    )


async def run_deterministic_specialist(
    request: SessionRequest,
    state: SessionState,
    *,
    agente_nombre: str,
    intencion: IntentClass,
    last_calculated: dict[str, CalculatedOrder],
) -> AgentResponse:
    """Ejecuta tools SQL/RAG sin pasar por el LLM del especialista."""
    if agente_nombre == "agente_inventario":
        return await _inventory(request, intencion)
    if agente_nombre == "agente_sommelier":
        return await _sommelier(request, intencion)
    if agente_nombre == "agente_orders":
        return await _orders(request, state, intencion, last_calculated)
    if agente_nombre == "agente_events":
        return AgentResponse(
            session_id=request.session_id,
            correlation_id=request.correlation_id,
            respuesta=(
                "Puedo ayudarte con catas y eventos apenas recupere el modelo. "
                "Mientras tanto escribinos al local para reservar."
            ),
            agente=agente_nombre,
            intencion=intencion,
            metadata={"fallback": "provider"},
        )
    return AgentResponse(
        session_id=request.session_id,
        correlation_id=request.correlation_id,
        respuesta="Te derivo con un humano para resolverlo. Disculpá la demora.",
        agente=agente_nombre,
        intencion=intencion,
        metadata={"fallback": "provider", "escalado": "true"},
    )


async def _inventory(request: SessionRequest, intencion: IntentClass) -> AgentResponse:
    from tools.catalog.consult_price import consultar_precio
    from tools.catalog.consult_stock import consultar_stock

    nombre = _etiqueta(request.mensaje) or "Achaval Ferrer Malbec"
    precio = await consultar_precio.entrypoint(nombre=nombre)
    stock = await consultar_stock.entrypoint(nombre=nombre)
    if not precio.items:
        texto = f"No encontré precio vigente para «{nombre}». Lo verifico con el local."
        return AgentResponse(
            session_id=request.session_id,
            correlation_id=request.correlation_id,
            respuesta=texto,
            agente="agente_inventario",
            intencion=intencion,
            metadata={"fallback": "provider"},
        )
    item = _prefer_exact(precio.items, nombre)
    unidades = next(
        (s.cantidad for s in stock.items if s.vino_id == item.vino_id),
        stock.items[0].cantidad if stock.items else 0,
    )
    texto = (
        f"{item.nombre} {item.anada or ''} está a ${item.precio_ars} ARS "
        f"y hay {unidades} botellas disponibles (dato SQL)."
    )
    return AgentResponse(
        session_id=request.session_id,
        correlation_id=request.correlation_id,
        respuesta=texto,
        agente="agente_inventario",
        intencion=intencion,
        metadata={"fallback": "provider", "producto_id": str(item.vino_id)},
    )


async def _sommelier(request: SessionRequest, intencion: IntentClass) -> AgentResponse:
    from core.rag.memgraph_adapter import query_memgraph_rag
    from schemas.customer_profile import PerfilClienteTipo
    from storage.postgres import fetch_all

    tope = _presupuesto(request.mensaje) or Decimal("15000")
    rows = await fetch_all(
        """
        SELECT v.id::text AS id, v.nombre, v.bodega, v.precio, v.anada,
               GREATEST(COALESCE(s.cantidad_disponible,0)-COALESCE(s.reservado,0),0) AS stock
        FROM vinos v
        JOIN stock s ON s.producto_id = v.id
        WHERE v.activo = TRUE
          AND v.precio > 0 AND v.precio <= $1
          AND GREATEST(COALESCE(s.cantidad_disponible,0)-COALESCE(s.reservado,0),0) > 0
          AND (
                v.varietal ILIKE '%malbec%'
                OR v.varietal ILIKE '%tinto%'
                OR v.nombre ILIKE '%malbec%'
                OR v.id LIKE 'achaval%'
                OR v.id LIKE 'luigi-bosca%'
                OR v.id LIKE 'zuccardi%'
          )
        ORDER BY CASE
                   WHEN v.id LIKE 'achaval-ferrer-malbec%' THEN 0
                   WHEN v.id LIKE 'luigi-bosca-d-o-c%' THEN 1
                   WHEN v.id LIKE 'zuccardi%' THEN 2
                   ELSE 3
                 END,
                 v.precio ASC
        LIMIT 3
        """,
        tope,
    )
    if not rows:
        return AgentResponse(
            session_id=request.session_id,
            correlation_id=request.correlation_id,
            respuesta="Ahora mismo no tengo tintos en stock dentro de ese presupuesto.",
            agente="agente_sommelier",
            intencion=intencion,
            metadata={"fallback": "provider"},
        )
    contexto = ""
    try:
        frags = await query_memgraph_rag(
            request.mensaje,
            perfil_cliente=PerfilClienteTipo.OCASION,
            top_k=3,
        )
        if frags:
            contexto = " " + frags[0].contenido[:220]
    except Exception:
        logger.exception("RAG fallback sommelier")
    lineas = []
    for row in rows:
        lineas.append(
            f"- {row['nombre']} ({row['bodega']}, {row['anada']}): "
            f"${Decimal(str(row['precio'])):,.0f} ARS, {row['stock']} u."
        )
    texto = (
        "Para el asado, con presupuesto de "
        f"${tope:,.0f} ARS, te armo estas opciones con stock SQL:"
        f"\n"
        + "\n".join(lineas)
        + contexto
        + " Si te copa alguna, decime cuántas botellas y lo preparamos."
    )
    return AgentResponse(
        session_id=request.session_id,
        correlation_id=request.correlation_id,
        respuesta=texto,
        agente="agente_sommelier",
        intencion=intencion,
        metadata={"fallback": "provider"},
    )


async def _orders(
    request: SessionRequest,
    state: SessionState,
    intencion: IntentClass,
    last_calculated: dict[str, CalculatedOrder],
) -> AgentResponse:
    from tools.orders.calculate_order import calcular_orden
    from tools.orders.create_order import crear_orden
    from tools.orders.send_payment_link import enviar_link_pago
    from tools.orders.verify_stock_exact import verificar_stock_exacto

    texto = request.mensaje.lower()
    if re.search(r"\bconfirmo\b", texto):
        pending = (
            last_calculated.get(request.session_id)
            or _PENDING_CALCULATED.get(request.session_id)
            or state.pedido_en_preparacion
        )
        if pending is None or not pending.lineas:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta="No tengo un pedido preparado. Decime el vino y la cantidad primero.",
                agente="agente_orders",
                intencion=intencion,
                metadata={"fallback": "provider"},
            )
        lineas = [{"producto_id": ln.producto_id, "cantidad": ln.cantidad} for ln in pending.lineas]
        created = await crear_orden.entrypoint(
            session_id=request.session_id,
            cliente_id=request.cliente_id,
            lineas=lineas,
            costo_envio_ars=float(pending.costo_envio),
            tipo_entrega=pending.tipo_entrega,
        )
        last_calculated.pop(request.session_id, None)
        _PENDING_CALCULATED.pop(request.session_id, None)
        if created.resultado != ResultadoTool.OK or created.order is None:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=created.mensaje or "No pude confirmar el pedido.",
                agente="agente_orders",
                intencion=intencion,
                metadata={"fallback": "provider"},
            )
        link = await enviar_link_pago.entrypoint(created.order.id)
        pago = link.payment_link or ""
        msg = (
            f"Pedido {created.order.id} confirmado. Total ${created.order.total:,.2f} ARS. "
            f"Stock reservado. Pagá acá: {pago}"
        )
        return AgentResponse(
            session_id=request.session_id,
            correlation_id=request.correlation_id,
            respuesta=msg,
            agente="agente_orders",
            intencion=intencion,
            metadata={
                "fallback": "provider",
                "order_id": created.order.id,
            },
        )

    producto_id, nombre = await _resolver_vino(request.mensaje)
    cantidad = _cantidad(request.mensaje)
    if not producto_id:
        return AgentResponse(
            session_id=request.session_id,
            correlation_id=request.correlation_id,
            respuesta="Decime qué vino y cuántas botellas para armarte el total.",
            agente="agente_orders",
            intencion=intencion,
            metadata={"fallback": "provider"},
        )
    lineas = [{"producto_id": producto_id, "cantidad": cantidad}]
    stock = await verificar_stock_exacto.entrypoint(
        session_id=request.session_id,
        lineas=lineas,
    )
    if stock.resultado != ResultadoTool.OK or not stock.todos_disponibles:
        return AgentResponse(
            session_id=request.session_id,
            correlation_id=request.correlation_id,
            respuesta=stock.mensaje or f"No hay stock suficiente de {nombre}.",
            agente="agente_orders",
            intencion=intencion,
            metadata={"fallback": "provider"},
        )
    calc = await calcular_orden.entrypoint(lineas=lineas)
    if calc.resultado != ResultadoTool.OK or calc.order is None:
        return AgentResponse(
            session_id=request.session_id,
            correlation_id=request.correlation_id,
            respuesta=calc.mensaje or "No pude calcular el total.",
            agente="agente_orders",
            intencion=intencion,
            metadata={"fallback": "provider"},
        )
        last_calculated[request.session_id] = calc.order
    _PENDING_CALCULATED[request.session_id] = calc.order
    o = calc.order
    msg = (
        f"Fase 1 lista (sin descontar stock). {cantidad}× {nombre}: "
        f"subtotal ${o.subtotal:,.2f}, envío ${o.costo_envio:,.2f}, "
        f"total ${o.total:,.2f} ARS. ¿Confirmás el pedido?"
    )
    return AgentResponse(
        session_id=request.session_id,
        correlation_id=request.correlation_id,
        respuesta=msg,
        agente="agente_orders",
        intencion=intencion,
        requiere_aprobacion=True,
        finalizado=False,
        metadata={"fallback": "provider"},
    )


def _etiqueta(mensaje: str) -> str | None:
    match = re.search(
        r"(achaval\s+ferrer(?:\s+malbec)?|luigi\s+bosca(?:\s+d\.?o\.?c\.?)?|"
        r"zuccardi(?:\s+valle)?(?:\s+tempranillo)?|catena(?:\s+zapata)?(?:\s+adrianna)?)",
        mensaje,
        re.I,
    )
    return match.group(1) if match else None


def _prefer_exact(items, nombre: str):
    needle = nombre.lower()
    for item in items:
        if item.nombre.lower() == needle:
            return item
    return items[0]


def _presupuesto(mensaje: str) -> Decimal | None:
    match = re.search(r"\$\s*([\d\.]+)", mensaje)
    if not match:
        match = re.search(r"(\d[\d\.]{3,})\s*(?:pesos|ars)?", mensaje, re.I)
    if not match:
        return None
    raw = match.group(1).replace(".", "")
    try:
        return Decimal(raw)
    except Exception:
        return None


def _cantidad(mensaje: str) -> int:
    match = re.search(r"(\d+)\s*botellas?", mensaje, re.I)
    if match:
        return max(1, int(match.group(1)))
    return 1


async def _resolver_vino(mensaje: str) -> tuple[str | None, str]:
    from storage.postgres import fetchrow

    etiqueta = _etiqueta(mensaje) or "Achaval Ferrer Malbec"
    row = await fetchrow(
        """
        SELECT id::text AS id, nombre
        FROM vinos
        WHERE activo = TRUE AND nombre ILIKE $1
        ORDER BY CASE WHEN id LIKE 'achaval-ferrer-malbec%' THEN 0 ELSE 1 END, precio ASC
        LIMIT 1
        """,
        f"%{etiqueta}%",
    )
    if row is None:
        return None, etiqueta
    return str(row["id"]), str(row["nombre"])
