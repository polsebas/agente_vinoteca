"""Indexa `KnowledgeFragment` en pgvector y en el grafo MemGraphRAG.

El SQL transaccional (precio/stock) no pasa por acá. Este pipeline extrae
triples del dominio vino, resuelve alias de bodega/región y los escribe en
M_ont / M_fac / M_pas.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.rag.memgraph_adapter import MemGraphEngine, ingest_fragment
from core.rag.vector_store import indexar_fragmentos
from core.rag.wine_graph_schema import WineTriple, extract_wine_triples
from schemas.knowledge_fragment import KnowledgeFragment


class IndexingStats(BaseModel):
    """Resumen de una ingesta de fragmento."""

    model_config = ConfigDict(extra="forbid")

    fragment_id: str
    sql_indexados: int = 0
    triples_extraidos: int = 0
    facts_aceptados: int = 0
    triples: list[WineTriple] = Field(default_factory=list)


async def index_knowledge_fragment(
    fragment: KnowledgeFragment,
    *,
    engine: MemGraphEngine | None = None,
    persistir_sql: bool = True,
) -> IndexingStats:
    """Extrae triples, resuelve entidades y escribe SQL + grafo.

    Invocar cuando un fragmento cualitativo queda validado (humano o umbral).
    """
    sql_count = 0
    if persistir_sql:
        sql_count = await indexar_fragmentos(
            [
                {
                    "id": fragment.id,
                    "producto_id": fragment.producto_id,
                    "capa": int(fragment.capa),
                    "contenido": fragment.contenido,
                    "fuente": fragment.fuente.value,
                    "validador_humano": fragment.validador_humano,
                }
            ]
        )

    triples = extract_wine_triples(fragment)
    accepted = await ingest_fragment(fragment, triples, engine=engine)
    return IndexingStats(
        fragment_id=fragment.id,
        sql_indexados=sql_count,
        triples_extraidos=len(triples),
        facts_aceptados=accepted,
        triples=triples,
    )
