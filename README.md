# Vinoteca IA

Sumiller autónomo multi-agente para una vinoteca: recomendaciones con conocimiento cualitativo, consultas deterministas de precio/stock, pedidos con Two-Phase Commit, guardrails y telemetría. Stack: **Agno 2.5.x**, **FastAPI**, **Pydantic v2 (2.13.x)**, **PostgreSQL 16 + pgvector**, **Redis** y **MemGraphRAG**.

El paquete vive en [`vinoteca_ia/`](vinoteca_ia/). Python **3.11+** (Ruff `target-version = py311`; runtime típico 3.12).

---

## Tabla de contenidos

- [Qué es](#qué-es)
- [Arquitectura](#arquitectura)
- [Características](#características)
- [Agentes](#agentes)
- [Quickstart](#quickstart)
- [Variables de entorno](#variables-de-entorno)
- [API](#api)
- [Tests y calidad](#tests-y-calidad)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Documentación](#documentación)

---

## Qué es

Vinoteca IA atiende al cliente (web / WhatsApp / playground) como un sommelier con contratos estrictos: **nunca** inventa precio ni stock. Lo cuantitativo sale de SQL (`asyncpg`); lo cualitativo (terruño, historia, maridaje, voz del sumiller) sale de **MemGraphRAG** con fallback vectorial `VECTOR(768)`.

El turno productivo pasa por el orquestador **PRAO** (Perceive → Reason → Act → Observe) en `VinotecaOrchestrator.process_turn`. AgentOS envuelve la app para dashboard y sesiones Agno en Postgres.

---

## Arquitectura

```text
  Cliente (web / WhatsApp / curl)
              │
              ▼
  ┌─────────────────────────────────────┐
  │  Gateway FastAPI  (:8001)           │
  │  /health  /chat  /webhook  /pedido  │
  │  /admin/metricas  (+ AgentOS)       │
  └─────────────────┬───────────────────┘
                    │  guardrails + correlación
                    ▼
  ┌─────────────────────────────────────┐
  │  Orchestrator PRAO                  │
  │  Router T=0.0 → especialista        │
  │  Fallback SQL/RAG si el LLM cae     │
  └─────────────────┬───────────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   Agno Agents   MemGraphRAG   PostgreSQL 16
   prompts/*.md  PPR λ=0.5     precio, stock,
   tools @tool   5 capas       pedidos, 2PC,
                 VECTOR(768)   memoria, log
        │
        ▼
  Observability: LatencyTracer · CostTracker · KPIMetrics · AlertManager
```

Separación dura:

| Capa | Fuente de verdad | Prohibido |
|------|------------------|-----------|
| Precio, stock, envío, pedido | PostgreSQL vía tools SQL | RAG / LLM |
| Terruño, historia, maridaje, voz | MemGraphRAG (+ pgvector fallback) | inventar fichas |
| Idempotencia / rate limit | Redis (fail-open a SQL si Redis cae) | cobros dobles |

---

## Características

- **MemGraphRAG** (`memgraphrag-core`): grafo heterogéneo + PPR (λ=0.5, 10 iteraciones) y cosine `VECTOR(768)`.
- **2PC de pedidos**: Fase 1 solo lectura (`verificar_stock_exacto` + `calcular_orden`); Fase 2 `crear_orden` tras **"confirmo"**, `idempotency_key` de un solo uso, `FOR UPDATE` y `log_inmutable` con SHA-256 canónico.
- **Memoria en 3 niveles**: working (ventana 8), summarizer (≥ 12 turnos), episódica + semántica en Postgres.
- **Guardrails**: injection/jailbreak bloquean; PII (tarjetas Luhn, DNI, passwords, email, teléfono) se enmascara.
- **Telemetría**: alerta si el turno > **8.0 s**; costo USD por modelo; KPIs en `GET /admin/metricas`.
- **LLM-as-a-Judge**: job nocturno `jobs/nightly_audit.py` (03:00 ART) con 6 criterios binarios; 50 golden + 25+ adversarial.

---

## Agentes

Constituciones en `vinoteca_ia/prompts/*.md`, cargadas por `agents/constitution.py`.

| Agente | T | Rol |
|--------|---|-----|
| Router | 0.0 | Clasifica intención → especialista |
| Sommelier | 0.7 | Recomendación / maridaje (RAG + SQL de control) |
| Inventory | 0.0 | Precio, stock, añadas, zona de entrega (solo SQL) |
| Orders | 0.0 | 2PC, link de pago, estado de pedido |
| Support | 0.4 | FAQ, reclamos, escalada humana |
| Events | 0.0 | Catas y reservas |
| Judge | 0.0 | Rúbrica binaria 6 criterios (auditoría) |

También existe `AuditorAgent` para hallazgos persistidos (`guardar_hallazgo`) en el job nocturno.

Si OpenAI/Anthropic no responden (crédito, 429, etc.), el orquestador usa `core/llm_fallback.py`: ruteo heurístico + las mismas tools SQL/RAG. No se filtran errores de billing al cliente.

---

## Quickstart

```bash
git clone https://github.com/polsebas/agente_vinoteca.git
cd agente_vinoteca/vinoteca_ia
uv sync

docker compose up -d

cp .env.example .env
# Seteá OPENAI_API_KEY y/o ANTHROPIC_API_KEY, DATABASE_URL, REDIS_URL
# En local: ADMIN_API_TOKEN y APPROVAL_API_TOKEN (si no, /admin y /aprobar dan 503)

uv run python storage/migrations.py
uv run python scripts/seed_catalog.py

uv run uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
```

Health: `http://127.0.0.1:8001/health`  
OpenAPI: `http://127.0.0.1:8001/docs`

El seed carga etiquetas demo (Achaval Ferrer Malbec 2022, Luigi Bosca D.O.C., etc.) con stock y 5 capas; el lifespan hidrata MemGraphRAG desde `wine_knowledge`.

Catálogo grande (opcional):

```bash
uv run python scripts/ingest_product_details.py
uv run python scripts/enrich_catalog.py
```

---

## Variables de entorno

Fuente: [`vinoteca_ia/.env.example`](vinoteca_ia/.env.example).

| Grupo | Variables |
|-------|-----------|
| LLM | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LLM_PRIMARY`, `LLM_FALLBACK` (`claude-*` → Anthropic; si no, OpenAI) |
| Datos | `DATABASE_URL`, `REDIS_URL`, `IDEMPOTENCY_TTL_SECONDS` |
| Seguridad | `APPROVAL_API_TOKEN`, `ADMIN_API_TOKEN`, `CHAT_API_KEY` (opcional en dev) |
| Rate limit | `RATE_LIMIT_CHAT_PER_MIN`, `RATE_LIMIT_APPROVAL_PER_MIN`, `RATE_LIMIT_ADMIN_PER_MIN` |
| Pagos | `MERCADOPAGO_*`, `MERCADOPAGO_MOCK_ENABLED` |
| Embeddings | `HF_EMBEDDING_MODEL`, `EMBEDDING_DIM=768` |
| AgentOS | `AGENTOS_PUBLIC_PATHS`, `OS_SECURITY_KEY`, `AGENTOS_TELEMETRY` (default `false`) |

`POST /pedido/{run_id}/aprobar` y `GET /admin/*` son **fail-closed** si falta el token.

---

## API

Detalle en [`docs/api.md`](docs/api.md). Resumen:

| Método | Ruta | Notas |
|--------|------|--------|
| `GET` | `/health` | `db`, `redis`, `graph`, `llm` |
| `POST` | `/chat` | JSON (`stream: false`) o SSE (`stream: true`, default). Body: `mensaje` o `message`. Header `X-Correlation-ID`. |
| `POST` | `/webhook` · `/webhook/mercadopago` | Pagos (PAGADA / FALLIDA) |
| `POST` | `/webhook/whatsapp` | Inbound WhatsApp |
| `POST` | `/pedido/{run_id}/aprobar` | HitL · `X-Approval-Token` |
| `GET` | `/admin/metricas` | KPIs + costo · `X-Admin-Token` |
| `POST` | `/admin/auditor/run` | Judge on-demand · `X-Admin-Token` |

Ejemplo síncrono:

```bash
curl -s http://127.0.0.1:8001/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo","message":"Vino tinto para asado bajo $15000","canal":"whatsapp","stream":false}'
```

---

## Tests y calidad

```bash
cd vinoteca_ia
uv run pytest tests/unit/ tests/integration/
uv run ruff check .
```

Datasets: `tests/datasets/golden_dataset.json` (50) y `adversarial_dataset.json` (≥ 25). Contratos: `schemas/evaluation.py`.

Judge CLI: `uv run python -m tests.judge.run_judge`.

---

## Estructura del repositorio

```text
agente_vinoteca/
├── README.md
├── docs/                          # Guías (arquitectura, API, operaciones)
└── vinoteca_ia/                   # Paquete (pyproject.toml, uv.lock)
    ├── api/                       # FastAPI: routes, middleware, deps
    ├── agents/                    # Fábricas Agno + constituciones
    ├── core/                      # PRAO, guardrails, memoria, RAG, fallback
    ├── knowledge/                 # Captura, pipeline, sources
    ├── observability/             # tracer, cost, KPIs, alerts
    ├── jobs/                      # nightly_audit
    ├── prompts/                   # Constituciones *.md
    ├── schemas/                   # Pydantic extra=forbid
    ├── storage/                   # asyncpg, migraciones, log inmutable
    ├── tools/                     # catalog, orders, support, events, audit
    ├── tests/                     # unit, integration, datasets, judge
    ├── scripts/                   # seed, ingest, enrich, ensure_database
    ├── docs/                      # Diagramas HTML de diseño (históricos)
    ├── docker-compose.yml         # Postgres pgvector + Redis
    └── .env.example
```

---

## Documentación

| Doc | Contenido |
|-----|-----------|
| [docs/architecture.md](docs/architecture.md) | PRAO, MemGraphRAG, memoria, 2PC |
| [docs/api.md](docs/api.md) | Endpoints, contratos, auth |
| [docs/operations.md](docs/operations.md) | Seed, cron, telemetría, AgentOS |
| [docs/development.md](docs/development.md) | Tests, uv, convenciones |
| [vinoteca_ia/docs/](vinoteca_ia/docs/) | HTML de diseño (no son la fuente de verdad operativa) |

- [Agno](https://docs.agno.com/) · [AgentOS](https://docs.agno.com/reference/agent-os/agent-os) · [FastAPI](https://fastapi.tiangolo.com/)
