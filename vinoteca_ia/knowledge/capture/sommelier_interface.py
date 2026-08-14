"""Regla de 2 minutos: captura de voz/texto del sumiller y confirmación 1-click."""

from __future__ import annotations

import re
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from schemas.knowledge_fragment import CapaConocimiento, FuenteConocimiento, KnowledgeFragment

_KEYWORD_CAPA: tuple[tuple[CapaConocimiento, tuple[str, ...]], ...] = (
    (
        CapaConocimiento.TERRUNO,
        ("suelo", "altura", "terroir", "terruño", "valle", "clima", "aluvial", "calcáreo"),
    ),
    (
        CapaConocimiento.HISTORIA,
        ("enólogo", "filosofía", "fundó", "historia", "familia", "elaboración"),
    ),
    (
        CapaConocimiento.TENDENCIA,
        ("orgánico", "natural", "puntaje", "parker", "tendencia", "biodinámico"),
    ),
    (
        CapaConocimiento.VOZ_PROPIA,
        ("cata", "nariz", "paladar", "recuerda", "me gusta", "sumiller"),
    ),
    (
        CapaConocimiento.DATO_DURO,
        ("malbec", "cabernet", "añada", "abv", "alcohol", "varietal", "región"),
    ),
)


class KnowledgePoint(BaseModel):
    """Punto extraído de la nota rápida, listo para confirmar."""

    model_config = ConfigDict(extra="forbid")

    capa: CapaConocimiento
    contenido: str
    confianza: float = Field(ge=0.0, le=1.0)


class CaptureDraft(BaseModel):
    """Borrador de captura. No se indexa hasta `confirmar_captura`."""

    model_config = ConfigDict(extra="forbid")

    producto_id: str
    puntos: list[KnowledgePoint]
    requiere_confirmacion: bool = True
    mensaje_sumiller: str


def capture_nota_rapida(texto: str, producto_id: str) -> CaptureDraft:
    """Parsea texto o transcripción de audio y clasifica en las 5 capas.

    Pensado para el mostrador: el sumiller dicta ~2 minutos y confirma
    con un click antes de indexar.
    """
    bruto = (texto or "").strip()
    oraciones = [p.strip() for p in re.split(r"[.\n;]+", bruto) if p.strip()]
    puntos: list[KnowledgePoint] = []
    for oracion in oraciones:
        capa, confianza = _clasificar_capa(oracion)
        puntos.append(KnowledgePoint(capa=capa, contenido=oracion, confianza=confianza))
    n = len(puntos)
    mensaje = (
        f"Capturé {n} punto(s) sobre {producto_id}. "
        "Confirmá con un click para indexarlos en las 5 capas."
        if n
        else "No detecté puntos de conocimiento. Reescribí la nota en una o dos frases."
    )
    return CaptureDraft(
        producto_id=producto_id,
        puntos=puntos,
        requiere_confirmacion=True,
        mensaje_sumiller=mensaje,
    )


def confirmar_captura(draft: CaptureDraft) -> list[KnowledgeFragment]:
    """Convierte el borrador confirmado en fragmentos listos para el indexer."""
    fragments: list[KnowledgeFragment] = []
    for punto in draft.puntos:
        fragments.append(
            KnowledgeFragment(
                id=f"kf-sumiller-{uuid4().hex[:12]}",
                producto_id=draft.producto_id,
                capa=punto.capa,
                fuente=FuenteConocimiento.SUMILLER,
                contenido=punto.contenido,
                validador_humano=True,
            )
        )
    return fragments


def _clasificar_capa(texto: str) -> tuple[CapaConocimiento, float]:
    lower = texto.lower()
    for capa, keywords in _KEYWORD_CAPA:
        hits = sum(1 for kw in keywords if kw in lower)
        if hits:
            return capa, min(0.55 + 0.15 * hits, 0.95)
    return CapaConocimiento.DATO_DURO, 0.4
