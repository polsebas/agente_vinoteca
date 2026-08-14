"""RAG cualitativo: MemGraphRAG primero, cosine pgvector como fallback."""

from core.rag.memgraph_adapter import query_memgraph_rag
from core.rag.retriever import buscar_similar, search_catalog_rag
from core.rag.vector_store import indexar_fragmentos, listar_sin_embedding

__all__ = [
    "buscar_similar",
    "indexar_fragmentos",
    "listar_sin_embedding",
    "query_memgraph_rag",
    "search_catalog_rag",
]
