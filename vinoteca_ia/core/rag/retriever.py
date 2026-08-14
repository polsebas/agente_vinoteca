"""
Recuperación semántica del catálogo de conocimiento (RAG).
Solo para texto cualitativo: notas de cata, historia, terruño, tendencias.
Prohibido usarlo para precio o stock.

Ruta primaria: MemGraphRAG (PPR + triples). Fallback: cosine `<=>` en pgvector.
"""

from __future__ import annotations

from core.rag.embedder import generar_embedding
from core.rag.memgraph_adapter import query_memgraph_rag
from schemas.customer_profile import PerfilClienteTipo
from schemas.knowledge_fragment import CapaConocimiento
from schemas.tool_responses import RAGResult
from storage.postgres import fetch_all

SCORE_THRESHOLD = 0.30


def _embedding_literal(embedding: list[float]) -> str:
    return f"[{','.join(str(x) for x in embedding)}]"


def _rows_to_results(rows) -> list[RAGResult]:
    return [
        RAGResult(
            vino_id=str(row["producto_id"]),
            nombre_vino=row["nombre_vino"],
            capa=row["capa"],
            contenido=row["contenido"],
            score=float(row["score"]),
            modo_retrieval="vector_fallback",
        )
        for row in rows
    ]


async def _query_wine_knowledge(
    query: str,
    *,
    capas: list[int] | None,
    top_k: int,
    score_threshold: float = SCORE_THRESHOLD,
) -> list[RAGResult]:
    embedding = await generar_embedding(query)
    embedding_str = _embedding_literal(embedding)
    args: list = [embedding_str, top_k, score_threshold]
    capa_filter = ""
    if capas:
        placeholders = ", ".join(f"${i + 4}" for i in range(len(capas)))
        capa_filter = f"AND wk.capa IN ({placeholders})"
        args.extend(capas)

    rows = await fetch_all(
        f"""
        SELECT
            wk.producto_id::text AS producto_id,
            COALESCE(v.nombre, wk.producto_id::text) AS nombre_vino,
            wk.capa,
            wk.contenido,
            1 - (wk.embedding <=> $1::vector) AS score
        FROM wine_knowledge wk
        JOIN vinos v ON v.id = wk.producto_id
        WHERE wk.embedding IS NOT NULL
          AND v.activo = true
          AND (
                wk.validador_humano = TRUE
                OR (1 - (wk.embedding <=> $1::vector)) >= $3
              )
          {capa_filter}
        ORDER BY wk.embedding <=> $1::vector
        LIMIT $2
        """,
        *args,
    )
    return _rows_to_results(rows)


async def search_catalog_rag(
    query: str,
    capa: CapaConocimiento | None = None,
    top_k: int = 5,
    perfil_cliente: PerfilClienteTipo | None = None,
) -> list[RAGResult]:
    """Busca fragmentos cualitativos vía MemGraphRAG, con fallback denso.

    Nunca usar para precio/stock.
    """
    graph_hits = await query_memgraph_rag(
        query, capa=capa, perfil_cliente=perfil_cliente, top_k=top_k
    )
    if graph_hits:
        return graph_hits
    capas = [int(capa)] if capa is not None else None
    return await _query_wine_knowledge(query, capas=capas, top_k=top_k)


async def buscar_similar(
    query: str,
    capas: list[CapaConocimiento | int] | None = None,
    top_k: int = 5,
    perfil_cliente: PerfilClienteTipo | None = None,
) -> list[RAGResult]:
    """Compatibilidad: lista de capas (tools de maridaje/ocasión)."""
    capa_unica = None
    if capas and len(capas) == 1:
        capa_unica = CapaConocimiento(int(capas[0]))
    graph_hits = await query_memgraph_rag(
        query, capa=capa_unica, perfil_cliente=perfil_cliente, top_k=top_k
    )
    if graph_hits:
        if capas:
            permitidas = {int(c) for c in capas}
            filtrados = [h for h in graph_hits if int(h.capa) in permitidas]
            if filtrados:
                return filtrados
        return graph_hits
    capa_ints = [int(c) for c in capas] if capas else None
    return await _query_wine_knowledge(query, capas=capa_ints, top_k=top_k)
