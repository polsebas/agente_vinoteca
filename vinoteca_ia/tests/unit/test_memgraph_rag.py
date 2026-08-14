"""MemGraphRAG: PPR, multi-hop, fallback denso y mapeo a RAGResult."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.rag.memgraph_adapter import (
    BoundedPPRCalculator,
    build_engine,
    ingest_fragment,
    query_memgraph_rag,
)
from core.rag.retriever import search_catalog_rag
from core.rag.wine_graph_schema import (
    PPR_LAMBDA,
    PPR_MAX_ITER,
    EntidadGrafo,
    RelacionGrafo,
    canonical_entity,
    extract_wine_triples,
)
from knowledge.pipeline.indexer import index_knowledge_fragment
from schemas.customer_profile import PerfilClienteTipo
from schemas.knowledge_fragment import CapaConocimiento, FuenteConocimiento, KnowledgeFragment
from schemas.tool_responses import RAGResult


def _frag(
    fid: str,
    producto_id: str,
    contenido: str,
    capa: CapaConocimiento,
    **meta: str,
) -> KnowledgeFragment:
    return KnowledgeFragment(
        id=fid,
        producto_id=producto_id,
        capa=capa,
        fuente=FuenteConocimiento.SUMILLER,
        contenido=contenido,
        validador_humano=True,
        metadata=meta,
    )


def test_extract_triples_terruno_maridaje_y_alias():
    frag = _frag(
        "p1",
        "achaval-malbec-2020",
        "Bodega Achaval produce este Malbec en Valle de Uco. Marida con asado.",
        CapaConocimiento.TERRUNO,
        bodega="catena",
    )
    triples = extract_wine_triples(frag)
    relaciones = {t.relation for t in triples}
    assert RelacionGrafo.ORIGEN_TERRUNO in relaciones
    assert RelacionGrafo.MARIDA_CON in relaciones
    assert RelacionGrafo.VARIETAL_COMPOSICION in relaciones
    assert RelacionGrafo.PRODUCIDO_POR in relaciones
    assert canonical_entity("catena", EntidadGrafo.BODEGA) == "Catena Zapata"


def test_ppr_lambda_y_max_iter():
    calc = BoundedPPRCalculator()
    assert calc.alpha == PPR_LAMBDA == 0.5
    assert calc.max_iter == PPR_MAX_ITER == 10


@pytest.mark.asyncio
async def test_ingest_y_query_mapea_a_ragresult():
    engine = build_engine()
    frag = _frag(
        "pas-achaval",
        "achaval-malbec-2020",
        "Achaval Ferrer Malbec de Valle de Uco. Marida con asado de tira.",
        CapaConocimiento.TERRUNO,
        region="Valle de Uco",
        maridaje="asado",
    )
    triples = extract_wine_triples(frag)
    accepted = await ingest_fragment(frag, triples, engine=engine)
    assert accepted >= 1

    hits = await query_memgraph_rag(
        "Malbec de Valle de Uco para asado",
        top_k=5,
        engine=engine,
    )
    assert hits
    assert all(isinstance(h, RAGResult) for h in hits)
    assert hits[0].vino_id == "achaval-malbec-2020"
    assert hits[0].triples
    assert any("ORIGEN_TERRUNO" in t or "MARIDA_CON" in t for t in hits[0].triples)
    assert hits[0].modo_retrieval in {"hybrid_rerank", "memory_guided_ppr", "vector_fallback"}
    assert "Valle de Uco" in hits[0].contenido or "asado" in hits[0].contenido.lower()


@pytest.mark.asyncio
async def test_multihop_mismo_terruno_y_enologo():
    engine = build_engine()
    a = _frag(
        "pas-a",
        "achaval-malbec-2020",
        "Achaval Ferrer Malbec. Enólogo Roberto Cipresso. Terruño Valle de Uco.",
        CapaConocimiento.TERRUNO,
        enologo="Roberto Cipresso",
        region="Valle de Uco",
    )
    b = _frag(
        "pas-b",
        "zuccardi-aluvional-2019",
        "Zuccardi Aluvional. Enólogo Roberto Cipresso. Terruño Valle de Uco.",
        CapaConocimiento.TERRUNO,
        enologo="Roberto Cipresso",
        region="Valle de Uco",
    )
    await ingest_fragment(a, extract_wine_triples(a), engine=engine)
    await ingest_fragment(b, extract_wine_triples(b), engine=engine)

    hits = await query_memgraph_rag(
        "vinos de Valle de Uco del enólogo Roberto Cipresso",
        capa=CapaConocimiento.TERRUNO,
        perfil_cliente=PerfilClienteTipo.COLECCIONISTA,
        top_k=5,
        engine=engine,
    )
    ids = {h.vino_id for h in hits}
    assert "achaval-malbec-2020" in ids
    assert "zuccardi-aluvional-2019" in ids
    assert all(h.capa == CapaConocimiento.TERRUNO for h in hits)


@pytest.mark.asyncio
async def test_fallback_denso_si_grafo_vacio():
    engine = build_engine()
    vacio = await query_memgraph_rag("malbec asado", engine=engine)
    assert vacio == []

    row = {
        "producto_id": "achaval-malbec-2020",
        "nombre_vino": "Achaval Ferrer Malbec",
        "capa": 2,
        "contenido": "Suelos aluviales.",
        "score": 0.77,
    }
    with (
        patch("core.rag.retriever.query_memgraph_rag", new_callable=AsyncMock, return_value=[]),
        patch(
            "core.rag.retriever.generar_embedding",
            new_callable=AsyncMock,
            return_value=[0.1] * 8,
        ),
        patch("core.rag.retriever.fetch_all", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_fetch.return_value = [row]
        results = await search_catalog_rag("terroir uco", capa=CapaConocimiento.TERRUNO)

    assert len(results) == 1
    assert results[0].modo_retrieval == "vector_fallback"
    assert "<=>" in mock_fetch.await_args.args[0]


@pytest.mark.asyncio
async def test_indexer_ingesta_grafo_sin_sql():
    engine = build_engine()
    frag = _frag(
        "pas-idx",
        "rutini-malbec-2018",
        "Bodega Rutini. Ideal para un regalo de aniversario. Malbec de Mendoza.",
        CapaConocimiento.TENDENCIA,
        ocasion="regalo de aniversario",
    )
    stats = await index_knowledge_fragment(frag, engine=engine, persistir_sql=False)
    assert stats.sql_indexados == 0
    assert stats.triples_extraidos >= 1
    assert stats.facts_aceptados >= 1
    assert any(t.relation == RelacionGrafo.IDEAL_PARA for t in stats.triples)

    hits = await query_memgraph_rag(
        "regalo de aniversario malbec",
        perfil_cliente=PerfilClienteTipo.OCASION,
        engine=engine,
    )
    assert hits
    assert hits[0].vino_id == "rutini-malbec-2018"
