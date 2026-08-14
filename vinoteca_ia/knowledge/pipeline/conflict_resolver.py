"""Resolución de conflictos por jerarquía de fuente.

SUMILLER > BODEGA_OFICIAL > CRITICO > REDES_SOCIALES (> CONCURSO).
A igual autoridad, gana el fragmento más reciente.
"""

from __future__ import annotations

from collections import defaultdict

from schemas.knowledge_fragment import JerarquiaFuente, KnowledgeFragment


def resolve_conflicts(fragments: list[KnowledgeFragment]) -> list[KnowledgeFragment]:
    """Un ganador por `(producto_id, capa)` según `JerarquiaFuente`."""
    grupos: dict[tuple[str, int], list[KnowledgeFragment]] = defaultdict(list)
    for fragment in fragments:
        grupos[(fragment.producto_id, int(fragment.capa))].append(fragment)

    ganadores: list[KnowledgeFragment] = []
    for grupo in grupos.values():
        grupo.sort(
            key=lambda f: (
                JerarquiaFuente.prioridad(f.fuente),
                -f.created_at.timestamp(),
            )
        )
        ganadores.append(grupo[0])
    ganadores.sort(key=lambda f: (f.producto_id, int(f.capa)))
    return ganadores


def fuente_gana(izquierda: KnowledgeFragment, derecha: KnowledgeFragment) -> KnowledgeFragment:
    """Elige el fragmento de mayor autoridad (o el más nuevo si empatan)."""
    cmp = JerarquiaFuente.comparar(izquierda.fuente, derecha.fuente)
    if cmp < 0:
        return izquierda
    if cmp > 0:
        return derecha
    return izquierda if izquierda.created_at >= derecha.created_at else derecha
