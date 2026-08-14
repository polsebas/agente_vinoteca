"""Migraciones idempotentes ejecutadas en el lifespan de la app.

DDL canónico de la Fase 2: PKs TEXT, stock con `cantidad_disponible`/`reservado`,
pedidos 2PC, eventos, clientes y log append-only. Cada `ensure_*` es seguro
en cada boot (`CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS`).
"""

from __future__ import annotations

from storage.postgres import get_pool

_TARGET_EMBEDDING_DIM = 768


async def _add_column(conn, table: str, column: str, ddl: str) -> None:
    await conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")


async def _drop_not_null(conn, table: str, column: str) -> None:
    """Relaja NOT NULL de columnas legacy que el DDL canónico ya no usa."""
    if not await _column_udt(conn, table, column):
        return
    await conn.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL")


async def _column_udt(conn, table: str, column: str) -> str | None:
    row = await conn.fetchrow(
        """
        SELECT udt_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = $1
          AND column_name = $2
        """,
        table,
        column,
    )
    return str(row["udt_name"]) if row else None


async def _table_exists(conn, table: str) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema() AND table_name = $1
        """,
        table,
    )
    return row is not None


async def _add_fk_if_missing(conn, table: str, name: str, ddl: str) -> None:
    row = await conn.fetchrow(
        """
        SELECT 1 FROM pg_constraint
        WHERE conname = $1 AND conrelid = $2::regclass
        """,
        name,
        table,
    )
    if row is None:
        await conn.execute(ddl)


async def _drop_fks_to(conn, table: str) -> None:
    rows = await conn.fetch(
        """
        SELECT con.conname AS name, rel.relname AS src
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_class tgt ON tgt.oid = con.confrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE con.contype = 'f'
          AND nsp.nspname = current_schema()
          AND tgt.relname = $1
        """,
        table,
    )
    for row in rows:
        await conn.execute(f'ALTER TABLE "{row["src"]}" DROP CONSTRAINT IF EXISTS "{row["name"]}"')


async def _align_legacy_catalog_schema(conn) -> None:
    """Convierte PKs UUID heredados a TEXT y alinea stock/knowledge a `producto_id`.

    Los volúmenes locales previos a Fase 2 tienen `vinos.id uuid` y `stock.vino_id`.
    `CREATE TABLE IF NOT EXISTS` no cambia eso; sin este paso `pedido_lineas`
    no puede crear el FK TEXT → UUID.
    """
    if not await _table_exists(conn, "vinos"):
        return

    vinos_id = await _column_udt(conn, "vinos", "id")
    if vinos_id == "uuid":
        await _drop_fks_to(conn, "vinos")
        await conn.execute("ALTER TABLE vinos ALTER COLUMN id TYPE TEXT USING id::text")

    if await _table_exists(conn, "stock"):
        await _add_column(conn, "stock", "producto_id", "TEXT")
        if await _column_udt(conn, "stock", "vino_id"):
            await conn.execute(
                """
                UPDATE stock
                SET producto_id = vino_id::text
                WHERE producto_id IS NULL AND vino_id IS NOT NULL
                """
            )
        pk = await conn.fetchrow(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = 'stock'::regclass AND i.indisprimary
            """
        )
        if pk and pk["attname"] != "producto_id":
            await conn.execute("ALTER TABLE stock DROP CONSTRAINT IF EXISTS stock_pkey")
            await conn.execute("ALTER TABLE stock ALTER COLUMN producto_id SET NOT NULL")
            await conn.execute("ALTER TABLE stock ADD PRIMARY KEY (producto_id)")
        await _add_fk_if_missing(
            conn,
            "stock",
            "stock_producto_id_fkey",
            """
            ALTER TABLE stock
            ADD CONSTRAINT stock_producto_id_fkey
            FOREIGN KEY (producto_id) REFERENCES vinos(id) ON DELETE CASCADE
            """,
        )
        if await _column_udt(conn, "stock", "cantidad"):
            await conn.execute(
                """
                UPDATE stock
                SET cantidad_disponible = cantidad
                WHERE COALESCE(cantidad_disponible, 0) = 0 AND COALESCE(cantidad, 0) > 0
                """
            )
            await conn.execute(
                """
                UPDATE stock
                SET cantidad = cantidad_disponible
                WHERE cantidad IS NULL AND cantidad_disponible IS NOT NULL
                """
            )
            await _drop_not_null(conn, "stock", "cantidad")
        # El DDL canónico usa `producto_id`; columnas legacy quedan nullable.
        await _drop_not_null(conn, "stock", "vino_id")

    if await _table_exists(conn, "wine_knowledge"):
        if await _column_udt(conn, "wine_knowledge", "id") == "uuid":
            await conn.execute("ALTER TABLE wine_knowledge ALTER COLUMN id DROP DEFAULT")
            await conn.execute(
                "ALTER TABLE wine_knowledge ALTER COLUMN id TYPE TEXT USING id::text"
            )
        await _add_column(conn, "wine_knowledge", "producto_id", "TEXT")
        if await _column_udt(conn, "wine_knowledge", "vino_id"):
            await conn.execute(
                """
                UPDATE wine_knowledge
                SET producto_id = vino_id::text
                WHERE producto_id IS NULL AND vino_id IS NOT NULL
                """
            )
            await _drop_not_null(conn, "wine_knowledge", "vino_id")
        await _add_fk_if_missing(
            conn,
            "wine_knowledge",
            "wine_knowledge_producto_id_fkey",
            """
            ALTER TABLE wine_knowledge
            ADD CONSTRAINT wine_knowledge_producto_id_fkey
            FOREIGN KEY (producto_id) REFERENCES vinos(id) ON DELETE CASCADE
            """,
        )

    tiene_precio_ars = await _column_udt(conn, "vinos", "precio_ars")
    tiene_precio = await _column_udt(conn, "vinos", "precio")
    if tiene_precio_ars and tiene_precio:
        await conn.execute(
            "UPDATE vinos SET precio = precio_ars WHERE precio IS NULL AND precio_ars IS NOT NULL"
        )
        await conn.execute(
            "UPDATE vinos SET precio_ars = precio WHERE precio_ars IS NULL AND precio IS NOT NULL"
        )
        await _drop_not_null(conn, "vinos", "precio_ars")
    tiene_anada_actual = await _column_udt(conn, "vinos", "anada_actual")
    tiene_anada = await _column_udt(conn, "vinos", "anada")
    if tiene_anada_actual and tiene_anada:
        await conn.execute(
            "UPDATE vinos SET anada = anada_actual WHERE anada IS NULL AND anada_actual IS NOT NULL"
        )


