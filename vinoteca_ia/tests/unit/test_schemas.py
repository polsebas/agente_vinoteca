"""
Tests de validación de contratos Pydantic.
Verifican invariantes críticos del modelo de dominio.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from schemas import (
    CalculatedOrder,
    CapaConocimiento,
    ConfirmedOrder,
    CustomerProfile,
    EstadoOrden,
    FuenteConocimiento,
    JerarquiaFuente,
    JudgeEvaluationResult,
    KnowledgeFragment,
    Order,
    OrderLineItem,
    PerfilClienteTipo,
    SessionState,
    TipoEntrega,
    WineProduct,
)
from schemas.agent_io import AgenteDestino, IntentClass, RouterOutput
from schemas.api import ChatRequest
from schemas.judge_rubric import CriterioEvaluacion, JudgeCriterioScore
from schemas.wine_catalog import StockInfo, Varietal


def _stock(vino_id: uuid.UUID | None = None, nombre: str = "Test") -> StockInfo:
    return StockInfo(
        vino_id=vino_id or uuid.uuid4(),
        nombre=nombre,
        disponible=True,
        cantidad=10,
    )


def _linea_ejemplo() -> OrderLineItem:
    return OrderLineItem(
        producto_id=str(uuid.uuid4()),
        nombre="Test",
        cantidad=1,
        precio_unitario=Decimal("1000.00"),
        subtotal=Decimal("1000.00"),
    )


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
    assert wine.stock_info is not None
    assert wine.apto_publicacion is False


def test_wine_apto_publicacion_requiere_tres_capas():
    vid = uuid.uuid4()
    wine = WineProduct(
        vino_id=vid,
        nombre="Achaval",
        bodega="Achaval Ferrer",
        varietal=Varietal.MALBEC,
        region="Mendoza",
        precio_ars=Decimal("1500.00"),
        anada_actual=2022,
        capas_disponibles=[
            CapaConocimiento.DATO_DURO,
            CapaConocimiento.TERRUNO,
            CapaConocimiento.VOZ_PROPIA,
        ],
        stock_info=_stock(vid, "Achaval"),
    )
    assert wine.apto_publicacion is True


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


# ── KnowledgeFragment ──────────────────────────────────────────────────
def test_knowledge_fragment_capas_y_jerarquia():
    frag = KnowledgeFragment(
        id="kf-1",
        producto_id="achaval-malbec-2022",
        capa=CapaConocimiento.VOZ_PROPIA,
        fuente=FuenteConocimiento.SUMILLER,
        contenido="A mí este vino me recuerda a Gualtallary en enero.",
    )
    assert frag.capa == 5
    assert JerarquiaFuente.es_preferida(
        FuenteConocimiento.SUMILLER, FuenteConocimiento.REDES_SOCIALES
    )
    assert JerarquiaFuente.prioridad(FuenteConocimiento.BODEGA_OFICIAL) < (
        JerarquiaFuente.prioridad(FuenteConocimiento.CRITICO)
    )


# ── Order ──────────────────────────────────────────────────────────────
def test_order_total_negativo_invalido():
    with pytest.raises(ValidationError):
        Order(
            session_id="sess_test",
            idempotency_key="key_test",
            lineas=[_linea_ejemplo()],
            total=Decimal("-100.00"),
        )


def test_order_estado_default():
    order = Order(
        session_id="sess_test",
        idempotency_key="key_test",
        lineas=[_linea_ejemplo()],
        total=Decimal("1000.00"),
    )
    assert order.estado == EstadoOrden.PREPARADA
    assert order.tipo_entrega == TipoEntrega.ENVIO_DOMICILIO


def test_order_acepta_alias_historicos():
    linea = OrderLineItem.model_validate(
        {
            "vino_id": str(uuid.uuid4()),
            "nombre_vino": "Malbec",
            "cantidad": 2,
            "precio_unitario_ars": "1500.00",
            "subtotal_ars": "3000.00",
        }
    )
    assert linea.producto_id
    assert linea.nombre == "Malbec"
    order = Order.model_validate(
        {
            "order_id": str(uuid.uuid4()),
            "session_id": "s1",
            "idempotency_key": "k1",
            "lineas": [linea.model_dump()],
            "total_ars": "3000.00",
        }
    )
    assert order.total == Decimal("3000.00")


def test_calculated_order_requiere_confirmacion():
    calc = CalculatedOrder(
        lineas=[_linea_ejemplo()],
        subtotal=Decimal("1000.00"),
        total=Decimal("1000.00"),
        tipo_entrega=TipoEntrega.RETIRO_LOCAL,
    )
    assert calc.requiere_confirmacion is True
    confirmed = ConfirmedOrder(
        session_id="s1",
        idempotency_key="k1",
        lineas=[_linea_ejemplo()],
        total=Decimal("1000.00"),
    )
    assert confirmed.estado == EstadoOrden.APROBADA


# ── Judge ──────────────────────────────────────────────────────────────
def test_judge_aprueba_con_cinco_de_seis():
    scores = [JudgeCriterioScore(criterio=c, aprobado=True) for c in list(CriterioEvaluacion)[:5]]
    scores.append(
        JudgeCriterioScore(
            criterio=CriterioEvaluacion.TONO_Y_CAPA_ADECUADOS,
            aprobado=False,
            observacion="Tono demasiado técnico",
        )
    )
    result = JudgeEvaluationResult(
        session_id="s1",
        correlation_id="c1",
        scores=scores,
    )
    assert result.puntos_totales == 5
    assert result.aprobado is True
    assert len(CriterioEvaluacion) == 6


def test_judge_reprueba_con_menos_de_cinco():
    scores = [
        JudgeCriterioScore(criterio=c, aprobado=i < 3) for i, c in enumerate(CriterioEvaluacion)
    ]
    result = JudgeEvaluationResult(
        session_id="s1",
        correlation_id="c1",
        scores=scores,
    )
    assert result.puntos_totales == 3
    assert result.aprobado is False
    assert result.categoria_fallo is not None


# ── CustomerProfile ────────────────────────────────────────────────────
def test_customer_profile_aliases_y_segmento_general():
    perfil = CustomerProfile.model_validate(
        {
            "cliente_id": "cli-1",
            "segmento": "general",
            "varietales_favoritos": ["malbec"],
            "alergias": ["sulfitos"],
            "rango_precio_preferido_ars": [8000, 15000],
        }
    )
    assert perfil.perfil_tipo == PerfilClienteTipo.GENERAL
    assert perfil.cepas_favoritas == [Varietal.MALBEC]
    assert perfil.restricciones_dietarias == ["sulfitos"]
    assert perfil.rango_precio_habitual == (8000, 15000)


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
    assert state.max_pasos == 5
    assert state.perfil_inferido == PerfilClienteTipo.GENERAL
    with pytest.raises(ValidationError):
        state.pasos_actuales = 99  # type: ignore[misc]


def test_session_state_ultimos_turnos():
    state = SessionState(session_id="s1", correlation_id="c1")
    for i in range(12):
        state = state.con_turno("user", f"msg {i}")
    ultimos = state.ultimos_turnos(8)
    assert len(ultimos) == 8
    assert ultimos[-1].contenido == "msg 11"


def test_knowledge_fragment_created_at_timezone():
    frag = KnowledgeFragment(
        id="kf-2",
        producto_id="x",
        capa=CapaConocimiento.DATO_DURO,
        fuente=FuenteConocimiento.BODEGA_OFICIAL,
        contenido="Malbec 14.5% ABV.",
    )
    assert frag.created_at.tzinfo is not None
    assert frag.created_at.tzinfo == UTC
    assert isinstance(frag.created_at, datetime)


def test_chat_request_stream_default_y_forbid():
    req = ChatRequest(mensaje="hola")
    assert req.stream is True
    assert req.canal == "web"
    assert ChatRequest.model_validate({"message": "hola", "session_id": "s1"}).mensaje == "hola"
    with pytest.raises(ValidationError):
        ChatRequest(mensaje="hola", extra_field="no")
