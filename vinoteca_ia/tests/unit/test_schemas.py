"""
Tests de validación de contratos Pydantic.
Verifican invariantes críticos del modelo de dominio.
"""

import uuid

import pytest
from pydantic import ValidationError

from schemas.agent_io import IntentClass, RouterOutput
from schemas.order import Order, OrderEstado, OrderLine, TipoEntrega
from schemas.session_state import SessionState, TurnoHistorial
from schemas.wine_catalog import PrecioInfo, StockInfo, WineModel


# ── WineModel ──────────────────────────────────────────────────────────
def test_wine_precio_positivo():
    vid = uuid.uuid4()
    wine = WineModel(
        id=vid, nombre="Test", bodega="Bodega", varietal="Malbec", precio=1500.0
    )
    assert wine.precio == 1500.0


def test_wine_precio_cero_invalido():
    with pytest.raises(ValidationError):
        WineModel(id=uuid.uuid4(), nombre="X", bodega="B", varietal="V", precio=0.0)


def test_wine_precio_negativo_invalido():
    with pytest.raises(ValidationError):
        WineModel(id=uuid.uuid4(), nombre="X", bodega="B", varietal="V", precio=-100.0)


# ── StockInfo ──────────────────────────────────────────────────────────
def test_stock_info_disponible():
    s = StockInfo(vino_id=uuid.uuid4(), nombre="Vino", disponible=True, cantidad=10)
    assert s.disponible is True
    assert s.cantidad == 10


def test_stock_info_no_disponible():
    s = StockInfo(vino_id=uuid.uuid4(), nombre="Vino", disponible=False, cantidad=0)
    assert s.disponible is False


# ── Order ──────────────────────────────────────────────────────────────
def test_order_total_negativo_invalido():
    with pytest.raises(ValidationError):
        Order(
            id=uuid.uuid4(),
            session_id="sess_test",
            estado=OrderEstado.PREPARANDO,
            tipo_entrega=TipoEntrega.RETIRO,
            idempotency_key="key_test",
            total=-100.0,
        )


def test_order_estado_enum():
    order = Order(
        id=uuid.uuid4(),
        session_id="sess_test",
        estado=OrderEstado.PENDIENTE_APROBACION,
        tipo_entrega=TipoEntrega.RETIRO,
        idempotency_key="key_test",
        total=5000.0,
    )
    assert order.estado == "pendiente_aprobacion"


# ── RouterOutput ───────────────────────────────────────────────────────
def test_router_output_confianza_rango():
    r = RouterOutput(
        intencion=IntentClass.RECOMENDACION,
        confianza=0.95,
        agente_destino="agente_sumiller",
    )
    assert r.confianza == 0.95


def test_router_output_confianza_fuera_rango():
    with pytest.raises(ValidationError):
        RouterOutput(
            intencion=IntentClass.RECOMENDACION,
            confianza=1.5,
            agente_destino="agente_sumiller",
        )


# ── SessionState ───────────────────────────────────────────────────────
def test_session_state_inmutabilidad():
    state = SessionState(session_id="s1", correlation_id="c1")
    new_state = state.agregar_turno("user", "Hola")
    assert len(new_state.historial) == 1
    assert len(state.historial) == 0  # original sin mutar


def test_session_state_ultimos_turnos():
    state = SessionState(session_id="s1", correlation_id="c1")
    for i in range(12):
        state = state.agregar_turno("user", f"msg {i}")
    ultimos = state.ultimos_turnos(8)
    assert len(ultimos) == 8
    assert ultimos[-1].contenido == "msg 11"


# ── PrecioInfo ─────────────────────────────────────────────────────────
def test_precio_info_valido():
    p = PrecioInfo(vino_id=uuid.uuid4(), nombre="Vino", precio=3500.0)
    assert p.moneda == "ARS"
