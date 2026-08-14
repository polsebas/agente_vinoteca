# Arquitectura — Vinoteca IA

Fuente de verdad: el código en `vinoteca_ia/`. Este documento describe lo **implementado**.

## Capas

1. **Gateway** — FastAPI (`api/main.py`) + middlewares (auth de canal, logging, rate limit) + AgentOS.
2. **Orchestrator PRAO** — `VinotecaOrchestrator.process_turn`: guardrail → contexto → router → especialista → memoria → telemetría.
3. **Agentes Agno 2.5** — `output_schema` Pydantic, tools `@tool`, instrucciones desde `prompts/*.md`.
4. **Datos** — PostgreSQL 16 (asyncpg) para transaccional; MemGraphRAG in-memory hidratado desde `wine_knowledge`; Redis para idempotencia.
5. **Observability** — `LatencyTracer`, `CostTracker`, `KPIMetricsCollector`, `AlertManager`.

## PRAO

- **Perceive**: `check_input_guardrails`, carga de perfil (`SemanticStore`) y working memory.
- **Reason**: Router `T=0.0` emite `RouterOutput` (`extra=forbid`). Confianza menor a 0.85 → aclaración.
- **Act**: especialista `arun` con tope de 5 pasos; stuck-state a 3 firmas de tool idénticas.
- **Observe**: episódico append-only, KPIs, costo de tokens, spans de latencia.

Si el proveedor LLM falla, `core/llm_fallback.py` clasifica por heurística y ejecuta las **mismas tools** (SQL/RAG). No se reenvían mensajes de billing al cliente.

## MemGraphRAG

Módulo: `core/rag/memgraph_adapter.py` + `wine_graph_schema.py`. Dependencia: `memgraphrag-core`.

### Cinco capas (`CapaConocimiento`)

| # | Capa | Contenido |
|---|------|-----------|
| 1 | Dato duro | Ficha técnica (sin usar para precio/stock de venta) |
| 2 | Terruño | Altura, suelo, valle |
| 3 | Historia | Bodega, enólogo, elaboración |
| 4 | Tendencia | Crítica, natural/orgánico, mercado |
| 5 | Voz propia | Opinión del sumiller de la vinoteca |

### Grafo

Nodos: `VINO`, `BODEGA`, `ENOLOGO`, `TERRUNO_REGION`, `VARIETAL`, `MARIDAJE`, `OCASION`, `ESTILO_FILOSOFIA`, `NOTA_SUMILLER`.

Retrieval: seeds vectoriales → **PPR** (`λ = 0.5`, máx. 10 iteraciones) → `RAGResult`. Fallback: `wine_knowledge.embedding <=>` cosine, umbral 0.30.

Al boot, `hydrate_engine_from_sql()` carga fragmentos activos (prioridad `sumiller` / `seed`).

## Memoria

| Nivel | Dónde | Comportamiento |
|-------|--------|----------------|
| Working | in-process | Últimos **8** turnos |
| Summarizer | extractivo, sin LLM | Se dispara con **≥ 12** turnos |
| Episódica | Postgres | Historial de interacciones / pedidos |
| Semántica | `clientes`, `cliente_preferencias` | Perfil persistente |

## Two-Phase Commit

**Fase 1 (no muta stock)**

1. `verificar_stock_exacto` — lectura: `cantidad_disponible - reservado`.
2. `calcular_orden` — subtotal SQL, descuento 6/12 botellas, envío `$2500` o **gratis** si subtotal post-descuento ≥ `$30.000` (retiro = `$0`).
3. Resumen al cliente y pedido de **"confirmo"**. `requiere_aprobacion=true`.

**Fase 2 (mutación)**

1. `crear_orden` con `idempotency_key` Redis (un solo uso) + UNIQUE SQL.
2. Transacción: `SELECT … FOR UPDATE` en `stock`, incrementa `reservado`, inserta `pedidos` / `pedido_lineas`, estado `aprobada`.
3. `enviar_link_pago` (mock Mercado Pago en dev, TTL 30 min).
4. Fila en `log_inmutable` con `payload_hash` SHA-256 del JSON canónico (`sort_keys=True`).

Confirmación del cliente y pause de framework son **dos caminos distintos**:

| Camino | Cómo se confirma | Dónde corre |
|--------|------------------|-------------|
| Chat (`POST /chat` → PRAO) | El cliente dice **"confirmo"** (o equivalente) en el turno siguiente; el agente o el fallback llama `crear_orden.entrypoint` | `VinotecaOrchestrator` |
| Team / AgentOS | Tools con `requires_confirmation=True` pausan el run; un operador llama `POST /pedido/{run_id}/aprobar` | `crear_router_team` + `team.acontinue_run` |

## Guardrails

- Injection / jailbreak (EN/ES, p. ej. “ignorá … instrucciones previas”) → bloqueo educado, agente `guardrail`.
- PII → máscara; el turno **sigue**.
- Salida: se recortan tracebacks y claves internas (`system_prompt`, `razonamiento`, …).

## Observabilidad

- `LatencyTracer`: spans `guardrails`, `llm_reasoning`, `tool_execution`; alerta `> 8.0 s`.
- `CostTracker`: USD / millón (Sonnet $3/$15, Haiku $0.80/$4, GPT-4o $2.50/$10).
- KPIs: `resolution_rate`, `conversion_rate` (consulta → orden), `stuck_state_rate`, `avg_latency_ms`, tokens promedio.
- Judge: 6 criterios en `schemas/judge_rubric.py`; aprueba con ≥ 5/6. Cron típico: `0 6 * * *` (03:00 ART si el host está en UTC).
