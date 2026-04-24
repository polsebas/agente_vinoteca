"""Ingesta masiva del catálogo desde `product_details.txt` (NDJSON).

Uso típico:

    # dev: corré las migraciones de catálogo antes o dejá que la API lo haga
    python scripts/ingest_product_details.py --file product_details.txt --dry-run
    python scripts/ingest_product_details.py --file product_details.txt

Flags:
    --file PATH         Ruta al NDJSON (default: `product_details.txt`).
    --dry-run           No abre conexión: valida, normaliza e imprime reporte.
    --limit N           Procesa sólo las primeras N líneas (útil para probar).
    --stock-default N   Cantidad inicial al insertar vinos nuevos (default 0).
    --no-knowledge      No escribir fragmentos en `wine_knowledge`.
    --database-url URL  Override del `DATABASE_URL` del entorno.

Política de filas:
    - Sin `imagen`, `nombre`, `productor` o precio positivo → se reporta en
      `omitidos` y no se persiste (las tools del dominio asumen precios reales).
    - Con `imagen` ya existente → UPSERT sobre `vinos` preservando el UUID y
      el stock previo; `wine_knowledge` capa 1 se inserta o actualiza (embedding
      a NULL para que `scripts/enrich_catalog.py` lo regenere).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

from scripts.ingest.normalizers import normalizar_fila
from scripts.ingest.repository import upsert_fila

load_dotenv()

_BATCH_SIZE = 200


@dataclass(slots=True)
class Reporte:
    leidos: int = 0
    insertados: int = 0
    actualizados: int = 0
    knowledge_escritos: int = 0
    omitidos_sin_precio: int = 0
    omitidos_incompletos: int = 0
    errores_json: int = 0
    errores_sql: int = 0
    muestras_omitidas: list[str] = field(default_factory=list)

    def imprimir(self, *, dry_run: bool) -> None:
        titulo = "Reporte de ingesta (DRY RUN)" if dry_run else "Reporte de ingesta"
        print(f"\n{titulo}")
        print("=" * len(titulo))
        print(f"  Líneas leídas:        {self.leidos}")
        print(f"  Vinos insertados:     {self.insertados}")
        print(f"  Vinos actualizados:   {self.actualizados}")
        print(f"  wine_knowledge capa 1:{self.knowledge_escritos}")
        print(f"  Omitidos (sin precio):{self.omitidos_sin_precio}")
        print(f"  Omitidos (incompletos):{self.omitidos_incompletos}")
        print(f"  Errores JSON:         {self.errores_json}")
        print(f"  Errores SQL:          {self.errores_sql}")
        if self.muestras_omitidas:
            print("  Muestras omitidas:")
            for m in self.muestras_omitidas[:5]:
                print(f"    - {m}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="product_details.txt")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--stock-default", type=int, default=0)
    parser.add_argument("--no-knowledge", action="store_true")
    parser.add_argument("--database-url", default=None)
    return parser.parse_args()


def _iter_lineas(path: Path, limit: int | None):
    with path.open("r", encoding="utf-8") as fh:
        for numero, raw in enumerate(fh, start=1):
            if limit is not None and numero > limit:
                break
            texto = raw.strip()
            if not texto:
                continue
            yield numero, texto


async def _ingestar(
    path: Path,
    *,
    dry_run: bool,
    limit: int | None,
    stock_default: int,
    incluir_knowledge: bool,
    database_url: str | None,
) -> Reporte:
    reporte = Reporte()

    if not dry_run:
        url = database_url or os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError(
                "DATABASE_URL no seteada. Pasá --database-url o cargá .env."
            )
        conn = await asyncpg.connect(url)
    else:
        conn = None

    try:
        pendientes: list[tuple[int, dict]] = []
        for numero, texto in _iter_lineas(path, limit):
            reporte.leidos += 1
            try:
                raw = json.loads(texto)
            except json.JSONDecodeError:
                reporte.errores_json += 1
                continue
            pendientes.append((numero, raw))

            if len(pendientes) >= _BATCH_SIZE:
                await _procesar_lote(pendientes, reporte, conn, stock_default, incluir_knowledge)
                pendientes.clear()

        if pendientes:
            await _procesar_lote(pendientes, reporte, conn, stock_default, incluir_knowledge)
    finally:
        if conn is not None:
            await conn.close()

    return reporte


async def _procesar_lote(
    pendientes: list[tuple[int, dict]],
    reporte: Reporte,
    conn: asyncpg.Connection | None,
    stock_default: int,
    incluir_knowledge: bool,
) -> None:
    if conn is None:
        for _, raw in pendientes:
            fila = normalizar_fila(raw)
            if not fila.imagen_slug or not fila.nombre or not fila.bodega:
                reporte.omitidos_incompletos += 1
                if len(reporte.muestras_omitidas) < 5:
                    reporte.muestras_omitidas.append(
                        f"incompleto: {fila.imagen_slug or fila.nombre or '(sin slug)'}"
                    )
                continue
            if fila.precio_ars is None or fila.precio_ars <= 0:
                reporte.omitidos_sin_precio += 1
                if len(reporte.muestras_omitidas) < 5:
                    reporte.muestras_omitidas.append(
                        f"sin precio: {fila.imagen_slug}"
                    )
                continue
        return

    for numero, raw in pendientes:
        fila = normalizar_fila(raw)
        if not fila.imagen_slug or not fila.nombre or not fila.bodega:
            reporte.omitidos_incompletos += 1
            if len(reporte.muestras_omitidas) < 5:
                reporte.muestras_omitidas.append(
                    f"incompleto (L{numero}): "
                    f"{fila.imagen_slug or fila.nombre or '(sin slug)'}"
                )
            continue
        if fila.precio_ars is None or fila.precio_ars <= 0:
            reporte.omitidos_sin_precio += 1
            if len(reporte.muestras_omitidas) < 5:
                reporte.muestras_omitidas.append(
                    f"sin precio (L{numero}): {fila.imagen_slug}"
                )
            continue

        try:
            _, insertado, knowledge_escrito = await upsert_fila(
                conn,
                fila,
                stock_default=stock_default,
                incluir_knowledge=incluir_knowledge,
            )
        except asyncpg.PostgresError as exc:
            reporte.errores_sql += 1
            if len(reporte.muestras_omitidas) < 5:
                reporte.muestras_omitidas.append(
                    f"sql error (L{numero}): {fila.imagen_slug} → {exc}"
                )
            continue

        if insertado:
            reporte.insertados += 1
        else:
            reporte.actualizados += 1
        if knowledge_escrito:
            reporte.knowledge_escritos += 1


async def main_async() -> int:
    args = _parse_args()
    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: no encuentro {path}", file=sys.stderr)
        return 1

    reporte = await _ingestar(
        path,
        dry_run=args.dry_run,
        limit=args.limit,
        stock_default=args.stock_default,
        incluir_knowledge=not args.no_knowledge,
        database_url=args.database_url,
    )
    reporte.imprimir(dry_run=args.dry_run)
    if reporte.errores_sql or reporte.errores_json:
        return 2
    return 0


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
