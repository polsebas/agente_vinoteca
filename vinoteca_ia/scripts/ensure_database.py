"""Crea la base de datos de `DATABASE_URL` si no existe (solo dev / onboarding).

Conecta al cluster usando la misma URL pero apuntando a la base de mantenimiento
`postgres` (configurable con `POSTGRES_BOOTSTRAP_DATABASE`). Requiere que el
usuario tenga permiso para `CREATE DATABASE` (pasa con el usuario del
`docker-compose.yml`).

Ejecutar desde `vinoteca_ia/`:

    python scripts/ensure_database.py
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse, urlunparse

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def _bootstrap_dsn(database: str) -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print(
            "DATABASE_URL no está seteada. Copiá .env.example a .env o exportá la variable.",
            file=sys.stderr,
        )
        sys.exit(1)
    parsed = urlparse(dsn)
    path = f"/{database}"
    return urlunparse(parsed._replace(path=path))


def _target_db_name() -> str:
    parsed = urlparse(os.environ["DATABASE_URL"])
    name = (parsed.path or "").lstrip("/")
    if not name:
        print("DATABASE_URL no incluye nombre de base en el path.", file=sys.stderr)
        sys.exit(1)
    return name


def main() -> None:
    load_dotenv()
    target_db = _target_db_name()
    bootstrap_db = os.environ.get("POSTGRES_BOOTSTRAP_DATABASE", "postgres")
    admin_dsn = _bootstrap_dsn(bootstrap_db)

    try:
        conn = psycopg2.connect(admin_dsn)
    except psycopg2.OperationalError as e:
        print(
            "No se pudo conectar a Postgres usando DATABASE_URL "
            f"(base de arranque «{bootstrap_db}»).\n"
            "¿Está el servidor arriba? Probá: docker compose up -d\n",
            file=sys.stderr,
        )
        print(e, file=sys.stderr)
        sys.exit(1)

    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (target_db,),
            )
            if cur.fetchone():
                print(f"La base «{target_db}» ya existe. Nada que hacer.")
                return
            cur.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db))
            )
        print(f"Base «{target_db}» creada. Ya podés levantar la API (uvicorn).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
