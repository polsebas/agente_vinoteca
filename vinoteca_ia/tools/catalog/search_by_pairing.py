"""Búsqueda de vinos por maridaje vía MemGraphRAG (grafo MARIDA_CON)."""

from __future__ import annotations

from agno.tools import tool

from core.rag.memgraph_adapter import query_memgraph_rag
from core.rag.retriever import buscar_similar
from schemas.customer_profile import PerfilClienteTipo
from schemas.knowledge_fragment import CapaConocimiento
from schemas.tool_responses import PairingResponse, ResultadoTool


async def _buscar_fragmentos(query: str, limite: int) -> list:
    hits = await query_memgraph_rag(
        query,
        perfil_cliente=PerfilClienteTipo.OCASION,
        top_k=limite,
    )
    if hits:
        return hits
    return await buscar_similar(
        query,
        capas=[
            CapaConocimiento.DATO_DURO,
            CapaConocimiento.TERRUNO,
            CapaConocimiento.HISTORIA,
            CapaConocimiento.VOZ_PROPIA,
        ],
        top_k=limite,
    )


@tool
async def buscar_por_maridaje(
    descripcion_comida: str,
    limite: int = 5,
) -> PairingResponse:
    """Buscar vinos que maridan con una comida vía grafo MemGraphRAG.

    Usá esta tool cuando el cliente describe un plato. SIEMPRE verificá
    después stock y precio con las tools SQL: el RAG no es fuente de precios.

    Args:
        descripcion_comida: Texto libre del maridaje (asado, ceviche, …).
        limite: Máximo de fragmentos (1-10).
    """
    limite = max(1, min(limite, 10))
    if not descripcion_comida.strip():
        return PairingResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La descripción de la comida no puede estar vacía.",
        )
    fragmentos = await _buscar_fragmentos(descripcion_comida.strip(), limite)
    if not fragmentos:
        return PairingResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            mensaje="No se encontró ningún vino para ese maridaje.",
        )
    return PairingResponse(resultado=ResultadoTool.OK, fragmentos=fragmentos)
