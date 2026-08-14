"""
Escritura en el vector store (tabla wine_knowledge con pgvector).
Solo para conocimiento cualitativo: notas de cata, historia, terruño.
NUNCA indexar precios ni stock.
"""

from __future__ import annotations

from uuid import uuid4

from core.rag.embedder import generar_embeddings_batch
from storage.postgres import execute, fetch_all


async def indexar_fragmentos(
    fragmentos: list[dict],
) -> int:
    """
    Indexa fragmentos de conocimiento en wine_knowledge.

    Parámetros:
        fragmentos: Lista de {producto_id|vino_id, capa, contenido, fuente}

    Retorna el número de fragmentos indexados.
    """
    if not fragmentos:
        return 0

    textos = [f["contenido"] for f in fragmentos]
    embeddings = await generar_embeddings_batch(textos)

    count = 0
    for fragmento, embedding in zip(fragmentos, embeddings, strict=True):
        producto_id = str(fragmento.get("producto_id") or fragmento.get("vino_id") or "")
        if not producto_id:
            continue
        frag_id = str(fragmento.get("id") or uuid4())
        await execute(
            """
            INSERT INTO wine_knowledge (
                id, producto_id, capa, contenido, fuente, embedding, validador_humano
            )
            VALUES ($1, $2, $3, $4, $5, $6::vector, $7)
            ON CONFLICT (producto_id, capa, fuente) DO UPDATE SET
                contenido = EXCLUDED.contenido,
                embedding = EXCLUDED.embedding,
                validador_humano = EXCLUDED.validador_humano
            """,
            frag_id,
            producto_id,
            int(fragmento["capa"]),
            fragmento["contenido"],
            fragmento.get("fuente", "manual"),
            f"[{','.join(str(x) for x in embedding)}]",
            bool(fragmento.get("validador_humano", False)),
        )
        count += 1

    return count


async def listar_sin_embedding() -> list[dict]:
    """Retorna fragmentos que aún no tienen embedding generado."""
    rows = await fetch_all(
        """
        SELECT id, producto_id, capa, contenido, fuente
        FROM wine_knowledge
        WHERE embedding IS NULL
        ORDER BY created_at
        LIMIT 100
        """
    )
    return [
        {
            "id": r["id"],
            "producto_id": r["producto_id"],
            "vino_id": r["producto_id"],
            "capa": r["capa"],
            "contenido": r["contenido"],
            "fuente": r["fuente"],
        }
        for r in rows
    ]
