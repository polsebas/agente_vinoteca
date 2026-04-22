"""Búsqueda semántica de vinos por maridaje (RAG)."""

from __future__ import annotations

from agno.tools import tool

from schemas.tool_responses import (
    PairingResponse,
    ResultadoTool,
    VinoRecomendado,
)
from schemas.wine_catalog import WineProduct
from storage.postgres import fetch_all


@tool
async def buscar_por_maridaje(
    descripcion_comida: str,
    limite: int = 5,
) -> PairingResponse:
    """Buscar vinos que maridan con una comida o preparación específica.

    Usá esta tool cuando:
    - El cliente describe un plato y pide sugerencias.
    - Querés ofrecer una alternativa en función de lo que va a comer.

    SIEMPRE llamá después a `consultar_stock` y `consultar_precio` con los
    vino_ids que devuelva esta tool antes de confirmarlos al cliente. El RAG
    devuelve lo que *podría* encajar; el SQL dice lo que *tenés* disponible.

    Args:
        descripcion_comida: Texto libre del maridaje buscado (ej. "asado
            argentino", "ceviche", "risotto de hongos").
        limite: Cantidad máxima de recomendaciones (1-10).

    Returns:
        PairingResponse con lista de `VinoRecomendado` ordenada por relevancia
        semántica.
    """
    limite = max(1, min(limite, 10))
    if not descripcion_comida.strip():
        return PairingResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La descripción de la comida no puede estar vacía.",
        )

    rows = await fetch_all(
        """
        SELECT v.id, v.nombre, v.bodega, v.varietal, v.region,
               v.precio_ars, v.anada_actual, v.descripcion,
               1 - (vm.embedding <=> (
                   SELECT embedding FROM embeddings_query
                   WHERE texto = $1 LIMIT 1
               )) AS score
        FROM vinos v
        JOIN vinos_maridajes_embeddings vm ON vm.vino_id = v.id
        WHERE v.activo = TRUE
        ORDER BY score DESC
        LIMIT $2
        """,
        descripcion_comida,
        limite,
    )

    if not rows:
        return PairingResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            mensaje="No se encontró ningún vino para ese maridaje.",
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
            razon=f"Maridaje semántico para: {descripcion_comida}",
        )
        for row in rows
    ]
    return PairingResponse(
        resultado=ResultadoTool.OK,
        recomendaciones=recomendaciones,
    )
