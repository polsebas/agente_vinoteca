"""Esquema del grafo cualitativo de vinos (nunca precio ni stock).

Nodos y aristas llevan `capa` (1–5) y `fuente`. El SQL transaccional no
entra acá: este grafo solo modela maridaje, terruño, filosofía y voz del
sumiller.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from schemas.customer_profile import PerfilClienteTipo
from schemas.knowledge_fragment import CapaConocimiento, FuenteConocimiento, KnowledgeFragment
from schemas.wine_catalog import Varietal

PPR_LAMBDA = 0.5
PPR_MAX_ITER = 10
ONTOLOGY_TAU = 1


class EntidadGrafo(StrEnum):
    VINO = "VINO"
    BODEGA = "BODEGA"
    ENOLOGO = "ENOLOGO"
    TERRUNO_REGION = "TERRUNO_REGION"
    VARIETAL = "VARIETAL"
    MARIDAJE = "MARIDAJE"
    OCASION = "OCASION"
    ESTILO_FILOSOFIA = "ESTILO_FILOSOFIA"
    NOTA_SUMILLER = "NOTA_SUMILLER"


class RelacionGrafo(StrEnum):
    PRODUCIDO_POR = "PRODUCIDO_POR"
    CREADO_POR = "CREADO_POR"
    ORIGEN_TERRUNO = "ORIGEN_TERRUNO"
    VARIETAL_COMPOSICION = "VARIETAL_COMPOSICION"
    MARIDA_CON = "MARIDA_CON"
    IDEAL_PARA = "IDEAL_PARA"
    TIENE_VOZ_SUMILLER = "TIENE_VOZ_SUMILLER"


RELATION_WEIGHTS: dict[str, float] = {
    "INSTANTIATES": 1.0,
    "EVIDENCE_IN": 1.2,
    RelacionGrafo.PRODUCIDO_POR: 1.0,
    RelacionGrafo.CREADO_POR: 1.15,
    RelacionGrafo.ORIGEN_TERRUNO: 1.3,
    RelacionGrafo.VARIETAL_COMPOSICION: 1.0,
    RelacionGrafo.MARIDA_CON: 1.35,
    RelacionGrafo.IDEAL_PARA: 1.25,
    RelacionGrafo.TIENE_VOZ_SUMILLER: 1.4,
}

PERFIL_LAYER_WEIGHTS: dict[PerfilClienteTipo, dict[str, float]] = {
    PerfilClienteTipo.COLECCIONISTA: {"M_ont": 0.40, "M_fac": 0.45, "M_pas": 0.15},
    PerfilClienteTipo.CURIOSO: {"M_ont": 0.20, "M_fac": 0.30, "M_pas": 0.50},
    PerfilClienteTipo.OCASION: {"M_ont": 0.15, "M_fac": 0.55, "M_pas": 0.30},
    PerfilClienteTipo.GENERAL: {"M_ont": 0.20, "M_fac": 0.50, "M_pas": 0.30},
}

PERFIL_CAPAS: dict[PerfilClienteTipo, tuple[CapaConocimiento, ...]] = {
    PerfilClienteTipo.COLECCIONISTA: (
        CapaConocimiento.TERRUNO,
        CapaConocimiento.HISTORIA,
        CapaConocimiento.VOZ_PROPIA,
    ),
    PerfilClienteTipo.CURIOSO: (
        CapaConocimiento.HISTORIA,
        CapaConocimiento.TENDENCIA,
    ),
    PerfilClienteTipo.OCASION: (
        CapaConocimiento.DATO_DURO,
        CapaConocimiento.TENDENCIA,
        CapaConocimiento.VOZ_PROPIA,
    ),
    PerfilClienteTipo.GENERAL: tuple(CapaConocimiento),
}

_BODEGA_ALIASES: dict[str, str] = {
    "catena": "Catena Zapata",
    "catena zapata": "Catena Zapata",
    "bodega catena": "Catena Zapata",
    "achaval": "Achaval Ferrer",
    "achaval ferrer": "Achaval Ferrer",
    "zuccardi": "Zuccardi",
    "rutini": "Rutini",
}

_TERRUNO_RE = re.compile(
    r"(?i)\b("
    r"Valle de Uco|Gualtallary|Paraje Altamira|Altamira|Luj[aá]n de Cuyo|"
    r"Maip[uú]|Patagonia|Mendoza|Uco Valley|Agrelo|Vista Flores"
    r")\b"
)
_BODEGA_RE = re.compile(
    r"(?i)\b(?:bodega|winery)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑ]+){0,3})"
)
_ENOLOGO_RE = re.compile(
    r"(?i)\b(?:en[oó]log[oa]|winemaker)\s+"
    r"([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑ]+){0,2})"
)
_MARIDAJE_RE = re.compile(r"(?i)marida(?:\s+bien)?\s+con\s+([^.;:\n]+)")
_OCASION_RE = re.compile(r"(?i)(?:ideal para|perfecto para|para un|para una)\s+([^.;:\n]+)")


class WineTriple(BaseModel):
    """Triple cualitativo listo para M_fac / grafo de dominio."""

    model_config = ConfigDict(extra="forbid")

    head_entity: str
    head_type: EntidadGrafo = EntidadGrafo.VINO
    relation: RelacionGrafo
    tail_entity: str
    tail_type: EntidadGrafo
    capa: CapaConocimiento
    fuente: FuenteConocimiento
    producto_id: str
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)


def canonical_entity(nombre: str, tipo: EntidadGrafo) -> str:
    """Resuelve alias de bodega/región a una forma canónica."""
    key = re.sub(r"\s+", " ", nombre.strip().lower())
    if tipo == EntidadGrafo.BODEGA and key in _BODEGA_ALIASES:
        return _BODEGA_ALIASES[key]
    if tipo == EntidadGrafo.TERRUNO_REGION:
        return " ".join(w.capitalize() if w.lower() != "de" else "de" for w in key.split())
    return nombre.strip()


def slug_a_nombre(producto_id: str) -> str:
    return re.sub(r"[-_]+", " ", producto_id).strip().title()


def extract_wine_triples(fragment: KnowledgeFragment) -> list[WineTriple]:
    """Extrae triples del fragmento según capa, metadata y heurísticas.

    No llama al LLM: el indexer puede complementar con A_ext de MemGraphRAG.
    """
    vino = slug_a_nombre(fragment.producto_id)
    texto = fragment.contenido
    meta = fragment.metadata
    triples: list[WineTriple] = []

    def add(
        relation: RelacionGrafo,
        tail: str,
        tail_type: EntidadGrafo,
        *,
        confidence: float = 0.85,
    ) -> None:
        tail_c = canonical_entity(tail, tail_type)
        if not tail_c:
            return
        key = (relation, tail_c.lower())
        if any(t.relation == key[0] and t.tail_entity.lower() == key[1] for t in triples):
            return
        triples.append(
            WineTriple(
                head_entity=vino,
                relation=relation,
                tail_entity=tail_c,
                tail_type=tail_type,
                capa=fragment.capa,
                fuente=fragment.fuente,
                producto_id=fragment.producto_id,
                confidence=confidence,
            )
        )

    if meta.get("bodega"):
        add(RelacionGrafo.PRODUCIDO_POR, meta["bodega"], EntidadGrafo.BODEGA)
    if meta.get("enologo") or meta.get("enólogo"):
        add(
            RelacionGrafo.CREADO_POR,
            meta.get("enologo") or meta["enólogo"],
            EntidadGrafo.ENOLOGO,
        )
    if meta.get("region") or meta.get("terruno"):
        add(
            RelacionGrafo.ORIGEN_TERRUNO,
            meta.get("region") or meta["terruno"],
            EntidadGrafo.TERRUNO_REGION,
        )
    if meta.get("varietal"):
        add(RelacionGrafo.VARIETAL_COMPOSICION, meta["varietal"], EntidadGrafo.VARIETAL)
    if meta.get("maridaje"):
        add(RelacionGrafo.MARIDA_CON, meta["maridaje"], EntidadGrafo.MARIDAJE)
    if meta.get("ocasion") or meta.get("ocasión"):
        add(
            RelacionGrafo.IDEAL_PARA,
            meta.get("ocasion") or meta["ocasión"],
            EntidadGrafo.OCASION,
        )

    if m := _BODEGA_RE.search(texto):
        add(RelacionGrafo.PRODUCIDO_POR, m.group(1), EntidadGrafo.BODEGA, confidence=0.8)
    if m := _ENOLOGO_RE.search(texto):
        add(RelacionGrafo.CREADO_POR, m.group(1), EntidadGrafo.ENOLOGO, confidence=0.8)
    if m := _TERRUNO_RE.search(texto):
        add(RelacionGrafo.ORIGEN_TERRUNO, m.group(1), EntidadGrafo.TERRUNO_REGION, confidence=0.9)
    if m := _MARIDAJE_RE.search(texto):
        add(RelacionGrafo.MARIDA_CON, m.group(1).strip(), EntidadGrafo.MARIDAJE, confidence=0.85)
    if m := _OCASION_RE.search(texto):
        add(RelacionGrafo.IDEAL_PARA, m.group(1).strip(), EntidadGrafo.OCASION, confidence=0.8)

    texto_l = texto.lower()
    for varietal in Varietal:
        token = varietal.value.replace("_", " ")
        if token in texto_l or (varietal == Varietal.TORRONTES and "torrontés" in texto_l):
            add(RelacionGrafo.VARIETAL_COMPOSICION, token, EntidadGrafo.VARIETAL, confidence=0.8)

    if fragment.capa == CapaConocimiento.VOZ_PROPIA:
        add(
            RelacionGrafo.TIENE_VOZ_SUMILLER,
            texto[:80].strip(),
            EntidadGrafo.NOTA_SUMILLER,
            confidence=1.0,
        )

    return triples
