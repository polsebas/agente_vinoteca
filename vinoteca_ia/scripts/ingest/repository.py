"""Persistencia idempotente de filas del catálogo en Postgres.

Separado del script CLI para poder testearse contra una DB real sin CLI
y para mantener una única fuente de verdad del SQL de ingesta.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg

from scripts.ingest.models import FilaCatalogo
from scripts.ingest.normalizers import anada_o_fallback, construir_fragmento_capa1


async def upsert_fila(
    conn: asyncpg.Connection,
    fila: FilaCatalogo,
    *,
    stock_default: int,
    incluir_knowledge: bool,
) -> tuple[UUID, bool, bool]:
    """Inserta o actualiza un vino + stock inicial.

    Retorna `(vino_id, insertado, knowledge_escrito)`. La idempotencia se da
    sobre `imagen_slug`: si ya existe, actualiza campos mutables (precio,
    descripción, añada) y preserva `id`/`created_at`.

    Todo el bloque corre en una transacción propia para que un fallo intermedio
    no deje `vinos` / `stock` / `wine_knowledge` inconsistentes, y para que el
    caller pueda seguir procesando otras filas sin transacción Postgres abortada.
    """
    async with conn.transaction():
        vino_id_nuevo = uuid4()
        row = await conn.fetchrow(
            """
            INSERT INTO vinos (
                id, imagen_slug, nombre, bodega, varietal, region,
                precio_ars, anada_actual, descripcion
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (imagen_slug) DO UPDATE SET
                nombre       = EXCLUDED.nombre,
                bodega       = EXCLUDED.bodega,
                varietal     = EXCLUDED.varietal,
                region       = EXCLUDED.region,
                precio_ars   = EXCLUDED.precio_ars,
                anada_actual = EXCLUDED.anada_actual,
                descripcion  = EXCLUDED.descripcion,
                updated_at   = NOW()
            RETURNING id, (xmax = 0) AS insertado
            """,
            vino_id_nuevo,
            fila.imagen_slug,
            fila.nombre,
            fila.bodega,
            fila.varietal,
            fila.region or None,
            fila.precio_ars,
            anada_o_fallback(fila.anada_actual),
            fila.descripcion,
        )
        vino_id: UUID = row["id"]
        insertado: bool = bool(row["insertado"])

        if insertado:
            await conn.execute(
                """
                INSERT INTO stock (vino_id, cantidad)
                VALUES ($1, $2)
                ON CONFLICT (vino_id) DO NOTHING
                """,
                vino_id,
                stock_default,
            )

        knowledge_escrito = False
        if incluir_knowledge:
            fragmento = construir_fragmento_capa1(fila)
            if fragmento:
                await conn.execute(
                    """
                    INSERT INTO wine_knowledge (vino_id, capa, contenido, fuente)
                    VALUES ($1, 1, $2, 'import_product_details')
                    ON CONFLICT (vino_id, capa, fuente) DO UPDATE SET
                        contenido = EXCLUDED.contenido,
                        embedding = NULL
                    """,
                    vino_id,
                    fragmento,
                )
                knowledge_escrito = True

        return vino_id, insertado, knowledge_escrito
