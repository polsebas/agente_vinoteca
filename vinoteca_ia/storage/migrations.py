"""Migraciones idempotentes ejecutadas en el lifespan de la app.

Centralizamos acá los DDL que no maneja Agno (sesiones/memorias las gestiona
`PostgresDb`). Cada función `ensure_*` es segura para correr en cada boot.
"""

from __future__ import annotations

from storage.postgres import get_pool

_TARGET_EMBEDDING_DIM = 768


async def ensure_stock_reservas_table() -> None:
    """Tabla de reservas temporales de stock con TTL.

    Flujo de uso:
    - `verificar_stock_exacto` crea filas en estado `activa` con `expira_en = NOW + TTL`.
    - `crear_orden` las marca `consumida` y decrementa stock en la misma transacción.
    - Las expiradas se consideran inexistentes para el cálculo de disponibilidad:
      no requieren job de limpieza, pero podés incluir uno si querés purgar filas
      viejas (no es obligatorio para correctitud).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_reservas (
                reserva_id   UUID PRIMARY KEY,
                vino_id      UUID NOT NULL,
                cantidad     INT  NOT NULL CHECK (cantidad > 0),
                session_id   TEXT NOT NULL,
                estado       TEXT NOT NULL DEFAULT 'activa',
                creada_en    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expira_en    TIMESTAMPTZ NOT NULL,
                consumida_en TIMESTAMPTZ
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_stock_reservas_vino_estado "
            "ON stock_reservas(vino_id, estado)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_stock_reservas_session "
            "ON stock_reservas(session_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_stock_reservas_expira "
            "ON stock_reservas(expira_en) WHERE estado = 'activa'"
        )


async def ensure_catalog_tables() -> None:
    """Tablas de catálogo: `vinos`, `stock` y `wine_knowledge`.

    El esquema está alineado con las tools del dominio:

    - `vinos.precio_ars` / `vinos.anada_actual` → [tools.catalog.consult_price]
      y [tools.orders.calculate_order] leen esas columnas directamente.
    - `stock.vino_id` (PK, una ubicación por vino) → [tools.catalog.consult_stock]
      y [tools.orders.verify_stock_exact] hacen `LEFT JOIN ON s.vino_id = v.id`.
    - `wine_knowledge` con pgvector → indexado por [core.rag.retriever].

    La columna `imagen_slug` (UNIQUE) es la clave de idempotencia usada por
    la ingesta masiva desde `product_details.txt`.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vinos (
                id             UUID PRIMARY KEY,
                imagen_slug    TEXT UNIQUE,
                nombre         TEXT NOT NULL,
                bodega         TEXT NOT NULL,
                varietal       TEXT NOT NULL DEFAULT 'otro',
                region         TEXT,
                precio_ars     NUMERIC(12,2) NOT NULL CHECK (precio_ars > 0),
                anada_actual   INT,
                descripcion    TEXT,
                activo         BOOLEAN NOT NULL DEFAULT TRUE,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        # Idempotencia para deploys sobre tablas pre-existentes.
        await conn.execute(
            "ALTER TABLE vinos ADD COLUMN IF NOT EXISTS imagen_slug TEXT"
        )
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_vinos_imagen_slug "
            "ON vinos(imagen_slug) WHERE imagen_slug IS NOT NULL"
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock (
                vino_id    UUID PRIMARY KEY REFERENCES vinos(id) ON DELETE CASCADE,
                cantidad   INT  NOT NULL CHECK (cantidad >= 0),
                ubicacion  TEXT NOT NULL DEFAULT 'deposito_principal',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wine_knowledge (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                vino_id     UUID NOT NULL REFERENCES vinos(id) ON DELETE CASCADE,
                capa        INT  NOT NULL CHECK (capa BETWEEN 1 AND 5),
                contenido   TEXT NOT NULL,
                fuente      TEXT NOT NULL DEFAULT 'manual',
                embedding   VECTOR(768),
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (vino_id, capa, fuente)
            )
            """
        )
        dim_row = await conn.fetchrow(
            """
            SELECT CASE
                     WHEN a.atttypmod > 0 THEN a.atttypmod - 4
                     ELSE NULL
                   END AS dim
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname = 'wine_knowledge'
              AND a.attname = 'embedding'
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        )
        current_dim = dim_row["dim"] if dim_row else None
        if current_dim != _TARGET_EMBEDDING_DIM:
            await conn.execute(
                f"""
                ALTER TABLE wine_knowledge
                ALTER COLUMN embedding
                TYPE VECTOR({_TARGET_EMBEDDING_DIM})
                USING NULL::vector({_TARGET_EMBEDDING_DIM})
                """
            )
            await conn.execute(
                "UPDATE wine_knowledge SET embedding = NULL WHERE embedding IS NOT NULL"
            )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wine_knowledge_vino "
            "ON wine_knowledge(vino_id)"
        )


async def ensure_all_migrations() -> None:
    """Ejecuta todas las migraciones en el orden correcto."""
    await ensure_catalog_tables()
    await ensure_stock_reservas_table()
