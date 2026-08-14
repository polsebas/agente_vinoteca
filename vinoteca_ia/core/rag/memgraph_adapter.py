"""Adapter MemGraphRAG: memoria de 3 capas + PPR sobre el grafo de vinos.

SQL (asyncpg) sigue siendo la única fuente de precio/stock. Este módulo
solo indexa y recupera conocimiento cualitativo (terruño, maridaje, voz).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from memgraphrag_core.domain.models import (
    EDGE_EVIDENCE_IN,
    EDGE_INSTANTIATES,
    LAYER_M_FAC,
    LAYER_M_ONT,
    LAYER_M_PAS,
    NODE_FACT,
    NODE_PASSAGE,
    NODE_SCHEMA,
    Fact,
    GlobalMemoryState,
    Passage,
)
from memgraphrag_core.infrastructure.in_memory_vector_store import InMemoryVectorStore
from memgraphrag_core.infrastructure.networkx_graph_store import NetworkXGraphStore
from memgraphrag_core.interfaces.graph_store import BaseGraphStore, GraphEdge, GraphNode
from memgraphrag_core.interfaces.vector_store import BaseVectorStore
from memgraphrag_core.retrieval.ppr_engine import LayeredPPRCalculator
from memgraphrag_core.retrieval.retriever import MemoryGuidedRetriever, RetrievalResult

from core.rag.wine_graph_schema import (
    ONTOLOGY_TAU,
    PERFIL_CAPAS,
    PERFIL_LAYER_WEIGHTS,
    PPR_LAMBDA,
    PPR_MAX_ITER,
    RELATION_WEIGHTS,
    WineTriple,
    slug_a_nombre,
)
from schemas.customer_profile import PerfilClienteTipo
from schemas.knowledge_fragment import CapaConocimiento, FuenteConocimiento, KnowledgeFragment
from schemas.tool_responses import RAGResult

logger = logging.getLogger("vinoteca.rag.memgraph")


class BoundedPPRCalculator(LayeredPPRCalculator):
    """PPR con λ=0.5 y tope de 10 iteraciones de potencia."""

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("alpha", PPR_LAMBDA)
        kwargs.setdefault("relation_weights", RELATION_WEIGHTS)
        super().__init__(**kwargs)
        self.max_iter = PPR_MAX_ITER

    async def run(
        self,
        graph_store,
        ont_hits,
        fac_hits,
        pas_hits,
        *,
        alpha=None,
        max_iter=None,
        tol=1e-6,
    ):
        return await super().run(
            graph_store,
            ont_hits,
            fac_hits,
            pas_hits,
            alpha=self.alpha if alpha is None else alpha,
            max_iter=self.max_iter if max_iter is None else max_iter,
            tol=tol,
        )


@dataclass
class MemGraphEngine:
    """Estado vivo de MemGraphRAG para la vinoteca."""

    memory: GlobalMemoryState
    graph: BaseGraphStore
    vectors: BaseVectorStore
    retriever: MemoryGuidedRetriever
    producto_index: dict[str, str] = field(default_factory=dict)


_ENGINE: MemGraphEngine | None = None


def set_engine(engine: MemGraphEngine | None) -> None:
    """Inyecta un engine (tests) o resetea el singleton."""
    global _ENGINE
    _ENGINE = engine


def build_engine(
    *,
    memory: GlobalMemoryState | None = None,
    graph: BaseGraphStore | None = None,
    vectors: BaseVectorStore | None = None,
    perfil_cliente: PerfilClienteTipo | None = None,
) -> MemGraphEngine:
    mem = memory or GlobalMemoryState(tau=ONTOLOGY_TAU)
    g = graph or NetworkXGraphStore()
    v = vectors or InMemoryVectorStore()
    retriever = _make_retriever(mem, g, v, perfil_cliente)
    return MemGraphEngine(memory=mem, graph=g, vectors=v, retriever=retriever)


def get_engine() -> MemGraphEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = build_engine()
    return _ENGINE


def ping_graph() -> bool:
    """Readiness de MemGraphRAG: engine + grafo instanciados."""
    try:
        engine = get_engine()
        return engine is not None and engine.graph is not None
    except Exception:
        return False


def _make_retriever(
    memory: GlobalMemoryState,
    graph: BaseGraphStore,
    vectors: BaseVectorStore,
    perfil: PerfilClienteTipo | None,
) -> MemoryGuidedRetriever:
    layer_weights = PERFIL_LAYER_WEIGHTS.get(
        perfil or PerfilClienteTipo.GENERAL,
        PERFIL_LAYER_WEIGHTS[PerfilClienteTipo.GENERAL],
    )
    return MemoryGuidedRetriever(
        memory_state=memory,
        graph_store=graph,
        vector_store=vectors,
        alpha_ppr=PPR_LAMBDA,
        top_k_passages=8,
        top_k_facts=12,
        layer_weights=layer_weights,
        relation_weights=RELATION_WEIGHTS,
        ppr_calculator=BoundedPPRCalculator(layer_weights=layer_weights),
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or "x"


async def ingest_fragment(
    fragment: KnowledgeFragment,
    triples: list[WineTriple],
    *,
    engine: MemGraphEngine | None = None,
) -> int:
    """Incorpora un fragmento a M_pas / M_fac / M_ont y al grafo de dominio."""
    eng = engine or get_engine()
    passage = Passage(
        id=fragment.id,
        text=fragment.contenido,
        metadata={
            "producto_id": fragment.producto_id,
            "nombre_vino": slug_a_nombre(fragment.producto_id),
            "capa": int(fragment.capa),
            "fuente": fragment.fuente.value,
            "validador_humano": fragment.validador_humano,
        },
    )
    eng.memory.add_passage(passage)
    eng.producto_index[fragment.producto_id] = slug_a_nombre(fragment.producto_id)
    await eng.vectors.add_texts(
        texts=[passage.text],
        ids=[passage.id],
        metadatas=[passage.metadata],
        namespace=LAYER_M_PAS,
    )
    await eng.graph.add_node(
        GraphNode(
            id=f"pas_{passage.id}",
            label=NODE_PASSAGE,
            properties=dict(passage.metadata),
        )
    )

    accepted = 0
    for triple in triples:
        schema = eng.memory.register_schema_candidate(
            triple.head_type.value, triple.relation.value, triple.tail_type.value
        )
        await eng.vectors.add_texts(
            texts=[f"{schema.head_type} {schema.relation} {schema.tail_type}"],
            ids=[schema.schema_key],
            namespace=LAYER_M_ONT,
        )
        await eng.graph.add_node(
            GraphNode(
                id=f"ont_{schema.schema_key}",
                label=NODE_SCHEMA,
                properties={"frequency": schema.frequency, "capa": int(triple.capa)},
            )
        )
        fact = Fact(
            head_entity=triple.head_entity,
            head_type=triple.head_type.value,
            relation=triple.relation.value,
            tail_entity=triple.tail_entity,
            tail_type=triple.tail_type.value,
            passage_ids=[fragment.id],
            confidence=triple.confidence,
            metadata={
                "producto_id": triple.producto_id,
                "capa": int(triple.capa),
                "fuente": triple.fuente.value,
            },
        )
        stored = eng.memory.add_fact(fact)
        if stored is None:
            continue
        accepted += 1
        await _sync_fact(eng, stored, triple)
    return accepted


async def _sync_fact(eng: MemGraphEngine, fact: Fact, triple: WineTriple) -> None:
    await eng.vectors.add_texts(
        texts=[f"{fact.head_entity} {fact.relation} {fact.tail_entity}"],
        ids=[fact.fact_key],
        metadatas=[dict(fact.metadata)],
        namespace=LAYER_M_FAC,
    )
    fid = f"fact_{fact.fact_key}"
    await eng.graph.add_node(
        GraphNode(
            id=fid,
            label=NODE_FACT,
            properties={
                "head": fact.head_entity,
                "relation": fact.relation,
                "tail": fact.tail_entity,
                "capa": int(triple.capa),
                "fuente": triple.fuente.value,
                "producto_id": triple.producto_id,
            },
        )
    )
    await eng.graph.add_edge(
        GraphEdge(source_id=f"ont_{fact.schema_key}", target_id=fid, relation=EDGE_INSTANTIATES)
    )
    for pid in fact.passage_ids:
        await eng.graph.add_edge(
            GraphEdge(source_id=fid, target_id=f"pas_{pid}", relation=EDGE_EVIDENCE_IN)
        )

    vino_id = f"ent_vino_{_slug(triple.producto_id)}"
    tail_id = f"ent_{triple.tail_type.value.lower()}_{_slug(triple.tail_entity)}"
    await eng.graph.add_node(
        GraphNode(
            id=vino_id,
            label="VINO",
            properties={
                "producto_id": triple.producto_id,
                "nombre": triple.head_entity,
                "capa": int(triple.capa),
                "fuente": triple.fuente.value,
            },
        )
    )
    await eng.graph.add_node(
        GraphNode(
            id=tail_id,
            label=triple.tail_type.value,
            properties={
                "nombre": triple.tail_entity,
                "capa": int(triple.capa),
                "fuente": triple.fuente.value,
            },
        )
    )
    await eng.graph.add_edge(
        GraphEdge(
            source_id=vino_id,
            target_id=tail_id,
            relation=triple.relation.value,
            properties={"capa": int(triple.capa), "fuente": triple.fuente.value},
        )
    )
    await eng.graph.add_edge(
        GraphEdge(
            source_id=vino_id,
            target_id=f"pas_{fact.passage_ids[0]}",
            relation=EDGE_EVIDENCE_IN,
        )
    )


async def query_memgraph_rag(
    query: str,
    capa: CapaConocimiento | None = None,
    perfil_cliente: PerfilClienteTipo | None = None,
    top_k: int = 5,
    *,
    engine: MemGraphEngine | None = None,
) -> list[RAGResult]:
    """Retrieval structure-aware: seeds vectoriales → PPR → RAGResult.

    Si el grafo no tiene candidatos, devuelve lista vacía para que el
    retriever haga fallback a similitud coseno sobre `wine_knowledge`.
    """
    if not query.strip():
        return []
    try:
        eng = engine or get_engine()
        retriever = _make_retriever(eng.memory, eng.graph, eng.vectors, perfil_cliente)
        result = await retriever.retrieve(query.strip())
    except Exception:
        logger.exception("MemGraphRAG falló; el caller debe usar fallback denso")
        return []

    capas_ok = None
    if capa is not None:
        capas_ok = {int(capa)}
    elif perfil_cliente is not None:
        capas_ok = {int(c) for c in PERFIL_CAPAS.get(perfil_cliente, ())}

    mapped = _to_rag_results(result, eng, capas_ok, top_k)
    if mapped:
        return mapped
    if capas_ok is not None:
        return _to_rag_results(result, eng, None, top_k)
    return []


def _to_rag_results(
    result: RetrievalResult,
    eng: MemGraphEngine,
    capas_ok: set[int] | None,
    top_k: int,
) -> list[RAGResult]:
    facts_by_pas: dict[str, list[Fact]] = {}
    for fact in result.facts:
        for pid in fact.passage_ids:
            facts_by_pas.setdefault(pid, []).append(fact)

    out: list[RAGResult] = []
    seen: set[str] = set()
    for passage in result.passages:
        meta = passage.metadata or {}
        capa_raw = meta.get("capa")
        capa_int = int(capa_raw) if capa_raw not in (None, "") else None
        if capas_ok is not None and capa_int is not None and capa_int not in capas_ok:
            continue
        facts = facts_by_pas.get(passage.id, [])
        vino_id = str(
            meta.get("producto_id")
            or meta.get("vino_id")
            or _producto_desde_facts(facts)
            or passage.id
        )
        if vino_id in seen:
            continue
        seen.add(vino_id)
        triples = [f"({f.head_entity})-[:{f.relation}]->({f.tail_entity})" for f in facts]
        nodos = sorted({f.head_entity for f in facts} | {f.tail_entity for f in facts})
        contenido = passage.text
        if triples:
            contenido = f"{passage.text}\nTriples: {'; '.join(triples)}"
        score = float(
            result.hybrid_scores.get(f"pas_{passage.id}")
            or result.node_scores.get(f"pas_{passage.id}")
            or 0.0
        )
        out.append(
            RAGResult(
                vino_id=vino_id,
                nombre_vino=str(
                    meta.get("nombre_vino") or eng.producto_index.get(vino_id) or vino_id
                ),
                capa=_capa_de(capa_int, facts),
                contenido=contenido,
                score=score,
                triples=triples,
                nodos=nodos,
                modo_retrieval=result.retrieval_mode,
            )
        )
        if len(out) >= top_k:
            return out

    if out:
        return out

    for fact in result.facts:
        capa_int = int(fact.metadata.get("capa") or 0) or None
        if capas_ok is not None and capa_int is not None and capa_int not in capas_ok:
            continue
        vino_id = str(fact.metadata.get("producto_id") or fact.head_entity)
        if vino_id in seen:
            continue
        seen.add(vino_id)
        triple = f"({fact.head_entity})-[:{fact.relation}]->({fact.tail_entity})"
        score = float(result.hybrid_scores.get(f"fact_{fact.fact_key}") or fact.confidence)
        out.append(
            RAGResult(
                vino_id=vino_id,
                nombre_vino=fact.head_entity,
                capa=_capa_de(capa_int, [fact]),
                contenido=triple,
                score=score,
                triples=[triple],
                nodos=[fact.head_entity, fact.tail_entity],
                modo_retrieval=result.retrieval_mode,
            )
        )
        if len(out) >= top_k:
            break
    return out


def _producto_desde_facts(facts: list[Fact]) -> str | None:
    for fact in facts:
        pid = fact.metadata.get("producto_id")
        if pid:
            return str(pid)
    return None


def _capa_de(capa_int: int | None, facts: list[Fact]) -> CapaConocimiento:
    if capa_int in {1, 2, 3, 4, 5}:
        return CapaConocimiento(capa_int)
    for fact in facts:
        raw = fact.metadata.get("capa")
        if raw in {1, 2, 3, 4, 5} or str(raw) in {"1", "2", "3", "4", "5"}:
            return CapaConocimiento(int(raw))
    return CapaConocimiento.VOZ_PROPIA


def _fuente_desde_sql(raw: str | None) -> FuenteConocimiento:
    try:
        return FuenteConocimiento((raw or "").strip().lower())
    except ValueError:
        if (raw or "").lower() in {"seed", "manual", "sumiller"}:
            return FuenteConocimiento.SUMILLER
        return FuenteConocimiento.BODEGA_OFICIAL


async def hydrate_engine_from_sql(*, limit: int = 400) -> int:
    """Carga fragmentos SQL en el grafo in-memory al arrancar el proceso."""
    from core.rag.wine_graph_schema import extract_wine_triples
    from storage.postgres import fetch_all

    rows = await fetch_all(
        """
        SELECT wk.id,
               wk.producto_id,
               wk.capa,
               wk.contenido,
               wk.fuente,
               COALESCE(wk.validador_humano, FALSE) AS validador_humano
        FROM wine_knowledge wk
        JOIN vinos v ON v.id = wk.producto_id
        WHERE v.activo = TRUE
          AND wk.contenido IS NOT NULL
          AND length(wk.contenido) > 20
        ORDER BY CASE WHEN wk.fuente IN ('sumiller', 'seed') THEN 0 ELSE 1 END,
                 wk.capa DESC,
                 wk.created_at DESC
        LIMIT $1
        """,
        limit,
    )
    engine = get_engine()
    ingested = 0
    for row in rows:
        capa_raw = int(row["capa"] or 5)
        if capa_raw not in {1, 2, 3, 4, 5}:
            continue
        fragment = KnowledgeFragment(
            id=str(row["id"]),
            producto_id=str(row["producto_id"]),
            capa=CapaConocimiento(capa_raw),
            fuente=_fuente_desde_sql(row["fuente"]),
            contenido=str(row["contenido"]),
            validador_humano=bool(row["validador_humano"]),
        )
        triples = extract_wine_triples(fragment)
        await ingest_fragment(fragment, triples, engine=engine)
        ingested += 1
    logger.info("MemGraphRAG hidratado: %s fragmentos", ingested)
    return ingested
