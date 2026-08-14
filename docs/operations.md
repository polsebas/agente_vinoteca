# Operaciones — Vinoteca IA

Comandos desde `vinoteca_ia/` salvo que se indique lo contrario.

## Infra

```bash
docker compose up -d
# postgres: vinoteca / vinoteca_dev / vinoteca_db :5432 (imagen pgvector/pgvector:pg16)
# redis: :6379
```

Si el cluster no tiene la base del `DATABASE_URL`:

```bash
uv run python scripts/ensure_database.py
```

## Migraciones y seed

```bash
uv run python storage/migrations.py
uv run python scripts/seed_catalog.py
```

El seed upserta etiquetas demo (id slug, `activo=true`, stock, 5 capas `fuente=sumiller`) y backfillea `cantidad_disponible` en filas en cero. El lifespan de FastAPI vuelve a correr `ensure_all_migrations()` y `hydrate_engine_from_sql()`.

Ingesta masiva:

```bash
uv run python scripts/ingest_product_details.py --dry-run
uv run python scripts/ingest_product_details.py
uv run python scripts/enrich_catalog.py    # embeddings BETO 768
```

## API local

```bash
uv run uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
```

`:8001` es el puerto de smoke/dev documentado. `APP_PORT` en `.env.example` acompaña ese valor; uvicorn del quickstart manda.

## Tokens de operador

Sin `ADMIN_API_TOKEN` / `APPROVAL_API_TOKEN` los endpoints admin y aprobar responden **503**. En dev:

```bash
# .env
ADMIN_API_TOKEN=vinoteca-admin-dev
APPROVAL_API_TOKEN=vinoteca-approval-dev
```

```bash
curl -s http://127.0.0.1:8001/admin/metricas -H "X-Admin-Token: vinoteca-admin-dev"
```

## LLM

`LLM_PRIMARY` + `LLM_FALLBACK` vía `core/model_provider.py`. Si ambos fallan (sin crédito, 429), el chat **sigue** con tools SQL/RAG (`metadata.fallback: "provider"`). Para sommelier T=0.7 “de verdad” hace falta billing en OpenAI y/o Anthropic.

## Job nocturno

`jobs/nightly_audit.py`:

- Ventana de corridas → Judge (6 criterios, umbral 5/6).
- Persistencia de hallazgos y append a golden (en el path de datasets del job).
- Cron sugerido (03:00 ART si el host está en UTC): `0 6 * * * cd /app && .venv/bin/python -m jobs.nightly_audit`

On-demand: `POST /admin/auditor/run`. CLI eval: `uv run python -m tests.judge.run_judge`.

## Telemetría

| Señal | Umbral / fórmula |
|-------|------------------|
| Latencia de turno | Alerta `warning` / `latency` si supera 8.0 s |
| Costo | lookup por nombre de modelo (Sonnet / Haiku / GPT-4o) |
| Conversión SQL | pedidos `pagada` / sesiones en `log_inmutable` |
| Conversión in-process | sesiones consultivas (`MARIDAJE`, `RECOMENDACION_*`) que llegaron a `crear_orden` |
| Webhook de alertas | `ALERT_WEBHOOK_URL` (fail-open) |

`STOCK_RESERVA_TTL_MIN` está en `.env.example` como documentación de intención; el código actual reserva en `crear_orden` (incrementa `reservado`) y libera en el webhook, sin TTL automático de esa variable.

`playground.py` reexporta `api.main:app` (compatibilidad con `uvicorn playground:app`). El entrypoint documentado es `api.main:app`.

## AgentOS / UI

- Paths públicos: `AGENTOS_PUBLIC_PATHS` (default `/health,/chat,/webhook`).
- Resto: solo loopback (`InternalPathsGuard`).
- Control plane: [os.agno.com](https://os.agno.com/) en modo Local → `http://127.0.0.1:8001`.
- Agent UI self-hosted: `npx create-agent-ui@latest`, endpoint `http://127.0.0.1:8001`.
- `AGENTOS_TELEMETRY=false` por defecto.

## Tests

```bash
uv run pytest tests/unit/ tests/integration/
uv run ruff check .
uv run ruff format --check .
```

Integración de stock/reservas requiere `DATABASE_URL` o `TEST_DATABASE_URL` apuntando al Postgres del compose.
