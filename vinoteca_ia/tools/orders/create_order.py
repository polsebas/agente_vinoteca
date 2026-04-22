"""Creación de orden (Fase 1 del Two-Phase Commit).

Esta es una tool MUTATIVA: pasa el agente a estado "requiere confirmación"
antes de ejecutarse. El agente devolverá la respuesta, el servidor pausará
el run, y solo tras `/pedido/{id}/aprobar` el run se reanuda con
`acontinue_run()` para invocar `enviar_link_pago`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from agno.tools import tool

from core.idempotency import IdempotencyManager
from schemas.order import Order, OrderLine
from schemas.tool_responses import CreateOrderResponse, ResultadoTool
from storage.postgres import get_pool


@tool(requires_confirmation=True)
async def crear_orden(
    session_id: str,
    cliente_id: str | None,
    lineas: list[dict[str, str | int]],
    costo_envio_ars: float = 0.0,
) -> CreateOrderResponse:
    """Persistir un pedido en estado PREPARADA. Requiere confirmación explícita.

    Usá esta tool SOLO después de que:
    1. `verificar_stock_exacto` haya devuelto `todos_disponibles=True`.
    2. `calcular_orden` haya devuelto un total coherente.
    3. El cliente haya visto el resumen completo y dicho "sí" textualmente.

    Esta tool tiene `requires_confirmation=True`: el framework pausará el
    run antes de ejecutarla y lo reanudará solo tras la aprobación humana.
    NO la uses para "pedir confirmación al cliente" — pedir confirmación
    es parte del mensaje natural del agente; esta tool ES la ejecución.

    La idempotencia se calcula sobre (session_id, cliente_id, lineas) para
    que si el cliente vuelve a pedir "ok confirmá", no se cree una orden
    duplicada.

    Args:
        session_id: ID de la sesión de conversación.
        cliente_id: ID del cliente registrado (puede ser None para invitados).
        lineas: Lista de `{"vino_id": "<uuid>", "cantidad": <int>}`.
        costo_envio_ars: Costo de envío en ARS.

    Returns:
        CreateOrderResponse con la Order creada en estado PREPARADA.
    """
    if not lineas:
        return CreateOrderResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="Debe proveer al menos una línea.",
        )

    try:
        items: list[tuple[UUID, int]] = [
            (UUID(str(line["vino_id"])), int(line["cantidad"]))
            for line in lineas
        ]
    except (KeyError, ValueError) as exc:
        return CreateOrderResponse(
            resultado=ResultadoTool.ERROR,
            mensaje=f"Líneas mal formadas: {exc}",
        )

    idem = IdempotencyManager()
    idem_key = IdempotencyManager.build_key(
        "crear_orden",
        session_id,
        cliente_id or "invitado",
        "|".join(f"{vid}:{q}" for vid, q in items),
    )
    cached = await idem.get(idem_key)
    if cached and cached.status == "ok":
        return CreateOrderResponse.model_validate_json(cached.resultado_json)

    now = datetime.now(UTC)
    vino_ids = [vid for vid, _ in items]

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT id, nombre, precio_ars
                FROM vinos
                WHERE id = ANY($1::uuid[]) AND activo = TRUE
                """,
                vino_ids,
            )
            por_id = {row["id"]: row for row in rows}
            if len(por_id) != len(items):
                return CreateOrderResponse(
                    resultado=ResultadoTool.ERROR,
                    mensaje="Uno o más vinos no existen o están inactivos.",
                )

            reservas_rows = await conn.fetch(
                """
                SELECT reserva_id, vino_id, cantidad, expira_en
                FROM stock_reservas
                WHERE session_id = $1
                  AND vino_id = ANY($2::uuid[])
                  AND estado = 'activa'
                  AND expira_en > $3
                FOR UPDATE
                """,
                session_id,
                vino_ids,
                now,
            )
            reservado_por_vino: dict[UUID, int] = {}
            for r in reservas_rows:
                reservado_por_vino[r["vino_id"]] = (
                    reservado_por_vino.get(r["vino_id"], 0) + int(r["cantidad"])
                )

            faltantes = [
                vid for vid, qty in items if reservado_por_vino.get(vid, 0) < qty
            ]
            if faltantes:
                return CreateOrderResponse(
                    resultado=ResultadoTool.ERROR,
                    mensaje=(
                        "Las reservas de stock expiraron o no alcanzan. "
                        "Volvé a correr `verificar_stock_exacto` antes de crear la orden."
                    ),
                )

            lineas_orden: list[OrderLine] = []
            subtotal = Decimal("0")
            for vino_id, cantidad in items:
                row = por_id[vino_id]
                subtotal_linea = row["precio_ars"] * Decimal(cantidad)
                subtotal += subtotal_linea
                lineas_orden.append(
                    OrderLine(
                        vino_id=vino_id,
                        nombre_vino=row["nombre"],
                        cantidad=cantidad,
                        precio_unitario_ars=row["precio_ars"],
                        subtotal_ars=subtotal_linea.quantize(Decimal("0.01")),
                    )
                )

            envio = Decimal(str(costo_envio_ars)).quantize(Decimal("0.01"))
            total = (subtotal + envio).quantize(Decimal("0.01"))
            order_id = uuid4()
            order = Order(
                order_id=order_id,
                session_id=session_id,
                cliente_id=cliente_id,
                idempotency_key=idem_key,
                lineas=lineas_orden,
                subtotal_ars=subtotal.quantize(Decimal("0.01")),
                envio_ars=envio,
                total_ars=total,
            )

            await conn.execute(
                """
                INSERT INTO pedidos (
                    id, session_id, cliente_id, idempotency_key,
                    subtotal_ars, envio_ars, total_ars, estado, created_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8, NOW())
                """,
                order.order_id,
                order.session_id,
                order.cliente_id,
                order.idempotency_key,
                order.subtotal_ars,
                order.envio_ars,
                order.total_ars,
                order.estado.value,
            )
            for linea in lineas_orden:
                await conn.execute(
                    """
                    INSERT INTO pedido_lineas (
                        pedido_id, vino_id, cantidad,
                        precio_unitario_ars, subtotal_ars
                    ) VALUES ($1,$2,$3,$4,$5)
                    """,
                    order.order_id,
                    linea.vino_id,
                    linea.cantidad,
                    linea.precio_unitario_ars,
                    linea.subtotal_ars,
                )

            await conn.execute(
                """
                UPDATE stock_reservas
                SET estado = 'consumida', consumida_en = $1
                WHERE session_id = $2 AND estado = 'activa'
                """,
                now,
                session_id,
            )

            for vino_id, cantidad in items:
                result = await conn.execute(
                    """
                    UPDATE stock
                    SET cantidad = cantidad - $1
                    WHERE vino_id = $2 AND cantidad >= $1
                    """,
                    cantidad,
                    vino_id,
                )
                if not result.endswith(" 1"):
                    raise RuntimeError(
                        f"Stock físico insuficiente al consumar reserva del vino {vino_id}"
                    )

    response = CreateOrderResponse(resultado=ResultadoTool.OK, order=order)
    await idem.put(idem_key, response.model_dump_json(), status="ok")
    return response
