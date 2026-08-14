"""Onboarding de un SKU nuevo: umbral ≥ 3/5 capas antes de publicar."""

from __future__ import annotations

from schemas.wine_catalog import WineProduct

UMBRAL_CAPAS_PUBLICACION = 3


def evaluar_nuevo_vino(wine: WineProduct) -> WineProduct:
    """Marca `activo=True` solo si hay al menos 3 capas de conocimiento.

    `apto_publicacion` lo deriva el validador de `WineProduct`
    (`activo` AND `len(capas_disponibles) >= 3`).
    """
    capas = {int(capa) for capa in wine.capas_disponibles}
    completo = len(capas) >= UMBRAL_CAPAS_PUBLICACION
    payload = wine.model_dump()
    payload["activo"] = completo
    return WineProduct.model_validate(payload)


def capas_completas(wine: WineProduct) -> bool:
    return len({int(c) for c in wine.capas_disponibles}) >= UMBRAL_CAPAS_PUBLICACION