async def ensure_catalog_tables() -> None:
    """Catálogo transaccional (`vinos`, `stock`) y conocimiento vectorial."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await _align_legacy_catalog_schema(conn)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vinos (
                id          TEXT PRIMARY KEY,
                nombre      TEXT,
                bodega      TEXT,
                varietal    TEXT,
                anada       INT,
                precio      NUMERIC(12,2),
                region      TEXT,
                alcohol     NUMERIC(4,2),
                activo      BOOLEAN NOT NULL DEFAULT TRUE,
                imagen_slug TEXT UNIQUE,
                descripcion TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await _add_column(conn, "vinos", "nombre", "TEXT")
        await _add_column(conn, "vinos", "bodega", "TEXT")
        await _add_column(conn, "vinos", "varietal", "TEXT")
        await _add_column(conn, "vinos", "anada", "INT")
        await _add_column(conn, "vinos", "precio", "NUMERIC(12,2)")
        await _add_column(conn, "vinos", "region", "TEXT")
        await _add_column(conn, "vinos", "alcohol", "NUMERIC(4,2)")
        await _add_column(conn, "vinos", "activo", "BOOLEAN DEFAULT TRUE")
        await _add_column(conn, "vinos", "imagen_slug", "TEXT")
        await _add_column(conn, "vinos", "descripcion", "TEXT")
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_vinos_imagen_slug "
            "ON vinos(imagen_slug) WHERE imagen_slug IS NOT NULL"
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock (
                producto_id          TEXT PRIMARY KEY REFERENCES vinos(id) ON DELETE CASCADE,
                cantidad_disponible  INT NOT NULL DEFAULT 0 CHECK (cantidad_disponible >= 0),
                reservado            INT NOT NULL DEFAULT 0 CHECK (reservado >= 0),
                ubicacion            TEXT NOT NULL DEFAULT 'deposito_principal',
                updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await _add_column(conn, "stock", "cantidad_disponible", "INT DEFAULT 0")
        await _add_column(conn, "stock", "reservado", "INT DEFAULT 0")
        await _add_column(conn, "stock", "ubicacion", "TEXT DEFAULT 'deposito_principal'")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wine_knowledge (
                id                TEXT PRIMARY KEY,
                producto_id       TEXT NOT NULL REFERENCES vinos(id) ON DELETE CASCADE,
                capa              INT  NOT NULL CHECK (capa BETWEEN 1 AND 5),
                fuente            TEXT NOT NULL DEFAULT 'manual',
                contenido         TEXT NOT NULL,
                validador_humano  BOOLEAN NOT NULL DEFAULT FALSE,
                embedding         VECTOR(768),
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (producto_id, capa, fuente)
            )
            """
        )
        await _add_column(conn, "wine_knowledge", "producto_id", "TEXT")
        await _add_column(conn, "wine_knowledge", "fuente", "TEXT DEFAULT 'manual'")
        await _add_column(conn, "wine_knowledge", "validador_humano", "BOOLEAN DEFAULT FALSE")
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
        if current_dim is not None and current_dim != _TARGET_EMBEDDING_DIM:
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
            "CREATE INDEX IF NOT EXISTS idx_wine_knowledge_producto ON wine_knowledge(producto_id)"
        )
        await conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_wk_producto_capa_fuente
            ON wine_knowledge (producto_id, capa, fuente)
            """
        )


async def ensure_order_tables() -> None:
    """Pedidos 2PC: cabecera, líneas e idempotencia única."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pedidos (
                id               TEXT PRIMARY KEY,
                session_id       TEXT,
                cliente_id       TEXT,
                estado           TEXT NOT NULL DEFAULT 'preparada',
                total            NUMERIC(12,2),
                subtotal         NUMERIC(12,2),
                descuento        NUMERIC(12,2) NOT NULL DEFAULT 0,
                costo_envio      NUMERIC(12,2) NOT NULL DEFAULT 0,
                tipo_entrega     TEXT,
                idempotency_key  TEXT UNIQUE,
                payment_link     TEXT,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for col, ddl in (
            ("session_id", "TEXT"),
            ("cliente_id", "TEXT"),
            ("estado", "TEXT DEFAULT 'preparada'"),
            ("total", "NUMERIC(12,2)"),
            ("subtotal", "NUMERIC(12,2)"),
            ("descuento", "NUMERIC(12,2) DEFAULT 0"),
            ("costo_envio", "NUMERIC(12,2) DEFAULT 0"),
            ("tipo_entrega", "TEXT"),
            ("idempotency_key", "TEXT"),
            ("payment_link", "TEXT"),
            ("created_at", "TIMESTAMPTZ DEFAULT NOW()"),
        ):
            await _add_column(conn, "pedidos", col, ddl)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_pedidos_idempotency "
            "ON pedidos(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pedido_lineas (
                id               SERIAL PRIMARY KEY,
                pedido_id        TEXT NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
                producto_id      TEXT NOT NULL REFERENCES vinos(id),
                nombre           TEXT,
                cantidad         INT NOT NULL CHECK (cantidad > 0),
                precio_unitario  NUMERIC(12,2) NOT NULL,
                subtotal         NUMERIC(12,2) NOT NULL
            )
            """
        )
        await _add_column(conn, "pedido_lineas", "producto_id", "TEXT")
        await _add_column(conn, "pedido_lineas", "nombre", "TEXT")
        await _add_column(conn, "pedido_lineas", "cantidad", "INT")
        await _add_column(conn, "pedido_lineas", "precio_unitario", "NUMERIC(12,2)")
        await _add_column(conn, "pedido_lineas", "subtotal", "NUMERIC(12,2)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pedido_lineas_pedido ON pedido_lineas(pedido_id)"
        )


async def ensure_customer_tables() -> None:
    """Clientes y preferencias clave/valor para memoria semántica."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clientes (
                id           TEXT PRIMARY KEY,
                nombre       TEXT,
                email        TEXT,
                telefono     TEXT,
                segmento     TEXT NOT NULL DEFAULT 'general',
                perfil_tipo  TEXT NOT NULL DEFAULT 'general',
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await _add_column(conn, "clientes", "email", "TEXT")
        await _add_column(conn, "clientes", "telefono", "TEXT")
        await _add_column(conn, "clientes", "segmento", "TEXT DEFAULT 'general'")
        await _add_column(conn, "clientes", "perfil_tipo", "TEXT DEFAULT 'general'")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cliente_preferencias (
                id          SERIAL PRIMARY KEY,
                cliente_id  TEXT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
                clave       TEXT NOT NULL,
                valor       TEXT NOT NULL,
                fuente      TEXT,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (cliente_id, clave)
            )
            """
        )
        await _add_column(conn, "cliente_preferencias", "clave", "TEXT")
        await _add_column(conn, "cliente_preferencias", "valor", "TEXT")
        await _add_column(conn, "cliente_preferencias", "fuente", "TEXT")
        await _add_column(conn, "cliente_preferencias", "updated_at", "TIMESTAMPTZ DEFAULT NOW()")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cliente_prefs_cliente "
            "ON cliente_preferencias(cliente_id, updated_at DESC)"
        )


async def ensure_events_tables() -> None:
    """Catas y cupos: fuente SQL, nunca RAG."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eventos (
                id                TEXT PRIMARY KEY,
                titulo            TEXT NOT NULL,
                descripcion       TEXT,
                fecha             TIMESTAMPTZ NOT NULL,
                precio            NUMERIC(12,2) NOT NULL DEFAULT 0,
                cupo_total        INT NOT NULL CHECK (cupo_total >= 0),
                cupo_disponible   INT NOT NULL CHECK (cupo_disponible >= 0),
                activo            BOOLEAN NOT NULL DEFAULT TRUE
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eventos_reservas (
                id          TEXT PRIMARY KEY,
                evento_id   TEXT NOT NULL REFERENCES eventos(id),
                cliente_id  TEXT,
                cantidad    INT NOT NULL CHECK (cantidad > 0),
                total       NUMERIC(12,2) NOT NULL,
                estado      TEXT NOT NULL DEFAULT 'confirmada',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_eventos_fecha ON eventos(fecha) WHERE activo"
        )


