"""Creación de orden (Fase 2 del 2PC). Mutación atómica + log inmutable."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import asyncpg
from agno.tools import tool

from core.idempotency import IdempotencyManager
from schemas.order import (
    ConfirmedOrder,
    LineaPedidoSolicitud,
    OrderLineItem,
    TipoEntrega,
)
from schemas.tool_responses import CreateOrderResponse, ResultadoTool
from storage.immutable_log import log_transaction_event
from storage.postgres import get_pool
from tools.orders.calculate_order import COSTO_ENVIO, UMBRAL_ENVIO_GRATIS, _descuento_volumen


def _parse_lineas(lineas: list) -> list[LineaPedidoSolicitud] | str:
    if not lineas:
        return "Debe proveer al menos una línea."
    try:
        parsed: list[LineaPedidoSolicitud] = []
        for line in lineas:
            if isinstance(line, LineaPedidoSolicitud):
                parsed.append(line)
            else:
                parsed.append(LineaPedidoSolicitud.model_validate(line))
        return parsed
    except (KeyError, ValueError, TypeError) as exc:
        return f"Líneas mal formadas: {exc}"


@tool(requires_confirmation=True)
async def crear_orden(
    session_id: str,
    cliente_id: str | None,
    lineas: list[LineaPedidoSolicitud],
    costo_envio_ars: float = 0.0,
    tipo_entrega: TipoEntrega = TipoEntrega.ENVIO_DOMICILIO,
    idempotency_key: str | None = None,
) -> CreateOrderResponse:
    """Persistir el pedido, descontar stock y loguear. Requiere HitL.

    Último paso del 2PC, solo después de `verificar_stock_exacto` + `calcular_orden`
    y confirmación explícita. Idempotente: Redis + UNIQUE `idempotency_key`.

    Args:
        session_id: sesión de chat.
        cliente_id: cliente registrado o None (invitado).
        lineas: producto_id + cantidad.
        costo_envio_ars: costo de envío ya calculado (0 = retiro o umbral).
        tipo_entrega: domicilio o retiro.
        idempotency_key: si viene vacía se deriva de sesión+líneas.
    """
    parsed = _parse_lineas(lineas)
    if isinstance(parsed, str):
        return CreateOrderResponse(resultado=ResultadoTool.ERROR, mensaje=parsed)

    items = [(sol.producto_id, sol.cantidad) for sol in parsed]
    idem = IdempotencyManager()
    idem_key = idempotency_key or IdempotencyManager.build_key(
        "crear_orden",
        session_id,
        cliente_id or "invitado",
        "|".join(f"{pid}:{q}" for pid, q in items),
    )
    try:
        cached = await idem.get(idem_key)
        if cached and cached.status == "ok":
            return CreateOrderResponse.model_validate_json(cached.resultado_json)
    except Exception:
        cached = None

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    "SELECT id FROM pedidos WHERE idempotency_key = $1",
                    idem_key,
                )
                if existing is not None:
                    return await _rehidratar(conn, str(existing["id"]))

                ids = [pid for pid, _ in items]
                rows = await conn.fetch(
                    """
                    SELECT id::text AS id, nombre, precio, activo
                    FROM vinos
                    WHERE id = ANY($1::text[])
                    """,
                    ids,
                )
                por_id = {str(r["id"]): r for r in rows}
                if len(por_id) != len(set(ids)):
                    return CreateOrderResponse(
                        resultado=ResultadoTool.ERROR,
                        mensaje="Uno o más vinos no existen.",
                    )

                stock_rows = await conn.fetch(
                    """
                    SELECT producto_id,
                           COALESCE(cantidad_disponible, 0) AS cantidad_disponible,
                           COALESCE(reservado, 0) AS reservado
                    FROM stock
                    WHERE producto_id = ANY($1::text[])
                    FOR UPDATE
                    """,
                    ids,
                )
                stock_map = {str(r["producto_id"]): r for r in stock_rows}
                for pid, cantidad in items:
                    st = stock_map.get(pid)
                    disponible = 0
                    if st is not None:
                        disponible = int(st["cantidad_disponible"]) - int(st["reservado"])
                    if disponible < cantidad:
                        return CreateOrderResponse(
                            resultado=ResultadoTool.ERROR,
                            mensaje=f"Stock insuficiente al confirmar {pid}.",
                        )

                lineas_orden: list[OrderLineItem] = []
                subtotal = Decimal("0")
                botellas = 0
                for pid, cantidad in items:
                    row = por_id[pid]
                    precio_raw = row["precio"]
                    if not row["activo"] or precio_raw is None or Decimal(str(precio_raw)) <= 0:
                        return CreateOrderResponse(
                            resultado=ResultadoTool.ERROR,
                            mensaje=f"Producto {pid} inactivo o sin precio válido.",
                        )
                    precio_u = Decimal(str(row["precio"])).quantize(Decimal("0.01"))
                    sub = (precio_u * Decimal(cantidad)).quantize(Decimal("0.01"))
                    subtotal += sub
                    botellas += cantidad
                    lineas_orden.append(
                        OrderLineItem(
                            producto_id=pid,
                            nombre=row["nombre"] or pid,
                            cantidad=cantidad,
                            precio_unitario=precio_u,
                            subtotal=sub,
                        )
                    )

                descuento = _descuento_volumen(botellas, subtotal)
                base = subtotal - descuento
                if tipo_entrega == TipoEntrega.RETIRO_LOCAL or base >= UMBRAL_ENVIO_GRATIS:
                    envio = Decimal("0.00")
                else:
                    envio = Decimal(str(costo_envio_ars or COSTO_ENVIO)).quantize(Decimal("0.01"))
                total = (base + envio).quantize(Decimal("0.01"))
                order_id = f"PED-{uuid4().hex[:8]}"

                for pid, cantidad in items:
                    result = await conn.execute(
                        """
                        UPDATE stock
                        SET cantidad_disponible = cantidad_disponible - $1,
                            reservado = reservado + $1,
                            updated_at = NOW()
                        WHERE producto_id = $2
                          AND (cantidad_disponible - COALESCE(reservado, 0)) >= $1
                        """,
                        cantidad,
                        pid,
                    )
                    if not str(result).endswith(" 1"):
                        return CreateOrderResponse(
                            resultado=ResultadoTool.ERROR,
                            mensaje=f"Stock insuficiente al confirmar {pid}.",
                        )

                await conn.execute(
                    """
                    INSERT INTO pedidos (
                        id, session_id, cliente_id, estado, total, subtotal,
                        descuento, costo_envio, tipo_entrega, idempotency_key, created_at
                    ) VALUES ($1,$2,$3,'aprobada',$4,$5,$6,$7,$8,$9, NOW())
                    """,
                    order_id,
                    session_id,
                    cliente_id,
                    total,
                    subtotal,
                    descuento,
                    envio,
                    tipo_entrega.value,
                    idem_key,
                )
                for linea in lineas_orden:
                    await conn.execute(
                        """
                        INSERT INTO pedido_lineas (
                            pedido_id, producto_id, nombre, cantidad,
                            precio_unitario, subtotal
                        ) VALUES ($1,$2,$3,$4,$5,$6)
                        """,
                        order_id,
                        linea.producto_id,
                        linea.nombre,
                        linea.cantidad,
                        linea.precio_unitario,
                        linea.subtotal,
                    )

                order = ConfirmedOrder(
                    id=order_id,
                    session_id=session_id,
                    cliente_id=cliente_id,
                    lineas=lineas_orden,
                    total=total,
                    tipo_entrega=tipo_entrega,
                    idempotency_key=idem_key,
                )
    except asyncpg.UniqueViolationError:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM pedidos WHERE idempotency_key = $1",
                idem_key,
            )
            if row:
                return await _rehidratar(conn, str(row["id"]))
        return CreateOrderResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="Conflicto de idempotencia sin pedido recuperable.",
        )

    await log_transaction_event(
        session_id=session_id,
        accion="crear_orden",
        payload=order,
        idempotency_key=idem_key,
        resultado="ok",
        metadata={"pedido_id": order.id},
    )
    response = CreateOrderResponse(resultado=ResultadoTool.OK, order=order)
    try:
        await idem.put(idem_key, response.model_dump_json(), status="ok")
    except Exception:
        pass
    return response


async def _rehidratar(conn, pedido_id: str) -> CreateOrderResponse:
    cab = await conn.fetchrow(
        """
        SELECT id, session_id, cliente_id, total, tipo_entrega, idempotency_key, payment_link
        FROM pedidos WHERE id = $1
        """,
        pedido_id,
    )
    if cab is None:
        return CreateOrderResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="Pedido idempotente no recuperable.",
        )
    lineas_rows = await conn.fetch(
        """
        SELECT producto_id, nombre, cantidad, precio_unitario, subtotal
        FROM pedido_lineas WHERE pedido_id = $1
        """,
        pedido_id,
    )
    tipo = TipoEntrega.ENVIO_DOMICILIO
    try:
        if cab["tipo_entrega"]:
            tipo = TipoEntrega(cab["tipo_entrega"])
    except ValueError:
        pass
    order = ConfirmedOrder(
        id=str(cab["id"]),
        session_id=cab["session_id"] or "",
        cliente_id=cab["cliente_id"],
        lineas=[
            OrderLineItem(
                producto_id=str(r["producto_id"]),
                nombre=r["nombre"] or "",
                cantidad=int(r["cantidad"]),
                precio_unitario=Decimal(str(r["precio_unitario"])),
                subtotal=Decimal(str(r["subtotal"])),
            )
            for r in lineas_rows
        ],
        total=Decimal(str(cab["total"])),
        tipo_entrega=tipo,
        idempotency_key=cab["idempotency_key"] or "",
        payment_link=cab["payment_link"],
    )
    return CreateOrderResponse(resultado=ResultadoTool.OK, order=order, mensaje="idempotent_replay")
