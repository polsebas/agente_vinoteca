"""
Escritura en el vector store (tabla wine_knowledge con pgvector).
Solo para conocimiento cualitativo: notas de cata, historia, terruño.
NUNCA indexar precios ni stock.
"""

from __future__ import annotations

from uuid import UUID

from core.rag.embedder import generar_embeddings_batch
from storage.postgres import execute, fetch_all


async def indexar_fragmentos(
    fragmentos: list[dict],
) -> int:
    """
    Indexa fragmentos de conocimiento en wine_knowledge.

    Parámetros:
        fragmentos: Lista de {vino_id, capa, contenido, fuente}

    Retorna el número de fragmentos indexados.
    """
    if not fragmentos:
        return 0

    textos = [f["contenido"] for f in fragmentos]
    embeddings = await generar_embeddings_batch(textos)

    count = 0
    for fragmento, embedding in zip(fragmentos, embeddings):
        await execute(
            """
            INSERT INTO wine_knowledge (vino_id, capa, contenido, fuente, embedding)
            VALUES ($1, $2, $3, $4, $5::vector)
            ON CONFLICT DO NOTHING
            """,
            UUID(str(fragmento["vino_id"])),
            int(fragmento["capa"]),
            fragmento["contenido"],
            fragmento.get("fuente", "manual"),
            f"[{','.join(str(x) for x in embedding)}]",
        )
        count += 1

    return count


async def listar_sin_embedding() -> list[dict]:
    """Retorna fragmentos que aún no tienen embedding generado."""
    rows = await fetch_all(
        """
        SELECT id, vino_id, capa, contenido, fuente
        FROM wine_knowledge
        WHERE embedding IS NULL
        ORDER BY created_at
        LIMIT 100
        """
    )
    return [dict(r) for r in rows]
