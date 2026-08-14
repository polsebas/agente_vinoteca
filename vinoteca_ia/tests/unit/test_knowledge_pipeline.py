"""Pipeline de conocimiento: captura, umbral 3/5, enricher, conflictos y sources."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from knowledge.capture.new_wine_onboarding import UMBRAL_CAPAS_PUBLICACION, evaluar_nuevo_vino
from knowledge.capture.sommelier_interface import capture_nota_rapida, confirmar_captura
from knowledge.pipeline.conflict_resolver import fuente_gana, resolve_conflicts
from knowledge.pipeline.enricher import heuristic_enrich
from knowledge.sources.press_monitor import fetch_press_mentions
from knowledge.sources.winery_websites import fetch_winery_articles
from schemas.knowledge_fragment import CapaConocimiento, FuenteConocimiento, KnowledgeFragment
from schemas.wine_catalog import Varietal, WineProduct


def _wine(*, capas: list[CapaConocimiento], activo: bool = True) -> WineProduct:
    return WineProduct(
        vino_id="nuevo-malbec-2024",
        nombre="Nuevo Malbec",
        bodega="Bodega Test",
        varietal=Varietal.MALBEC,
        region="Mendoza",
        precio_ars=Decimal("15000.00"),
        anada_actual=2024,
        activo=activo,
        capas_disponibles=capas,
    )


def test_onboarding_requiere_tres_capas():
    assert UMBRAL_CAPAS_PUBLICACION == 3
    corto = evaluar_nuevo_vino(
        _wine(capas=[CapaConocimiento.DATO_DURO, CapaConocimiento.TERRUNO], activo=True)
    )
    assert corto.activo is False
    assert corto.apto_publicacion is False

    completo = evaluar_nuevo_vino(
        _wine(
            capas=[
                CapaConocimiento.DATO_DURO,
                CapaConocimiento.TERRUNO,
                CapaConocimiento.VOZ_PROPIA,
            ],
            activo=False,
        )
    )
    assert completo.activo is True
    assert completo.apto_publicacion is True


def test_captura_regla_2_minutos_y_confirmacion():
    draft = capture_nota_rapida(
        "Suelos aluviales a 1100 msnm. En cata me recuerda a Gualtallary en enero.",
        "achaval-malbec-2022",
    )
    assert draft.requiere_confirmacion is True
    assert draft.puntos
    assert "click" in draft.mensaje_sumiller.lower()
    frags = confirmar_captura(draft)
    assert all(f.fuente == FuenteConocimiento.SUMILLER for f in frags)
    assert all(f.validador_humano for f in frags)
    capas = {int(f.capa) for f in frags}
    assert CapaConocimiento.TERRUNO in capas or CapaConocimiento.VOZ_PROPIA in capas


def test_enricher_heuristico_cinco_capas_sin_precio():
    ficha = (
        "Malbec 2022, 14.5% ABV, Valle de Uco.\n\n"
        "Suelos aluviales a 1100 msnm con clima continental.\n\n"
        "El enólogo fundó la bodega con filosofía de mínima intervención.\n\n"
        "Estilo orgánico en tendencia, puntaje Descorchados 94.\n\n"
        "Cata del sumiller: nariz de fruta negra y paladar tenso.\n\n"
        "Precio $100 ARS y stock 500 cajas."
    )
    frags = heuristic_enrich(ficha, "achaval-malbec-2022", FuenteConocimiento.BODEGA_OFICIAL)
    capas = {int(f.capa) for f in frags}
    assert len(capas) >= 3
    joined = " ".join(f.contenido for f in frags).lower()
    assert "500 cajas" not in joined


def test_conflict_resolver_jerarquia_sumiller_gana():
    t0 = datetime.now(UTC)
    social = KnowledgeFragment(
        id="a",
        producto_id="x",
        capa=CapaConocimiento.TERRUNO,
        fuente=FuenteConocimiento.REDES_SOCIALES,
        contenido="Dicen que es de llanura.",
        created_at=t0 + timedelta(hours=2),
    )
    bodega = KnowledgeFragment(
        id="b",
        producto_id="x",
        capa=CapaConocimiento.TERRUNO,
        fuente=FuenteConocimiento.BODEGA_OFICIAL,
        contenido="Valle de Uco, 1100 msnm.",
        created_at=t0,
    )
    sumiller = KnowledgeFragment(
        id="c",
        producto_id="x",
        capa=CapaConocimiento.TERRUNO,
        fuente=FuenteConocimiento.SUMILLER,
        contenido="Calcáreo de Gualtallary, lo caté yo.",
        created_at=t0 - timedelta(days=1),
    )
    critico = KnowledgeFragment(
        id="d",
        producto_id="x",
        capa=CapaConocimiento.TERRUNO,
        fuente=FuenteConocimiento.CRITICO,
        contenido="Notas de crítica sobre el valle.",
        created_at=t0,
    )
    ganadores = resolve_conflicts([social, bodega, sumiller, critico])
    assert len(ganadores) == 1
    assert ganadores[0].fuente == FuenteConocimiento.SUMILLER
    assert fuente_gana(bodega, critico) is bodega
    assert fuente_gana(critico, social) is critico


@pytest.mark.asyncio
async def test_sources_mock_bodega_y_prensa():
    wineries = await fetch_winery_articles(producto_id="achaval-malbec-2022")
    press = await fetch_press_mentions(producto_id="achaval-malbec-2022")
    assert wineries and wineries[0].fuente.value == "bodega_oficial"
    assert press and press[0].fuente.value == "critico"
    assert "Malbec" in wineries[0].contenido or "suelo" in wineries[0].contenido.lower()
