"""Tests unitarios de tools SQL, 2PC, cliente y eventos.

Mockean asyncpg (fetch_all / fetchrow / execute / get_pool). Verifican
que las tools transaccionales no usan retriever y que los contratos Pydantic
salen tipados.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.order import TipoEntrega
from schemas.tool_responses import (
    CalculatedOrderResponse,
    CreateOrderResponse,
    CustomerContextResponse,
    DeliveryZoneResponse,
    EventReservationResponse,
    EventsListResponse,
    PriceResponse,
    ResultadoTool,
    SavePreferenceResponse,
    StockResponse,
    VerifyStockResponse,
    VintageComparisonResponse,
)


def _row(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.__getitem__ = lambda self, k: data[k]
    mock.__contains__ = lambda self, k: k in data
    mock.get = lambda k, default=None: data.get(k, default)
    return mock


def _pool_conn(fetch=None, fetchrow=None, execute_results=None):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=fetch or [])
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    results = list(execute_results or ["UPDATE 1", "INSERT 1", "INSERT 1"])

    async def _exec(*_a, **_k):
        if results:
            return results.pop(0)
        return "UPDATE 1"

    conn.execute = AsyncMock(side_effect=_exec)
    txn = AsyncMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn)
    acq = AsyncMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acq)
    return pool, conn


# ── consultar_stock ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_consultar_stock_con_disponibilidad():
    vino_id = str(uuid.uuid4())
    with patch("tools.catalog.consult_stock.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [
            _row(
                {
                    "id": vino_id,
                    "nombre": "Zuccardi",
                    "cantidad": 20,
                    "ubicacion": "deposito_principal",
                }
            )
        ]
        from tools.catalog.consult_stock import consultar_stock

        result = await consultar_stock.entrypoint(vino_ids=[vino_id])

    assert isinstance(result, StockResponse)
    assert result.todos_disponibles is True
    assert result.items[0].cantidad == 20


@pytest.mark.asyncio
async def test_consultar_stock_vacio_ids():
    from tools.catalog.consult_stock import consultar_stock

    result = await consultar_stock.entrypoint(vino_ids=[])
    assert isinstance(result, StockResponse)
    assert result.todos_disponibles is False
    assert result.items == []


@pytest.mark.asyncio
async def test_consultar_stock_no_usa_rag():
    import tools.catalog.consult_stock as module

    source = inspect.getsource(module)
    assert "retriever" not in source
    assert "buscar_similar" not in source


# ── consultar_precio ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_consultar_precio_valido():
    vino_id = "achaval-malbec-2020"
    with patch("tools.catalog.consult_price.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [
            _row(
                {
                    "id": vino_id,
                    "nombre": "Achaval Ferrer",
                    "precio": Decimal("4500.00"),
                    "anada": 2020,
                    "activo": True,
                }
            )
        ]
        from tools.catalog.consult_price import consultar_precio

        result = await consultar_precio.entrypoint(vino_ids=[vino_id])

    assert isinstance(result, PriceResponse)
    assert result.resultado == ResultadoTool.OK
    assert result.items[0].precio_ars == Decimal("4500.00")


@pytest.mark.asyncio
async def test_consultar_precio_cero_se_descarta():
    with patch("tools.catalog.consult_price.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [
            _row(
                {
                    "id": "x",
                    "nombre": "X",
                    "precio": Decimal("0"),
                    "anada": 2020,
                    "activo": True,
                }
            )
        ]
        from tools.catalog.consult_price import consultar_precio

        result = await consultar_precio.entrypoint(producto_ids=["x"])
    assert result.resultado == ResultadoTool.NO_ENCONTRADO


@pytest.mark.asyncio
async def test_consultar_precio_no_encontrado():
    with patch("tools.catalog.consult_price.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        from tools.catalog.consult_price import consultar_precio

        result = await consultar_precio.entrypoint(vino_ids=["missing"])
    assert result.resultado == ResultadoTool.NO_ENCONTRADO


@pytest.mark.asyncio
async def test_comparar_anadas_ordena_por_anio():
    with patch("tools.catalog.compare_vintages.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [
            _row(
                {
                    "id": "a-2021",
                    "nombre": "Achaval",
                    "bodega": "AF",
                    "anada": 2021,
                    "precio": Decimal("5000"),
                    "activo": True,
                }
            ),
            _row(
                {
                    "id": "a-2019",
                    "nombre": "Achaval",
                    "bodega": "AF",
                    "anada": 2019,
                    "precio": Decimal("4200"),
                    "activo": True,
                }
            ),
        ]
        from tools.catalog.compare_vintages import comparar_anadas

        result = await comparar_anadas.entrypoint(etiqueta="Achaval")
    assert isinstance(result, VintageComparisonResponse)
    assert result.items[0].anada == 2021


# ── 2PC verify (read-only) + calculate ─────────────────────────────────
@pytest.mark.asyncio
async def test_verificar_stock_exacto_no_muta():
    pid = "malbec-1"
    with (
        patch("tools.orders.verify_stock_exact.fetch_all", new_callable=AsyncMock) as mock_fetch,
        patch("storage.postgres.execute", new_callable=AsyncMock) as mock_exec,
    ):
        mock_fetch.return_value = [
            _row(
                {
                    "id": pid,
                    "nombre": "Malbec",
                    "disponible": 4,
                    "ubicacion": "deposito_principal",
                    "activo": True,
                }
            )
        ]
        from tools.orders.verify_stock_exact import verificar_stock_exacto

        result = await verificar_stock_exacto.entrypoint(
            session_id="s1",
            lineas=[{"producto_id": pid, "cantidad": 2}],
        )
        mock_exec.assert_not_called()
    assert isinstance(result, VerifyStockResponse)
    assert result.todos_disponibles is True
    assert "execute(" not in inspect.getsource(
        __import__("tools.orders.verify_stock_exact", fromlist=["x"])
    )


@pytest.mark.asyncio
async def test_verificar_stock_faltante():
    with patch("tools.orders.verify_stock_exact.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [
            _row(
                {
                    "id": "x",
                    "nombre": "X",
                    "disponible": 1,
                    "ubicacion": "deposito_principal",
                    "activo": True,
                }
            )
        ]
        from tools.orders.verify_stock_exact import verificar_stock_exacto

        result = await verificar_stock_exacto.entrypoint(
            session_id="s1",
            lineas=[{"vino_id": "x", "cantidad": 5}],
        )
    assert result.todos_disponibles is False
    assert "x" in result.faltantes


@pytest.mark.asyncio
async def test_calcular_orden_envio_gratis_sobre_umbral():
    with patch("tools.orders.calculate_order.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [
            _row({"id": "caro", "nombre": "Icono", "precio": Decimal("20000"), "activo": True})
        ]
        from tools.orders.calculate_order import calcular_orden

        result = await calcular_orden.entrypoint(
            lineas=[{"producto_id": "caro", "cantidad": 2}],
            tipo_entrega=TipoEntrega.ENVIO_DOMICILIO,
        )
    assert isinstance(result, CalculatedOrderResponse)
    assert result.order is not None
    assert result.envio == Decimal("0.00")
    assert result.order.total == Decimal("40000.00")


@pytest.mark.asyncio
async def test_calcular_orden_descuento_volumen():
    with patch("tools.orders.calculate_order.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [
            _row({"id": "b", "nombre": "Box", "precio": Decimal("1000"), "activo": True})
        ]
        from tools.orders.calculate_order import calcular_orden

        result = await calcular_orden.entrypoint(
            lineas=[{"producto_id": "b", "cantidad": 6}],
            tipo_entrega=TipoEntrega.RETIRO_LOCAL,
        )
    assert result.order is not None
    assert result.order.descuento == Decimal("300.00")
    assert result.order.total == Decimal("5700.00")


@pytest.mark.asyncio
async def test_crear_orden_idempotente_y_log():
    pid = "m-1"
    pool, conn = _pool_conn(
        fetch=[
            _row({"id": pid, "nombre": "Malbec", "precio": Decimal("1000"), "activo": True}),
            _row({"producto_id": pid, "cantidad_disponible": 10, "reservado": 0}),
        ],
        fetchrow=None,
        execute_results=["UPDATE 1", "INSERT 0 1", "INSERT 0 1"],
    )
    conn.fetch = AsyncMock(
        side_effect=[
            [_row({"id": pid, "nombre": "Malbec", "precio": Decimal("1000"), "activo": True})],
            [_row({"producto_id": pid, "cantidad_disponible": 10, "reservado": 0})],
        ]
    )
    idem = MagicMock()
    idem.get = AsyncMock(return_value=None)
    idem.put = AsyncMock()

    with (
        patch("tools.orders.create_order.get_pool", new_callable=AsyncMock, return_value=pool),
        patch("tools.orders.create_order.IdempotencyManager", return_value=idem),
        patch(
            "tools.orders.create_order.log_transaction_event",
            new_callable=AsyncMock,
        ) as mock_log,
    ):
        from tools.orders.create_order import crear_orden

        result = await crear_orden.entrypoint(
            session_id="sess-1",
            cliente_id="cli-1",
            lineas=[{"producto_id": pid, "cantidad": 1}],
            tipo_entrega=TipoEntrega.RETIRO_LOCAL,
            idempotency_key="idem-test-1",
        )
    assert isinstance(result, CreateOrderResponse)
    assert result.resultado == ResultadoTool.OK
    assert result.order is not None
    assert result.order.id.startswith("PED-")
    mock_log.assert_awaited()


# ── customer ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cargar_contexto_cliente():
    with (
        patch("tools.customer.load_context.fetchrow", new_callable=AsyncMock) as mock_row,
        patch("tools.customer.load_context.fetch_all", new_callable=AsyncMock) as mock_all,
    ):
        mock_row.return_value = _row(
            {
                "nombre": "Martín",
                "email": "m@x.com",
                "telefono": None,
                "segmento": "frecuente",
                "perfil_tipo": "coleccionista",
            }
        )
        mock_all.return_value = [
            _row(
                {
                    "clave": "cepa_favorita",
                    "valor": "malbec",
                    "fuente": "chat",
                    "updated_at": datetime.now(UTC),
                }
            )
        ]
        from tools.customer.load_context import cargar_contexto_cliente

        result = await cargar_contexto_cliente.entrypoint(cliente_id="cli-1")
    assert isinstance(result, CustomerContextResponse)
    assert result.encontrado is True
    assert result.perfil is not None
    assert result.perfil.nombre == "Martín"


@pytest.mark.asyncio
async def test_guardar_preferencia_upsert():
    with (
        patch("tools.customer.save_preference.fetchrow", new_callable=AsyncMock) as mock_row,
        patch("tools.customer.save_preference.execute", new_callable=AsyncMock) as mock_exec,
    ):
        mock_row.side_effect = [_row({"id": "cli-1"}), _row({"id": 42})]
        from tools.customer.save_preference import guardar_preferencia

        result = await guardar_preferencia.entrypoint(
            cliente_id="cli-1",
            tipo="cepa_favorita",
            valor="malbec",
            confianza=0.9,
        )
    assert isinstance(result, SavePreferenceResponse)
    assert result.resultado == ResultadoTool.OK
    assert result.preferencia_id == "42"
    assert mock_exec.await_count >= 1


@pytest.mark.asyncio
async def test_zona_entrega_caba():
    from tools.customer.consult_delivery_zone import consultar_zona_entrega

    result = await consultar_zona_entrega.entrypoint(codigo_postal="C1425")
    assert isinstance(result, DeliveryZoneResponse)
    assert result.cubre is True
    assert result.zona == "caba"


# ── events ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_consultar_eventos():
    with patch("tools.events.consult_events.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [
            _row(
                {
                    "id": "cata-1",
                    "titulo": "Cata Malbec",
                    "descripcion": "Noche de malbecs",
                    "fecha": datetime.now(UTC),
                    "precio": Decimal("8000"),
                    "cupo_total": 20,
                    "cupo_disponible": 5,
                    "activo": True,
                }
            )
        ]
        from tools.events.consult_events import consultar_eventos

        result = await consultar_eventos.entrypoint()
    assert isinstance(result, EventsListResponse)
    assert result.eventos[0].cupo_disponible == 5


@pytest.mark.asyncio
async def test_reservar_evento_sin_cupo():
    pool, conn = _pool_conn(
        fetchrow=_row(
            {"id": "cata-1", "precio": Decimal("8000"), "cupo_disponible": 0, "activo": True}
        )
    )
    with patch("tools.events.reserve_event.get_pool", new_callable=AsyncMock, return_value=pool):
        from tools.events.reserve_event import reservar_evento

        result = await reservar_evento.entrypoint(
            evento_id="cata-1",
            cliente_id="cli-1",
            cantidad=2,
        )
    assert isinstance(result, EventReservationResponse)
    assert result.resultado == ResultadoTool.ERROR


@pytest.mark.asyncio
async def test_faq_fallback_envio():
    with patch("tools.support.search_faq.fetchrow", new_callable=AsyncMock, return_value=None):
        from tools.support.search_faq import buscar_faq

        result = await buscar_faq.entrypoint(pregunta="¿Cuánto sale el envío a CABA?")
    assert result.resultado == ResultadoTool.OK
    assert result.fuente is not None


@pytest.mark.asyncio
async def test_buscar_por_maridaje_devuelve_rag_tipado():
    from schemas.knowledge_fragment import CapaConocimiento
    from schemas.tool_responses import PairingResponse, RAGResult

    fragmento = RAGResult(
        vino_id="achaval-malbec-2020",
        nombre_vino="Achaval Malbec",
        capa=CapaConocimiento.TERRUNO,
        contenido="Marida con asado y empanadas.",
        score=0.91,
    )
    with patch(
        "tools.catalog.search_by_pairing.buscar_similar",
        new_callable=AsyncMock,
        return_value=[fragmento],
    ):
        from tools.catalog.search_by_pairing import buscar_por_maridaje

        result = await buscar_por_maridaje.entrypoint(descripcion_comida="asado")
    assert isinstance(result, PairingResponse)
    assert result.fragmentos[0].capa == CapaConocimiento.TERRUNO


@pytest.mark.asyncio
async def test_log_transaction_event_hashea_payload():
    with patch("storage.immutable_log.execute", new_callable=AsyncMock) as mock_exec:
        from storage.immutable_log import hash_payload, log_transaction_event

        payload = {"pedido_id": "PED-abc", "total": "1000.00"}
        await log_transaction_event(
            session_id="sess-1",
            accion="crear_orden",
            payload=payload,
            idempotency_key="idem-1",
            resultado="ok",
        )
    mock_exec.assert_awaited_once()
    sql, session_id, accion, payload_hash, *_rest = mock_exec.await_args.args
    assert "INSERT INTO log_inmutable" in sql
    assert session_id == "sess-1"
    assert accion == "crear_orden"
    assert payload_hash == hash_payload(payload)
