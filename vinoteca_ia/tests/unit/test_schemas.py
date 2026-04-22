"""
Tests de validación de contratos Pydantic.
Verifican invariantes críticos del modelo de dominio.
"""

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from schemas.agent_io import AgenteDestino, IntentClass, RouterOutput
from schemas.order import EstadoOrden, Order, OrderLine
from schemas.session_state import SessionState
from schemas.wine_catalog import StockInfo, Varietal, WineProduct


# ── WineProduct ─────────────────────────────────────────────────────────
def test_wine_precio_positivo():
    wine = WineProduct(
        vino_id=uuid.uuid4(),
        nombre="Test",
        bodega="Bodega",
        varietal=Varietal.MALBEC,
        region="Mendoza",
        precio_ars=Decimal("1500.00"),
        anada_actual=2020,
    )
    assert wine.precio_ars == Decimal("1500.00")


def test_wine_precio_cero_invalido():
    with pytest.raises(ValidationError):
        WineProduct(
            vino_id=uuid.uuid4(),
            nombre="X",
            bodega="B",
            varietal=Varietal.MALBEC,
            region="R",
            precio_ars=Decimal("0.00"),
            anada_actual=2020,
        )


def test_wine_precio_negativo_invalido():
    with pytest.raises(ValidationError):
        WineProduct(
            vino_id=uuid.uuid4(),
            nombre="X",
            bodega="B",
            varietal=Varietal.MALBEC,
            region="R",
            precio_ars=Decimal("-100.00"),
            anada_actual=2020,
        )


# ── StockInfo ──────────────────────────────────────────────────────────
def test_stock_info_disponible():
    s = StockInfo(vino_id=uuid.uuid4(), nombre="Vino", disponible=True, cantidad=10)
    assert s.disponible is True
    assert s.cantidad == 10


def test_stock_info_no_disponible():
    s = StockInfo(vino_id=uuid.uuid4(), nombre="Vino", disponible=False, cantidad=0)
    assert s.disponible is False


# ── Order ──────────────────────────────────────────────────────────────
def _linea_ejemplo() -> OrderLine:
    vid = uuid.uuid4()
    return OrderLine(
        vino_id=vid,
        nombre_vino="Test",
        cantidad=1,
        precio_unitario_ars=Decimal("1000.00"),
        subtotal_ars=Decimal("1000.00"),
    )


def test_order_total_negativo_invalido():
    with pytest.raises(ValidationError):
        Order(
            session_id="sess_test",
            idempotency_key="key_test",
            lineas=[_linea_ejemplo()],
            subtotal_ars=Decimal("-100.00"),
            envio_ars=Decimal("0.00"),
            total_ars=Decimal("-100.00"),
        )


def test_order_estado_default():
    order = Order(
        session_id="sess_test",
        idempotency_key="key_test",
        lineas=[_linea_ejemplo()],
        subtotal_ars=Decimal("1000.00"),
        envio_ars=Decimal("0.00"),
        total_ars=Decimal("1000.00"),
    )
    assert order.estado == EstadoOrden.PREPARADA


# ── RouterOutput ───────────────────────────────────────────────────────
def test_router_output_confianza_rango():
    r = RouterOutput(
        intencion=IntentClass.RECOMENDACION,
        confianza=0.95,
        agente_destino=AgenteDestino.SOMMELIER,
        razonamiento="Cliente pide recomendación clara.",
    )
    assert r.confianza == 0.95


def test_router_output_confianza_fuera_rango():
    with pytest.raises(ValidationError):
        RouterOutput(
            intencion=IntentClass.RECOMENDACION,
            confianza=1.5,
            agente_destino=AgenteDestino.SOMMELIER,
            razonamiento="Confianza fuera de rango (test).",
        )


# ── SessionState ───────────────────────────────────────────────────────
def test_session_state_inmutabilidad():
    state = SessionState(session_id="s1", correlation_id="c1")
    new_state = state.con_turno("user", "Hola")
    assert len(new_state.historial) == 1
    assert len(state.historial) == 0  # original sin mutar


def test_session_state_ultimos_turnos():
    state = SessionState(session_id="s1", correlation_id="c1")
    for i in range(12):
        state = state.con_turno("user", f"msg {i}")
    ultimos = state.ultimos_turnos(8)
    assert len(ultimos) == 8
    assert ultimos[-1].contenido == "msg 11"