async def ensure_support_tables() -> None:
    """Tickets de soporte/reclamo y FAQ administrativa."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets_soporte (
                id           TEXT PRIMARY KEY,
                session_id   TEXT,
                cliente_id   TEXT,
                categoria    TEXT,
                descripcion  TEXT NOT NULL,
                urgencia     TEXT DEFAULT 'media',
                estado       TEXT NOT NULL DEFAULT 'abierto',
                transcript   TEXT,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await _add_column(conn, "tickets_soporte", "transcript", "TEXT")
        await _add_column(conn, "tickets_soporte", "urgencia", "TEXT DEFAULT 'media'")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS faq (
                id             SERIAL PRIMARY KEY,
                pregunta       TEXT NOT NULL,
                respuesta      TEXT NOT NULL,
                fuente         TEXT NOT NULL DEFAULT 'politicas_v1',
                search_vector  tsvector
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_faq_search
            ON faq USING GIN (search_vector)
            """
        )


async def ensure_immutable_log_table() -> None:
    """Log append-only de mutaciones (2PC, pagos, reservas)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS log_inmutable (
                id               SERIAL PRIMARY KEY,
                timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                session_id       TEXT,
                accion           TEXT NOT NULL,
                payload_hash     TEXT NOT NULL,
                idempotency_key  TEXT,
                resultado        TEXT NOT NULL,
                metadata         JSONB
            )
            """
        )
        await _add_column(conn, "log_inmutable", "timestamp", "TIMESTAMPTZ DEFAULT NOW()")
        await _add_column(conn, "log_inmutable", "session_id", "TEXT")
        await _add_column(conn, "log_inmutable", "accion", "TEXT")
        await _add_column(conn, "log_inmutable", "payload_hash", "TEXT")
        await _add_column(conn, "log_inmutable", "idempotency_key", "TEXT")
        await _add_column(conn, "log_inmutable", "resultado", "TEXT")
        await _add_column(conn, "log_inmutable", "metadata", "JSONB")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_log_inmutable_session "
            "ON log_inmutable(session_id, timestamp DESC)"
        )


async def ensure_idempotency_table() -> None:
    """Fallback SQL de claves SET NX cuando Redis no está disponible."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key         TEXT PRIMARY KEY,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at  TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_keys(expires_at)"
        )


async def ensure_all_migrations() -> None:
    """Ejecuta todas las migraciones en el orden correcto (FKs)."""
    await ensure_catalog_tables()
    await ensure_customer_tables()
    await ensure_order_tables()
    await ensure_events_tables()
    await ensure_support_tables()
    await ensure_immutable_log_table()
    await ensure_idempotency_table()


if __name__ == "__main__":
    import asyncio

    from dotenv import load_dotenv

    from storage.postgres import close_pool

    load_dotenv()

    async def _main() -> None:
        await ensure_all_migrations()
        await close_pool()
        print("Migraciones OK.")

    asyncio.run(_main())
