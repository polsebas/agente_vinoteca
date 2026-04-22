"""
Genera embeddings para todos los fragmentos de wine_knowledge que aún no los tienen.
Ejecutar después del seed o de importar datos nuevos.

Uso: python scripts/enrich_catalog.py
"""

from __future__ import annotations

import asyncio

from dotenv import load_dotenv

load_dotenv()


async def indexar_pendientes() -> None:
    from core.rag.embedder import generar_embeddings_batch
    from storage.postgres import execute, fetch_all

    rows = await fetch_all(
        """
        SELECT id, vino_id, capa, contenido
        FROM wine_knowledge
        WHERE embedding IS NULL
        ORDER BY created_at
        """
    )

    if not rows:
        print("No hay fragmentos sin embedding.")
        return

    print(f"Generando embeddings para {len(rows)} fragmentos...")

    batch_size = 50
    indexados = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        textos = [r["contenido"] for r in batch]
        embeddings = await generar_embeddings_batch(textos)

        for row, embedding in zip(batch, embeddings):
            embedding_str = f"[{','.join(str(x) for x in embedding)}]"
            await execute(
                "UPDATE wine_knowledge SET embedding = $1::vector WHERE id = $2",
                embedding_str,
                row["id"],
            )
            indexados += 1

        print(f"  {indexados}/{len(rows)} fragmentos indexados...")

    print(f"Indexación completa: {indexados} fragmentos.")


if __name__ == "__main__":
    asyncio.run(indexar_pendientes())
