"""Acceso asíncrono a PostgreSQL + DB de sesiones de Agno.

Dos responsabilidades claras:

1. `get_pool()` / `fetch_all()` / `fetchrow()` / `execute()`  → pool de `asyncpg`
   usado por las tools para consultas de dominio (catálogo, stock, pedidos).
   Determinista, sin LLM, sin creatividad.

2. `get_agno_db()` → instancia de `PostgresDb` (Agno 2.5) usada para persistir
   sesiones/memorias de los agentes. Se llama una sola vez en el lifespan
   del servidor y se comparte entre todos los agentes.

Nunca importar `os.environ` directamente en capas superiores: se lee acá.
"""

from __future__ import annotations

import os
from typing import Any

import asyncpg
from agno.db.postgres import PostgresDb

_pool: asyncpg.Pool | None = None
_agno_db: PostgresDb | None = None


_IMPORT_STUB_URL = "postgresql://vinoteca:stub@vinoteca-import-stub.invalid:5432/stub"


def _database_url(*, required: bool = True) -> str:
    """Devuelve el `DATABASE_URL` del entorno.

    Con `required=True` (default) falla loud si falta: lo usamos antes de
    abrir el pool real en el lifespan. Con `required=False` devolvemos un
    stub sintácticamente válido para permitir construir objetos perezosos
    (ej. `PostgresDb` de Agno, que solo crea el engine) a tiempo de import
    sin obligar a los entornos de test/tooling a setear la variable.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    if required:
        raise RuntimeError(
            "DATABASE_URL no está configurada. Copiá .env.example a .env."
        )
    return _IMPORT_STUB_URL


async def get_pool() -> asyncpg.Pool:
    """Devuelve el pool singleton de asyncpg. Crea el pool si no existe."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=_database_url(),
            min_size=int(os.environ.get("DATABASE_POOL_MIN", "2")),
            max_size=int(os.environ.get("DATABASE_POOL_MAX", "10")),
            command_timeout=30,
        )
    return _pool


async def close_pool() -> None:
    """Cierra el pool en shutdown del servidor."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch_all(query: str, *args: Any) -> list[asyncpg.Record]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def execute(query: str, *args: Any) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


async def ping() -> bool:
    """Salud: ejecuta SELECT 1. Usado por /health."""
    try:
        row = await fetchrow("SELECT 1 AS ok")
        return bool(row and row["ok"] == 1)
    except Exception:
        return False


def get_agno_db() -> PostgresDb:
    """Devuelve la instancia de PostgresDb para sesiones/memorias de Agno.

    La creación es lazy: PostgresDb maneja su propio engine interno. Debe
    llamarse desde el lifespan del servidor para crear las tablas antes de
    aceptar requests.
    """
    global _agno_db
    if _agno_db is None:
        _agno_db = PostgresDb(
            db_url=_database_url(required=False),
            session_table="vinoteca_sessions",
            memory_table="vinoteca_memories",
        )
    return _agno_db
