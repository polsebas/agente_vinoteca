"""Funciones puras de normalización para la ingesta del catálogo.

Todo lo que convierte strings crudos del archivo `product_details.txt` al
modelo de dominio vive acá. Sin efectos secundarios: fácil de testear sin
Postgres ni red.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from scripts.ingest.models import FilaCatalogo

_RE_ANADA = re.compile(r"\b(19\d{2}|20\d{2})\b")
_RE_ALCOHOL = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_RE_VOLUMEN = re.compile(r"(\d+(?:[.,]\d+)?)\s*ml", re.IGNORECASE)
_RE_ALTURA = re.compile(r"(\d{3,5})")


def _texto(valor: Any) -> str:
    """Devuelve `valor` como string recortado, o cadena vacía."""
    if valor is None:
        return ""
    return str(valor).strip()


def parse_precio_ars(raw: str) -> Decimal | None:
    """Convierte `$879.935,00` → `Decimal("879935.00")`.

    Acepta también formatos sin signo ($), sin decimales o con espacios.
    Si hay coma, se asume formato AR (miles con ``.`` y decimal con ``,``).
    Sin coma y con un solo punto: si la parte decimal tiene 3 dígitos se trata
    como separador de miles (p. ej. ``1.500`` → 1500); si no, como decimal US
    (p. ej. ``99.99``).
    Devuelve `None` si la cadena está vacía o no se puede parsear.
    """
    texto = _texto(raw)
    if not texto:
        return None
    limpio = texto.replace("$", "").replace(" ", "").replace("ars", "").replace("ARS", "")
    if not limpio:
        return None
    if "," in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    else:
        partes = limpio.split(".")
        if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit() and len(partes[1]) == 3:
            limpio = partes[0] + partes[1]
        elif len(partes) > 2:
            limpio = limpio.replace(".", "")
    try:
        valor = Decimal(limpio)
    except InvalidOperation:
        return None
    if valor <= 0:
        return None
    return valor.quantize(Decimal("0.01"))


def parse_varietal(raw: str) -> str:
    """Normaliza la variedad a lower-strip.

    La columna `vinos.varietal` es TEXT libre (las tools la muestran tal
    cual). Para blends o valores desconocidos devolvemos `'otro'` solo
    si no hay texto; en caso contrario preservamos el literal para no
    perder información de catálogo.
    """
    texto = _texto(raw).lower()
    if not texto:
        return "otro"
    return texto


def extraer_anada(nombre: str, descripcion: str = "") -> int | None:
    """Busca un año plausible (1900-2099) en el nombre o la descripción."""
    for fuente in (nombre, descripcion):
        texto = _texto(fuente)
        if not texto:
            continue
        match = _RE_ANADA.search(texto)
        if match:
            return int(match.group(1))
    return None


def anada_o_fallback(anada: int | None) -> int:
    """Política de fallback para añada: año actual si no se pudo extraer.

    El schema `PrecioItem.anada: int` no acepta None; persistir un NULL en
    `vinos.anada_actual` rompería a las tools de precio. Devolvemos el año
    corriente como marcador razonable cuando no hay año explícito.
    """
    if anada is not None:
        return anada
    return datetime.now(UTC).year


def parse_alcohol(raw: str) -> Decimal | None:
    """`14,10%` → `Decimal("14.10")`."""
    texto = _texto(raw)
    if not texto:
        return None
    match = _RE_ALCOHOL.search(texto.replace(",", "."))
    if not match:
        return None
    try:
        return Decimal(match.group(1)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def parse_volumen_ml(raw: str) -> int | None:
    """`750 ml` → `750`."""
    texto = _texto(raw)
    if not texto:
        return None
    match = _RE_VOLUMEN.search(texto)
    if not match:
        return None
    try:
        return int(Decimal(match.group(1).replace(",", ".")))
    except (InvalidOperation, ValueError):
        return None


def parse_altura(raw: str) -> int | None:
    """`1100` o `1100 msnm` → `1100`."""
    texto = _texto(raw)
    if not texto:
        return None
    match = _RE_ALTURA.search(texto)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def construir_region(lugar: str, pais: str) -> str:
    """Combina `lugar de elaboracion` + `pais` en un string de región.

    Recorta puntos y comas finales, limita a 200 caracteres para entrar en
    columnas TEXT sin sorpresas (Postgres no tiene límite pero evitamos
    datos ruidosos del scraping).
    """
    lugar_limpio = _texto(lugar).rstrip(".").rstrip(",").strip()
    pais_limpio = _texto(pais).rstrip(".").strip()
    partes = [p for p in (lugar_limpio, pais_limpio) if p]
    if not partes:
        return ""
    if len(partes) == 2 and pais_limpio.lower() in lugar_limpio.lower():
        return lugar_limpio[:200]
    return ", ".join(partes)[:200]


def construir_descripcion_corta(ficha: str, corte: str, region: str) -> str | None:
    """Resumen narrativo usado como `vinos.descripcion` (≤ 500 chars)."""
    partes: list[str] = []
    corte_limpio = _texto(corte)
    if corte_limpio:
        partes.append(f"Corte: {corte_limpio}.")
    region_limpia = _texto(region)
    if region_limpia:
        partes.append(f"Origen: {region_limpia}.")
    ficha_limpia = _texto(ficha)
    if ficha_limpia:
        partes.append(ficha_limpia)
    texto = " ".join(partes).strip()
    if not texto:
        return None
    return texto[:500]


def construir_fragmento_capa1(fila: FilaCatalogo) -> str:
    """Texto para `wine_knowledge` capa 1 (hechos duros) listo para embeddings."""
    bloques: list[str] = [f"{fila.nombre} — {fila.bodega}."]
    if fila.varietal:
        bloques.append(f"Varietal: {fila.varietal}.")
    if fila.corte:
        bloques.append(f"Corte: {fila.corte}.")
    if fila.anada_actual is not None:
        bloques.append(f"Añada: {fila.anada_actual}.")
    if fila.alcohol_pct is not None:
        bloques.append(f"Alcohol: {fila.alcohol_pct}%.")
    if fila.volumen_ml is not None:
        bloques.append(f"Volumen: {fila.volumen_ml} ml.")
    if fila.region:
        bloques.append(f"Origen: {fila.region}.")
    if fila.altura_msnm is not None:
        bloques.append(f"Altura: {fila.altura_msnm} m s.n.m.")
    if fila.ficha_tecnica:
        bloques.append(fila.ficha_tecnica)
    return " ".join(bloques).strip()


def normalizar_fila(raw: dict[str, Any]) -> FilaCatalogo:
    """Convierte un dict crudo del NDJSON en `FilaCatalogo`.

    Sólo realiza normalización sintáctica; la decisión de persistir o no
    queda para el loop principal vía `FilaCatalogo.es_persistible`.
    """
    nombre = _texto(raw.get("nombre"))
    ficha = _texto(raw.get("ficha tecnica"))
    region = construir_region(raw.get("lugar de elaboracion", ""), raw.get("pais", ""))
    anada = extraer_anada(nombre, ficha)

    return FilaCatalogo(
        imagen_slug=_texto(raw.get("imagen")),
        nombre=nombre,
        bodega=_texto(raw.get("productor")),
        varietal=parse_varietal(raw.get("variedad", "")),
        region=region,
        precio_ars=parse_precio_ars(raw.get("precio de lista", "")),
        anada_actual=anada,
        descripcion=construir_descripcion_corta(ficha, raw.get("corte", ""), region),
        ficha_tecnica=ficha or None,
        corte=_texto(raw.get("corte")) or None,
        alcohol_pct=parse_alcohol(raw.get("alcohol", "")),
        volumen_ml=parse_volumen_ml(raw.get("volumen", "")),
        tipo=_texto(raw.get("tipo")) or None,
        pais=_texto(raw.get("pais")) or None,
        altura_msnm=parse_altura(raw.get("altura (s.n.m.)", "")),
    )
