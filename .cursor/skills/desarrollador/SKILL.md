# Skill: Estándares de desarrollo — Vinoteca IA

Código en `vinoteca_ia/`. Documentación operativa: `docs/` en la raíz del repo.

## Stack

- **Agno 2.5.x** (no 1.x). Agentes vía `agents/constitution.py` + `prompts/*.md`.
- **Python 3.11+**, **Pydantic v2** con `ConfigDict(extra="forbid")` en contratos de dominio.
- **uv** (`uv sync`, `uv run pytest`, `uv run ruff`).
- Async de punta a punta: `asyncpg`, `httpx`. Precio/stock **solo SQL**, nunca RAG.

## Agentes y temperatura

| Agente | T | Notas |
|--------|---|--------|
| Router, Orders, Inventory, Events, Judge, Auditor | 0.0 | Tools / JSON determinista |
| Sommelier | 0.7 | Narrativa; stock sigue saliendo de SQL |
| Support | 0.4 | FAQ / reclamos |

Salida estructurada: `output_schema=` (Agno 2.5), no el `response_model` de 1.x.

## Tools

- Nombres `snake_case` imperativo (`consultar_precio`, `crear_orden`).
- Docstring cognitivo: **cuándo** invocarla, no un resumen del código.
- Mutaciones críticas (`crear_orden`, `enviar_link_pago`): `requires_confirmation=True`.
- Datos cuantitativos: `storage.postgres` / tools en `tools/catalog` y `tools/orders`.
- Cualitativo: MemGraphRAG (`core/rag/memgraph_adapter.py`), fallback `VECTOR(768)`.

## Tests

```bash
cd vinoteca_ia
uv run pytest tests/unit/ tests/integration/
uv run ruff check .
```

Datasets: `tests/datasets/golden_dataset.json` (50), `adversarial_dataset.json` (25).
