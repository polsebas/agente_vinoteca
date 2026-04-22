"""Búsqueda semántica de vinos por ocasión (RAG)."""

from __future__ import annotations

from agno.tools import tool

from schemas.tool_responses import (
    OccasionResponse,
    ResultadoTool,
    VinoRecomendado,
)
from schemas.wine_catalog import WineProduct
from storage.postgres import fetch_all


@tool
async def buscar_por_ocasion(
    descripcion_ocasion: str,
    limite: int = 5,
) -> OccasionResponse:
    """Buscar vinos apropiados para una ocasión o contexto de consumo.

    Usá esta tool cuando:
    - El cliente pide un vino "para regalar a un jefe".
    - Necesita algo "para una cena romántica".
    - Quiere "un vino para compartir con amigos el finde".

    Esta tool NO reemplaza `buscar_por_maridaje`. Si el contexto menciona
    comida, usá `buscar_por_maridaje`. Si menciona contexto social/emocional,
    usá esta. SIEMPRE verificá stock y precio después con las tools dedicadas.

    Args:
        descripcion_ocasion: Texto libre de la ocasión.
        limite: Máximo de recomendaciones (1-10).

    Returns:
        OccasionResponse con vinos ordenados por relevancia semántica.
    """
    limite = max(1, min(limite, 10))
    if not descripcion_ocasion.strip():
        return OccasionResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La descripción de la ocasión no puede estar vacía.",
        )

    rows = await fetch_all(
        """
        SELECT v.id, v.nombre, v.bodega, v.varietal, v.region,
               v.precio_ars, v.anada_actual, v.descripcion,
               1 - (ve.embedding <=> (
                   SELECT embedding FROM embeddings_query
                   WHERE texto = $1 LIMIT 1
               )) AS score
        FROM vinos v
        JOIN vinos_ocasiones_embeddings ve ON ve.vino_id = v.id
        WHERE v.activo = TRUE
        ORDER BY score DESC
        LIMIT $2
        """,
        descripcion_ocasion,
        limite,
    )

    if not rows:
        return OccasionResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            mensaje="No se encontró ningún vino para esa ocasión.",
        )

    recomendaciones = [
        VinoRecomendado(
            vino=WineProduct(
                vino_id=row["id"],
                nombre=row["nombre"],
                bodega=row["bodega"],
                varietal=row["varietal"],
                region=row["region"],
                precio_ars=row["precio_ars"],
                anada_actual=row["anada_actual"],
                descripcion=row["descripcion"],
            ),
            score_relevancia=float(row["score"] or 0.0),
            razon=f"Relevante para: {descripcion_ocasion}",
        )
        for row in rows
    ]
    return OccasionResponse(
        resultado=ResultadoTool.OK,
        recomendaciones=recomendaciones,
    )
