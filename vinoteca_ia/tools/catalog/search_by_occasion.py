"""
Tool RAG para buscar vinos por ocasión o tipo de cliente.

Invocar cuando el Sumiller necesita recuperar conocimiento cualitativo
para formular una recomendación personalizada. NUNCA usar para precio
ni stock — esos son siempre via SQL.
"""

from __future__ import annotations

from agno.tools import tool

from core.rag.retriever import buscar_similar
from schemas.tool_responses import RAGResult


@tool
async def buscar_por_ocasion(ocasion: str, perfil_cliente: str = "desconocido") -> list[RAGResult]:
    """
    Recupera fragmentos de conocimiento relevantes para una ocasión o perfil.

    Usar cuando el Sumiller necesita contexto cualitativo para recomendar:
    - "regalo de cumpleaños para alguien que le gustan los tintos"
    - "vino para maridar con asado de cordero"
    - "algo especial para una cena romántica"

    Las capas 3 (historia) y 5 (voz propia) son más relevantes para
    perfiles Ocasion y Curioso. Las capas 2 (terruño) y 4 (tendencia)
    para el perfil Coleccionista.

    Parámetros:
        ocasion: Descripción de la ocasión o pedido del cliente.
        perfil_cliente: "coleccionista" | "curioso" | "ocasion" | "desconocido"
    """
    capas_por_perfil = {
        "coleccionista": [2, 4, 1],
        "curioso": [3, 5, 2],
        "ocasion": [5, 3, 1],
        "desconocido": None,
    }
    capas = capas_por_perfil.get(perfil_cliente.lower())
    query = f"{ocasion} {perfil_cliente}" if perfil_cliente != "desconocido" else ocasion
    return await buscar_similar(query, capas=capas, top_k=5)
