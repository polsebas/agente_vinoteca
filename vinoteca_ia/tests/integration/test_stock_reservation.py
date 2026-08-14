"""Concurrencia de creación de orden (Fase 2 2PC).

`verificar_stock_exacto` es de solo lectura; la exclusión mutua ocurre en
`crear_orden` con `FOR UPDATE` + UPDATE condicional.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


def _test_db_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="module")
def db_url():
    url = _test_db_url()
    if not url:
        pytest.skip("Sin DB de prueba (TEST_DATABASE_URL/DATABASE_URL).")
    return url


@pytest.fixture
async def seeded_wine(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    from storage.migrations import ensure_all_migrations
    from storage.postgres import close_pool, get_pool

    try:
        await ensure_all_migrations()
    except OSError as exc:
        pytest.skip(f"Postgres no disponible: {exc}")
    pool = await get_pool()
    vid = "test-wine-stock-1"
    precio = Decimal("1000.00")
    async with pool.acquire() as conn:
        cols = {
            row["column_name"]
            for row in await conn.fetch(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'vinos'
                """
            )
        }
        if "precio_ars" in cols:
            await conn.execute(
                """
                INSERT INTO vinos (id, nombre, bodega, precio, precio_ars, anada, activo)
                VALUES ($1, $2, $3, $4, $4, 2020, TRUE)
                ON CONFLICT (id) DO UPDATE
                SET precio = EXCLUDED.precio, precio_ars = EXCLUDED.precio_ars, activo = TRUE
                """,
                vid,
                "Test Wine",
                "Test",
                precio,
            )
        else:
            await conn.execute(
                """
                INSERT INTO vinos (id, nombre, bodega, precio, anada, activo)
                VALUES ($1, $2, $3, $4, 2020, TRUE)
                ON CONFLICT (id) DO UPDATE SET precio = EXCLUDED.precio, activo = TRUE
                """,
                vid,
                "Test Wine",
                "Test",
                precio,
            )
        await conn.execute("DELETE FROM pedido_lineas WHERE producto_id = $1", vid)
        await conn.execute(
            "DELETE FROM pedidos WHERE id LIKE 'PED-%' AND session_id LIKE 'sess-conc-%'"
        )
        await conn.execute("DELETE FROM stock WHERE producto_id = $1", vid)
        await conn.execute(
            """
            INSERT INTO stock (producto_id, cantidad_disponible, reservado)
            VALUES ($1, 1, 0)
            """,
            vid,
        )
    yield vid
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM pedido_lineas WHERE producto_id = $1", vid)
        await conn.execute("DELETE FROM stock WHERE producto_id = $1", vid)
        await conn.execute("DELETE FROM vinos WHERE id = $1", vid)
    await close_pool()


async def test_verify_stock_es_solo_lectura(seeded_wine):
    from tools.orders.verify_stock_exact import verificar_stock_exacto

    vid = seeded_wine
    a = await verificar_stock_exacto.entrypoint(
        session_id="sess-A",
        lineas=[{"producto_id": vid, "cantidad": 1}],
    )
    b = await verificar_stock_exacto.entrypoint(
        session_id="sess-B",
        lineas=[{"producto_id": vid, "cantidad": 1}],
    )
    assert a.todos_disponibles is True
    assert b.todos_disponibles is True
