"""Migraciones idempotentes ejecutadas en el lifespan de la app.

Centralizamos acá los DDL que no maneja Agno (sesiones/memorias las gestiona
`PostgresDb`). Cada función `ensure_*` es segura para correr en cada boot.
"""

from __future__ import annotations

from storage.postgres import get_pool


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


async def ensure_all_migrations() -> None:
    """Ejecuta todas las migraciones en el orden correcto."""
    await ensure_stock_reservas_table()
