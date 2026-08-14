"""Búsqueda de vinos por ocasión vía MemGraphRAG (grafo IDEAL_PARA)."""

from __future__ import annotations

from agno.tools import tool

from core.rag.memgraph_adapter import query_memgraph_rag
from core.rag.retriever import buscar_similar
from schemas.customer_profile import PerfilClienteTipo
from schemas.knowledge_fragment import CapaConocimiento
from schemas.tool_responses import OccasionResponse, ResultadoTool


@tool
async def buscar_por_ocasion(
    descripcion_ocasion: str,
    limite: int = 5,
) -> OccasionResponse:
    """Buscar vinos para una ocasión (regalo, cena, asado) vía grafo MemGraphRAG.

    Usá esta tool cuando el contexto es social/emocional. Si menciona comida,
    preferí `buscar_por_maridaje`. SIEMPRE verificá stock y precio en SQL.

    Args:
        descripcion_ocasion: Texto libre de la ocasión.
        limite: Máximo de fragmentos (1-10).
    """
    limite = max(1, min(limite, 10))
    if not descripcion_ocasion.strip():
        return OccasionResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La descripción de la ocasión no puede estar vacía.",
        )
    fragmentos = await query_memgraph_rag(
        descripcion_ocasion.strip(),
        perfil_cliente=PerfilClienteTipo.OCASION,
        top_k=limite,
    )
    if not fragmentos:
        fragmentos = await buscar_similar(
            descripcion_ocasion.strip(),
            capas=[
                CapaConocimiento.HISTORIA,
                CapaConocimiento.TENDENCIA,
                CapaConocimiento.VOZ_PROPIA,
            ],
            top_k=limite,
        )
    if not fragmentos:
        return OccasionResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            mensaje="No se encontró ningún vino para esa ocasión.",
        )
    return OccasionResponse(resultado=ResultadoTool.OK, fragmentos=fragmentos)
