"""
Crea y migra el esquema relacional de Vinoteca IA en PostgreSQL.
Ejecutar una vez: python storage/migrations.py
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

DDL = """
-- Extensión vectorial
CREATE EXTENSION IF NOT EXISTS pgvector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Catálogo de vinos ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vinos (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre          TEXT NOT NULL,
    bodega          TEXT NOT NULL,
    varietal        TEXT NOT NULL,
    cosecha         SMALLINT,
    precio          NUMERIC(10, 2) NOT NULL CHECK (precio > 0),
    descripcion     TEXT,
    region          TEXT,
    sub_region      TEXT,
    alcohol         NUMERIC(4, 1),
    maridajes       TEXT[],
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Stock ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stock (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vino_id         UUID NOT NULL REFERENCES vinos(id) ON DELETE CASCADE,
    cantidad        INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
    ubicacion       TEXT DEFAULT 'deposito_principal',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(vino_id, ubicacion)
);

-- ── Perfiles de cliente ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS perfiles_cliente (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canal           TEXT NOT NULL,
    canal_user_id   TEXT NOT NULL,
    tipo_perfil     TEXT CHECK (tipo_perfil IN ('coleccionista', 'curioso', 'ocasion', 'desconocido'))
                    DEFAULT 'desconocido',
    preferencias    JSONB DEFAULT '{}',
    historial_ids   UUID[] DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(canal, canal_user_id)
);

-- ── Pedidos ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pedidos (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id      TEXT NOT NULL,
    cliente_id      UUID REFERENCES perfiles_cliente(id),
    estado          TEXT NOT NULL
                    CHECK (estado IN ('preparando', 'pendiente_aprobacion', 'confirmado', 'cancelado', 'fallido'))
                    DEFAULT 'preparando',
    tipo_entrega    TEXT CHECK (tipo_entrega IN ('retiro', 'envio')) DEFAULT 'retiro',
    direccion       TEXT,
    subtotal        NUMERIC(10, 2),
    total           NUMERIC(10, 2),
    idempotency_key TEXT UNIQUE NOT NULL,
    notas           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Líneas de pedido ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lineas_pedido (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pedido_id       UUID NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
    vino_id         UUID NOT NULL REFERENCES vinos(id),
    cantidad        INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario NUMERIC(10, 2) NOT NULL CHECK (precio_unitario > 0),
    subtotal        NUMERIC(10, 2) GENERATED ALWAYS AS (cantidad * precio_unitario) STORED
);

-- ── Sesiones de agente (PgAgentStorage) ─────────────────────────────
CREATE TABLE IF NOT EXISTS sesiones_agente (
    id              TEXT PRIMARY KEY,
    correlation_id  TEXT NOT NULL,
    canal           TEXT NOT NULL DEFAULT 'web',
    agente_nombre   TEXT,
    historial_json  JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Log inmutable de transacciones ──────────────────────────────────
CREATE TABLE IF NOT EXISTS log_inmutable (
    id              BIGSERIAL PRIMARY KEY,
    pedido_id       UUID REFERENCES pedidos(id),
    session_id      TEXT,
    correlation_id  TEXT,
    evento          TEXT NOT NULL,
    payload         JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Conocimiento vectorial (RAG) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS wine_knowledge (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vino_id         UUID NOT NULL REFERENCES vinos(id) ON DELETE CASCADE,
    capa            SMALLINT NOT NULL CHECK (capa BETWEEN 1 AND 5),
    contenido       TEXT NOT NULL,
    fuente          TEXT DEFAULT 'manual',
    embedding       vector(1536),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Índices ──────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_stock_vino ON stock(vino_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_session ON pedidos(session_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_estado ON pedidos(estado);
CREATE INDEX IF NOT EXISTS idx_pedidos_idempotency ON pedidos(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_lineas_pedido ON lineas_pedido(pedido_id);
CREATE INDEX IF NOT EXISTS idx_sesiones_correlacion ON sesiones_agente(correlation_id);
CREATE INDEX IF NOT EXISTS idx_log_pedido ON log_inmutable(pedido_id);
CREATE INDEX IF NOT EXISTS idx_log_created ON log_inmutable(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_vino ON wine_knowledge(vino_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_capa ON wine_knowledge(capa);
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding
    ON wine_knowledge USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
"""


async def run_migrations() -> None:
    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(DDL)
        print("Migraciones aplicadas correctamente.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
