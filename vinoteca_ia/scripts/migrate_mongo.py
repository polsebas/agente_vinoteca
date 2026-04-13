"""
Migra el catálogo de vinos desde MongoDB hacia PostgreSQL.
Adaptar los nombres de campos según el esquema real de Mongo.

Uso:
    python scripts/migrate_mongo.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

# ── Mapeo de campos MongoDB → PostgreSQL ─────────────────────────────
# Ajustar este mapeo según el esquema real de la base Mongo del negocio.
FIELD_MAP = {
    "name": "nombre",
    "winery": "bodega",
    "grape": "varietal",
    "vintage": "cosecha",
    "price": "precio",
    "description": "descripcion",
    "region": "region",
    "subregion": "sub_region",
    "alcohol": "alcohol",
    "pairings": "maridajes",
    "stock": "stock",
}


def map_doc(doc: dict) -> tuple[dict, int]:
    """Transforma un documento Mongo al formato de la tabla vinos + stock."""
    vino: dict = {}
    stock: int = 0

    for mongo_field, pg_field in FIELD_MAP.items():
        value = doc.get(mongo_field) or doc.get(pg_field)
        if value is None:
            continue
        if pg_field == "stock":
            stock = int(value)
        elif pg_field == "precio":
            try:
                vino[pg_field] = float(str(value).replace("$", "").replace(",", ""))
            except ValueError:
                vino[pg_field] = 0.0
        elif pg_field == "maridajes":
            vino[pg_field] = value if isinstance(value, list) else [value]
        else:
            vino[pg_field] = value

    if "nombre" not in vino:
        vino["nombre"] = str(doc.get("_id", "Sin nombre"))
    if "bodega" not in vino:
        vino["bodega"] = "Desconocida"
    if "varietal" not in vino:
        vino["varietal"] = "Desconocido"
    if "precio" not in vino or vino["precio"] <= 0:
        vino["precio"] = 0.01  # valor mínimo para cumplir CHECK

    return vino, stock


async def migrate(dry_run: bool = False) -> None:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    mongo_db = os.environ.get("MONGO_DB", "vinoteca_mongo")
    pg_url = os.environ["DATABASE_URL"]

    mongo_client = AsyncIOMotorClient(mongo_url)
    db = mongo_client[mongo_db]

    collections = await db.list_collection_names()
    wine_collection = None
    for name in ["vinos", "wines", "productos", "products", "catalog"]:
        if name in collections:
            wine_collection = name
            break

    if wine_collection is None:
        print(f"No se encontró colección de vinos. Colecciones disponibles: {collections}")
        print("Ajustá MONGO_DB y el nombre de la colección en este script.")
        sys.exit(1)

    docs = await db[wine_collection].find({}).to_list(length=None)
    print(f"Documentos en Mongo: {len(docs)}")

    if dry_run:
        for doc in docs[:3]:
            vino, stock = map_doc(doc)
            print(f"  DRY RUN → {vino['nombre']} | stock: {stock} | precio: {vino.get('precio')}")
        print(f"  ... y {len(docs) - 3} más.")
        return

    pg_conn = await asyncpg.connect(pg_url)
    insertados = 0
    errores = 0

    try:
        for doc in docs:
            try:
                vino, stock = map_doc(doc)

                vino_id = await pg_conn.fetchval(
                    """
                    INSERT INTO vinos (nombre, bodega, varietal, cosecha, precio,
                        descripcion, region, sub_region, alcohol, maridajes)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    vino.get("nombre"),
                    vino.get("bodega"),
                    vino.get("varietal"),
                    vino.get("cosecha"),
                    vino.get("precio", 0.01),
                    vino.get("descripcion"),
                    vino.get("region"),
                    vino.get("sub_region"),
                    vino.get("alcohol"),
                    vino.get("maridajes", []),
                )

                if vino_id and stock > 0:
                    await pg_conn.execute(
                        """
                        INSERT INTO stock (vino_id, cantidad)
                        VALUES ($1, $2)
                        ON CONFLICT (vino_id, ubicacion) DO UPDATE SET cantidad = EXCLUDED.cantidad
                        """,
                        vino_id,
                        stock,
                    )

                if vino_id:
                    insertados += 1
            except Exception as e:
                errores += 1
                print(f"  Error en doc {doc.get('_id')}: {e}")
    finally:
        await pg_conn.close()
        mongo_client.close()

    total = await asyncpg.connect(pg_url)
    count = await total.fetchval("SELECT COUNT(*) FROM vinos")
    await total.close()

    print(f"Migración completada: {insertados} insertados, {errores} errores. Total en PG: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar, no insertar")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run))
