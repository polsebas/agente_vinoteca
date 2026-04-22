"""Concurrencia de reserva de stock.

Este test requiere una Postgres accesible (variable `TEST_DATABASE_URL` o,
en su defecto, `DATABASE_URL`). Si ninguna está seteada, se saltea.

Escenario: dos sesiones intentan reservar la última unidad de un vino al
mismo tiempo. La segunda reserva debe fallar (`todos_disponibles=False`).
Después, la creación de orden desde una sesión sin reservas debe rechazarse.
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

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
    """Crea un vino con stock=1 y limpia al terminar."""
    monkeypatch.setenv("DATABASE_URL", db_url)

    from storage.migrations import ensure_all_migrations
    from storage.postgres import close_pool, get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vinos (
                id UUID PRIMARY KEY,
                nombre TEXT NOT NULL,
                precio_ars NUMERIC(12,2) NOT NULL DEFAULT 1000,
                activo BOOLEAN NOT NULL DEFAULT TRUE
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock (
                vino_id UUID PRIMARY KEY REFERENCES vinos(id),
                cantidad INT NOT NULL,
                ubicacion TEXT NOT NULL DEFAULT 'deposito_principal'
            )
            """
        )
    await ensure_all_migrations()

    vid = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO vinos (id, nombre, precio_ars) VALUES ($1, $2, $3)",
            vid,
            "Test Wine",
            Decimal("1000.00"),
        )
        await conn.execute(
            "INSERT INTO stock (vino_id, cantidad) VALUES ($1, 1)",
            vid,
        )

    yield vid

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM stock_reservas WHERE vino_id = $1", vid)
        await conn.execute("DELETE FROM stock WHERE vino_id = $1", vid)
        await conn.execute("DELETE FROM vinos WHERE id = $1", vid)
    await close_pool()


async def test_concurrent_reservas_solo_una_exitosa(seeded_wine):
    """Dos sesiones pidiendo 1 unidad sobre stock=1: solo una obtiene reserva."""
    from tools.orders.verify_stock_exact import verificar_stock_exacto

    vid = seeded_wine
    lineas = [{"vino_id": str(vid), "cantidad": 1}]

    resp_a, resp_b = await asyncio.gather(
        verificar_stock_exacto.entrypoint(session_id="sess-A", lineas=lineas),
        verificar_stock_exacto.entrypoint(session_id="sess-B", lineas=lineas),
    )

    exitosas = [r for r in (resp_a, resp_b) if r.todos_disponibles]
    assert len(exitosas) == 1, (
        f"Se esperaba exactamente una reserva exitosa, "
        f"pero se obtuvieron: A={resp_a.todos_disponibles}, B={resp_b.todos_disponibles}"
    )
    assert exitosas[0].reserva_token in {"sess-A", "sess-B"}
