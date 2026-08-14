# Desarrollo

Paquete: `vinoteca_ia/`. Python 3.11+, gestor **uv**.

## Entorno

```bash
cd vinoteca_ia
uv sync
cp .env.example .env
docker compose up -d
uv run python storage/migrations.py
uv run python scripts/seed_catalog.py
```

Correr la API: ver [operations.md](operations.md).

## Tests

| Carpeta | Qué cubre |
|---------|-----------|
| `tests/unit/` | schemas, tools, guardrails, memoria, RAG, observability, agentes (sin red) |
| `tests/integration/` | 2PC, stock, sommelier, API, AgentOS, HitL, resiliencia ReAct |
| `tests/datasets/` | 50 golden + 25 adversarial (`schemas/evaluation.py`) |
| `tests/judge/` | CLI `python -m tests.judge.run_judge` |

```bash
uv run pytest tests/unit/ tests/integration/
uv run ruff check .
uv run ruff format --check .
```

Integración de pedidos/stock necesita Postgres del compose (`DATABASE_URL` o `TEST_DATABASE_URL`).

## Contratos

- Dominio: `schemas/*.py` con `extra="forbid"`.
- Transporte HTTP: `schemas/api.py` (`populate_by_name` en chat: `mensaje` / `message`).
- Constituciones: `prompts/*.md` — no hardcodear instrucciones largas en Python.

## No hacer

- Inventar precio/stock en prompts o en el grafo.
- Mutar stock en Fase 1.
- Commitear `.env`.
- Exponer `/agents` o `/config` fuera de loopback sin `AGENTOS_RELAX_LOOPBACK_GUARD` / `AGENTOS_PUBLIC_PATHS`.
