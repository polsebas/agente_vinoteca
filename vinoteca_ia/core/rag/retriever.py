"""
Recuperación semántica del catálogo de conocimiento (RAG).
Solo para texto cualitativo: notas de cata, historia, terruño, tendencias.
Prohibido usarlo para precio o stock.
"""

from __future__ import annotations

from core.rag.embedder import generar_embedding
from schemas.tool_responses import RAGResult
from storage.postgres import fetch_all


async def buscar_similar(
    query: str,
    capas: list[int] | None = None,
    top_k: int = 5,
) -> list[RAGResult]:
    """
    Busca fragmentos de conocimiento por similitud semántica.

    Parámetros:
        query: Texto de búsqueda (ocasión, maridaje, perfil, etc.)
        capas: Filtro de capas (1=dato duro, 2=terruño, 3=historia, 4=tendencia, 5=voz propia)
        top_k: Número máximo de resultados a retornar.

    Nunca usar este retriever para obtener precios o stock.
    """
    embedding = await generar_embedding(query)
    embedding_str = f"[{','.join(str(x) for x in embedding)}]"

    capa_filter = ""
    args: list = [embedding_str, top_k]

    if capas:
        placeholders = ", ".join(f"${i+3}" for i in range(len(capas)))
        capa_filter = f"AND wk.capa IN ({placeholders})"
        args.extend(capas)

    rows = await fetch_all(
        f"""
        SELECT
            wk.vino_id,
            v.nombre AS nombre_vino,
            wk.capa,
            wk.contenido,
            1 - (wk.embedding <=> $1::vector) AS score
        FROM wine_knowledge wk
        JOIN vinos v ON v.id = wk.vino_id
        WHERE wk.embedding IS NOT NULL
          AND v.activo = true
          {capa_filter}
        ORDER BY wk.embedding <=> $1::vector
        LIMIT $2
        """,
        *args,
    )

    return [
        RAGResult(
            vino_id=row["vino_id"],
            nombre_vino=row["nombre_vino"],
            capa=row["capa"],
            contenido=row["contenido"],
            score=float(row["score"]),
        )
        for row in rows
    ]
