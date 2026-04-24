"""Tests de las funciones puras de normalización de la ingesta del catálogo."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from scripts.ingest.normalizers import (
    anada_o_fallback,
    construir_descripcion_corta,
    construir_fragmento_capa1,
    construir_region,
    extraer_anada,
    normalizar_fila,
    parse_alcohol,
    parse_altura,
    parse_precio_ars,
    parse_varietal,
    parse_volumen_ml,
)


# ── parse_precio_ars ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw, esperado",
    [
        ("$879.935,00", Decimal("879935.00")),
        ("$692.380,00", Decimal("692380.00")),
        ("692380", Decimal("692380.00")),
        ("1.500,50", Decimal("1500.50")),
        ("$ 1.200", Decimal("1200.00")),
        ("99.99", Decimal("99.99")),
        ("1.500", Decimal("1500.00")),
    ],
)
def test_parse_precio_ars_ok(raw: str, esperado: Decimal) -> None:
    assert parse_precio_ars(raw) == esperado


@pytest.mark.parametrize("raw", ["", "  ", "$", "$0,00", "-500", "no-es-precio"])
def test_parse_precio_ars_invalido(raw: str) -> None:
    assert parse_precio_ars(raw) is None


# ── parse_varietal ──────────────────────────────────────────────────────
def test_parse_varietal_preserva_literal() -> None:
    assert parse_varietal("Malbec") == "malbec"
    assert parse_varietal("blend") == "blend"
    assert parse_varietal("cabernet sauvignon") == "cabernet sauvignon"


def test_parse_varietal_vacio_devuelve_otro() -> None:
    assert parse_varietal("") == "otro"
    assert parse_varietal("   ") == "otro"


# ── extraer_anada ───────────────────────────────────────────────────────
def test_extraer_anada_del_nombre() -> None:
    assert extraer_anada("adrianna mundus malbec 2019 - 100 puntos") == 2019
    assert extraer_anada("cobos volturno") is None


def test_extraer_anada_fallback_usa_descripcion() -> None:
    assert extraer_anada("vino sin año", "cosecha 2021 excelente") == 2021


def test_anada_o_fallback_devuelve_ano_actual_si_none() -> None:
    assert anada_o_fallback(None) == datetime.now(UTC).year


def test_anada_o_fallback_devuelve_valor_si_presente() -> None:
    assert anada_o_fallback(2018) == 2018


# ── parse_alcohol / volumen ─────────────────────────────────────────────
def test_parse_alcohol() -> None:
    assert parse_alcohol("14,10%") == Decimal("14.10")
    assert parse_alcohol("13.5%") == Decimal("13.50")
    assert parse_alcohol("") is None
    assert parse_alcohol("sin alcohol") is None


def test_parse_volumen() -> None:
    assert parse_volumen_ml("750 ml") == 750
    assert parse_volumen_ml("1500 ML") == 1500
    assert parse_volumen_ml("") is None


def test_parse_altura() -> None:
    assert parse_altura("1100") == 1100
    assert parse_altura("1100 msnm") == 1100
    assert parse_altura("") is None


# ── construir_region / descripcion ──────────────────────────────────────
def test_construir_region_combina_lugar_y_pais() -> None:
    region = construir_region("valle de uco, mendoza.", "argentina")
    assert region == "valle de uco, mendoza, argentina"


def test_construir_region_evita_duplicar_pais() -> None:
    region = construir_region("chile", "chile")
    assert region == "chile"


def test_construir_descripcion_corta_usa_ficha_y_corte() -> None:
    desc = construir_descripcion_corta(
        "notas a frutos rojos y chocolate",
        "100% malbec",
        "mendoza, argentina",
    )
    assert "Corte: 100% malbec" in desc
    assert "Origen: mendoza" in desc
    assert "notas a frutos rojos" in desc


def test_construir_descripcion_corta_vacia_devuelve_none() -> None:
    assert construir_descripcion_corta("", "", "") is None


# ── normalizar_fila + fragmento RAG ─────────────────────────────────────
_LINEA_EJEMPLO = {
    "categoria": "vinos",
    "productor": "familia zuccardi",
    "tipo": "tinto",
    "variedad": "malbec",
    "volumen": "750 ml",
    "corte": "100% malbec",
    "alcohol": "14,10%",
    "lugar de elaboracion": "finca piedra infinita, valle de uco. mendoza. argentina.",
    "altura (s.n.m.)": "1100",
    "precio de lista": "$692.380,00",
    "temperatura de servicio": "16º a 18º c",
    "pais": "argentina",
    "ficha tecnica": "notas yodadas, ostras, frutos del bosque.",
    "nombre": "zuccardi finca piedra infinita gravascal",
    "imagen": "zuccardi-piedra-infinita-gravascal",
}


def test_normalizar_fila_mapea_campos_clave() -> None:
    fila = normalizar_fila(_LINEA_EJEMPLO)

    assert fila.imagen_slug == "zuccardi-piedra-infinita-gravascal"
    assert fila.nombre == "zuccardi finca piedra infinita gravascal"
    assert fila.bodega == "familia zuccardi"
    assert fila.varietal == "malbec"
    assert fila.precio_ars == Decimal("692380.00")
    assert fila.alcohol_pct == Decimal("14.10")
    assert fila.volumen_ml == 750
    assert fila.altura_msnm == 1100
    assert "valle de uco" in fila.region
    assert "argentina" in fila.region
    assert fila.es_persistible is True


def test_normalizar_fila_sin_precio_no_persistible() -> None:
    raw = {**_LINEA_EJEMPLO, "precio de lista": ""}
    fila = normalizar_fila(raw)
    assert fila.precio_ars is None
    assert fila.es_persistible is False


def test_fragmento_capa1_incluye_hechos_duros() -> None:
    fila = normalizar_fila(_LINEA_EJEMPLO)
    fragmento = construir_fragmento_capa1(fila)
    assert "familia zuccardi" in fragmento
    assert "Alcohol: 14.10%" in fragmento
    assert "Volumen: 750 ml" in fragmento
    assert "Altura: 1100 m s.n.m." in fragmento


def test_fragmento_capa1_sin_anada_no_incluye_bloque_anada() -> None:
    raw = {**_LINEA_EJEMPLO, "nombre": "vino sin año en etiqueta"}
    fila = normalizar_fila(raw)
    assert extraer_anada(fila.nombre, "") is None
    fragmento = construir_fragmento_capa1(fila)
    assert "Añada:" not in fragmento
