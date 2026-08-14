"""Enricher: ficha cruda → fragmentos de 5 capas (LLM T=0.0 + heurística)."""

from __future__ import annotations

import logging
import os
import re
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agents.constitution import make_agent
from schemas.knowledge_fragment import CapaConocimiento, FuenteConocimiento, KnowledgeFragment

logger = logging.getLogger("vinoteca.knowledge.enricher")

_CAPA_HINTS: dict[CapaConocimiento, tuple[str, ...]] = {
    CapaConocimiento.DATO_DURO: (
        "varietal",
        "añada",
        "anada",
        "abv",
        "alcohol",
        "malbec",
        "cabernet",
        "región",
        "region",
        "formato",
    ),
    CapaConocimiento.TERRUNO: (
        "suelo",
        "altura",
        "terroir",
        "terruño",
        "valle",
        "clima",
        "aluvial",
        "msnm",
    ),
    CapaConocimiento.HISTORIA: (
        "enólogo",
        "enologo",
        "filosofía",
        "historia",
        "fund",
        "familia",
        "elaboración",
    ),
    CapaConocimiento.TENDENCIA: (
        "orgánico",
        "organico",
        "natural",
        "puntaje",
        "parker",
        "biodinámico",
        "tendencia",
        "premio",
    ),
    CapaConocimiento.VOZ_PROPIA: (
        "cata",
        "nariz",
        "paladar",
        "sumiller",
        "recuerda",
        "notas de cata",
    ),
}

_PRECIO_STOCK = re.compile(r"\b(precio|stock|ars|\$)\b", re.IGNORECASE)


class EnricherOutput(BaseModel):
    """Salida estructurada del agente enricher."""

    model_config = ConfigDict(extra="forbid")

    fragments: list[KnowledgeFragment] = Field(default_factory=list)


async def enrich_ficha(
    texto: str,
    producto_id: str,
    fuente: FuenteConocimiento = FuenteConocimiento.BODEGA_OFICIAL,
    *,
    use_llm: bool | None = None,
) -> list[KnowledgeFragment]:
    """Parsea una ficha técnica y genera fragmentos de las capas presentes.

    Precio y stock se descartan: viven en SQL. Si el LLM no está disponible
    se usa la heurística de keywords.
    """
    if use_llm is None:
        use_llm = os.environ.get("ENRICHER_USE_LLM", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if use_llm:
        try:
            return await _llm_enrich(texto, producto_id, fuente)
        except Exception as exc:
            logger.warning("enricher LLM fallback heurístico: %s", exc)
    return heuristic_enrich(texto, producto_id, fuente)


def heuristic_enrich(
    texto: str,
    producto_id: str,
    fuente: FuenteConocimiento = FuenteConocimiento.BODEGA_OFICIAL,
) -> list[KnowledgeFragment]:
    """Clasifica párrafos por keywords. Determinista, usable en tests."""
    bloques = [p.strip() for p in re.split(r"\n{2,}|(?<=\.)\s+", texto or "") if p.strip()]
    por_capa: dict[CapaConocimiento, list[str]] = {}
    for bloque in bloques:
        if _PRECIO_STOCK.search(bloque) and not _tiene_hint_cualitativo(bloque):
            continue
        capa = _capa_de(bloque)
        if capa is None:
            continue
        por_capa.setdefault(capa, []).append(bloque)
    fragments: list[KnowledgeFragment] = []
    for capa, partes in por_capa.items():
        contenido = " ".join(partes).strip()
        if not contenido:
            continue
        fragments.append(
            KnowledgeFragment(
                id=f"kf-enr-{uuid4().hex[:12]}",
                producto_id=producto_id,
                capa=capa,
                fuente=fuente,
                contenido=contenido,
                validador_humano=False,
            )
        )
    return fragments


async def _llm_enrich(
    texto: str,
    producto_id: str,
    fuente: FuenteConocimiento,
) -> list[KnowledgeFragment]:
    agent = make_agent(
        name="agente_enricher",
        description="Extrae fragmentos de 5 capas desde fichas técnicas.",
        prompt_file="enricher_v1.md",
        temperature=0.0,
        output_schema=EnricherOutput,
        tool_call_limit=1,
    )
    prompt = (
        f"producto_id={producto_id}\nfuente={fuente.value}\n\nFICHA:\n{texto}\n\n"
        "Emití solo las capas con evidencia. Sin precio ni stock."
    )
    result = await agent.arun(input=prompt, session_id=f"enrich-{producto_id}", stream=False)
    content = getattr(result, "content", result)
    if isinstance(content, EnricherOutput):
        return [_sanitizar(f, producto_id, fuente) for f in content.fragments]
    if isinstance(content, dict) and "fragments" in content:
        parsed = EnricherOutput.model_validate(content)
        return [_sanitizar(f, producto_id, fuente) for f in parsed.fragments]
    return heuristic_enrich(texto, producto_id, fuente)


def _sanitizar(
    fragment: KnowledgeFragment,
    producto_id: str,
    fuente: FuenteConocimiento,
) -> KnowledgeFragment:
    return fragment.model_copy(update={"producto_id": producto_id, "fuente": fuente})


def _capa_de(texto: str) -> CapaConocimiento | None:
    lower = texto.lower()
    mejor: tuple[int, CapaConocimiento] | None = None
    for capa, hints in _CAPA_HINTS.items():
        hits = sum(1 for h in hints if h in lower)
        if hits and (mejor is None or hits > mejor[0]):
            mejor = (hits, capa)
    return mejor[1] if mejor else None


def _tiene_hint_cualitativo(texto: str) -> bool:
    lower = texto.lower()
    return any(h in lower for hints in _CAPA_HINTS.values() for h in hints)
