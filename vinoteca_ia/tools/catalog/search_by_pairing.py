"""
Tool RAG para buscar vinos por maridaje con comida.

Invocar cuando el cliente menciona un plato específico o tipo de comida
y el Sumiller necesita encontrar vinos que lo acompañen bien.
"""

from __future__ import annotations

from agno.tools import tool

from core.rag.retriever import buscar_similar
from schemas.tool_responses import RAGResult


@tool
async def buscar_por_maridaje(comida: str) -> list[RAGResult]:
    """
    Recupera fragmentos de conocimiento de vinos que maridan con la comida indicada.

    Usar cuando el cliente menciona:
    - Un plato específico ("cordero asado", "salmón a la plancha")
    - Un tipo de cocina ("parrilla", "mariscos", "pasta")
    - Una ocasión de comida ("asado del domingo", "cena de negocios")

    Prioriza capas 1 (maridajes documentados) y 5 (voz del sumiller)
    donde el sumiller humano ya evaluó el maridaje personalmente.
    """
    query = f"maridaje con {comida}"
    return await buscar_similar(query, capas=[1, 5, 3], top_k=5)
