# Skill: Arquitectura cognitiva — Vinoteca IA

Fuente de verdad: `docs/architecture.md` y el código en `vinoteca_ia/`.

## PRAO

Todo turno de chat pasa por `VinotecaOrchestrator.process_turn`:

1. **Perceive** — guardrails (injection bloquea; PII se enmascara), perfil semántico, working memory (8 turnos).
2. **Reason** — `RouterAgent` T=0.0. Confianza menor a 0.85 → no derivar.
3. **Act** — especialista Agno; tope de pasos; stuck-state a 3 firmas de tool idénticas. Si el LLM cae: `core/llm_fallback.py` + las mismas tools.
4. **Observe** — episódico, KPIs, costo, spans. Summarizer extractivo si hay ≥ 12 turnos.

## SQL vs grafo

- **PostgreSQL / asyncpg**: precio, stock, envío, pedidos, idempotencia de cobro, `log_inmutable`.
- **MemGraphRAG**: capas 1–5 (dato duro, terruño, historia, tendencia, voz propia). PPR λ=0.5, 10 iteraciones. Nunca para cotizar.

## 2PC

1. **Preparación**: `verificar_stock_exacto` + `calcular_orden` (solo lectura). Resumen + "¿Confirmás?".
2. **Ejecución**:
   - Chat PRAO: el cliente dice **confirmo** → `crear_orden` (Redis idempotency, `FOR UPDATE`, SHA-256 en `log_inmutable`).
   - Team/AgentOS: pause por `requires_confirmation=True` → `POST /pedido/{run_id}/aprobar`.

## Topología

Router → Sommelier | Inventory | Orders | Support | Events. Judge + Auditor son jobs (`jobs/nightly_audit.py`), no canal cliente.

HitL de operador y `/admin/*` son fail-closed sin token de entorno.
