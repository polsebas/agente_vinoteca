#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════
#  Vinoteca IA — Generador de estructura de proyecto
#  Basado en: Guía de Entorno de Desarrollo (Agno Framework) v1.0
# ══════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colores ───────────────────────────────────────────────────────
WINE='\033[0;31m'
GOLD='\033[0;33m'
SAGE='\033[0;32m'
SLATE='\033[0;34m'
MUTED='\033[0;90m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Banner ────────────────────────────────────────────────────────
echo ""
echo -e "${WINE}${BOLD}  ▓░ Vinoteca IA — Setup de proyecto ░▓${RESET}"
echo -e "${MUTED}  Agno Framework · Python 3.11+ · FastAPI${RESET}"
echo ""

PROJECT_NAME="${1:-vinoteca_ia}"
BASE="./$PROJECT_NAME"

# ── Verificar que no exista ya ────────────────────────────────────
if [ -d "$BASE" ]; then
  echo -e "${WINE}  ✗ El directorio '$PROJECT_NAME' ya existe. Abortando.${RESET}"
  exit 1
fi

# ── Función helper ────────────────────────────────────────────────
mkd() { mkdir -p "$1"; }
mkf() { touch "$1"; }

echo -e "${GOLD}  → Creando estructura en ./$PROJECT_NAME${RESET}"
echo ""

# ══════════════════════════════════════════════════════════════════
# RAÍZ DEL PROYECTO
# ══════════════════════════════════════════════════════════════════
mkd "$BASE"

# Archivos de configuración raíz
mkf "$BASE/pyproject.toml"
mkf "$BASE/.env.example"
mkf "$BASE/.gitignore"
mkf "$BASE/README.md"
mkf "$BASE/docker-compose.yml"

# ══════════════════════════════════════════════════════════════════
# AGENTS — Capa Cognitiva
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/agents"
mkf "$BASE/agents/__init__.py"
mkf "$BASE/agents/router_agent.py"        # Clasificador de intención
mkf "$BASE/agents/sommelier_agent.py"     # Recomendación + RAG
mkf "$BASE/agents/orders_agent.py"        # Two-Phase Commit
mkf "$BASE/agents/inventory_agent.py"     # SQL determinista
mkf "$BASE/agents/support_agent.py"       # Reclamos + escalada
mkf "$BASE/agents/events_agent.py"        # Catas + reservas
mkf "$BASE/agents/judge_agent.py"         # LLM-as-a-Judge nocturno

# ══════════════════════════════════════════════════════════════════
# KNOWLEDGE — Pipeline de Conocimiento
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/knowledge"
mkf "$BASE/knowledge/__init__.py"

mkd "$BASE/knowledge/pipeline"
mkf "$BASE/knowledge/pipeline/__init__.py"
mkf "$BASE/knowledge/pipeline/scraper.py"           # Web scraping bodegas
mkf "$BASE/knowledge/pipeline/transcriber.py"       # Voz → texto sumiller
mkf "$BASE/knowledge/pipeline/enricher.py"          # LLM enriquecedor de fichas
mkf "$BASE/knowledge/pipeline/classifier.py"        # Clasifica en 5 capas
mkf "$BASE/knowledge/pipeline/indexer.py"           # Vectoriza e indexa en RAG
mkf "$BASE/knowledge/pipeline/conflict_resolver.py" # Jerarquía de fuentes

mkd "$BASE/knowledge/sources"
mkf "$BASE/knowledge/sources/__init__.py"
mkf "$BASE/knowledge/sources/winery_websites.py"    # Scraping sitios bodegas
mkf "$BASE/knowledge/sources/social_monitor.py"     # Instagram / TikTok enólogos
mkf "$BASE/knowledge/sources/press_monitor.py"      # Revistas + críticos
mkf "$BASE/knowledge/sources/awards_monitor.py"     # Concursos + rankings
mkf "$BASE/knowledge/sources/podcast_parser.py"     # Transcripción podcasts

mkd "$BASE/knowledge/capture"
mkf "$BASE/knowledge/capture/__init__.py"
mkf "$BASE/knowledge/capture/sommelier_interface.py" # App captura sumiller humano
mkf "$BASE/knowledge/capture/voice_processor.py"     # Procesamiento voz → NLP
mkf "$BASE/knowledge/capture/new_wine_onboarding.py" # Flujo nuevo SKU

# ══════════════════════════════════════════════════════════════════
# TOOLS — Capa de Acción (funciones deterministas)
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/tools"
mkf "$BASE/tools/__init__.py"

mkd "$BASE/tools/catalog"
mkf "$BASE/tools/catalog/__init__.py"
mkf "$BASE/tools/catalog/consult_stock.py"           # SQL: disponibilidad
mkf "$BASE/tools/catalog/consult_price.py"           # SQL: precio exacto
mkf "$BASE/tools/catalog/compare_vintages.py"        # SQL: comparativa cosechas
mkf "$BASE/tools/catalog/search_by_occasion.py"      # RAG: por ocasión
mkf "$BASE/tools/catalog/search_by_pairing.py"       # RAG: por maridaje

mkd "$BASE/tools/orders"
mkf "$BASE/tools/orders/__init__.py"
mkf "$BASE/tools/orders/verify_stock_exact.py"       # SQL: stock exacto previo a compra
mkf "$BASE/tools/orders/calculate_order.py"          # SQL: total + envío + descuentos
mkf "$BASE/tools/orders/create_order.py"             # MUTACIÓN: reserva stock
mkf "$BASE/tools/orders/send_payment_link.py"        # MUTACIÓN: Mercado Pago
mkf "$BASE/tools/orders/check_order_status.py"       # SQL: estado de pedido

mkd "$BASE/tools/customer"
mkf "$BASE/tools/customer/__init__.py"
mkf "$BASE/tools/customer/save_preference.py"        # MUTACIÓN: perfil semántico
mkf "$BASE/tools/customer/load_context.py"           # Carga memoria episódica
mkf "$BASE/tools/customer/consult_delivery_zone.py"  # SQL: zona + horario envío

mkd "$BASE/tools/support"
mkf "$BASE/tools/support/__init__.py"
mkf "$BASE/tools/support/escalate_to_human.py"       # Notif. operador + historial
mkf "$BASE/tools/support/search_faq.py"              # RAG: políticas y preguntas
mkf "$BASE/tools/support/register_complaint.py"      # MUTACIÓN: log CRM

mkd "$BASE/tools/events"
mkf "$BASE/tools/events/__init__.py"
mkf "$BASE/tools/events/consult_events.py"           # SQL: agenda de catas
mkf "$BASE/tools/events/reserve_event.py"            # MUTACIÓN: reserva de lugar

# ══════════════════════════════════════════════════════════════════
# SCHEMAS — Contratos Pydantic (Input / Output / Estado)
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/schemas"
mkf "$BASE/schemas/__init__.py"
mkf "$BASE/schemas/agent_io.py"           # Entrada/salida de agentes
mkf "$BASE/schemas/wine_catalog.py"       # Modelo de vino (5 capas)
mkf "$BASE/schemas/order.py"             # Pedido + líneas + estado
mkf "$BASE/schemas/customer_profile.py"  # Preferencias + historial
mkf "$BASE/schemas/knowledge_fragment.py" # Fragmento del pipeline
mkf "$BASE/schemas/session_state.py"     # Estado inmutable de sesión
mkf "$BASE/schemas/tool_responses.py"    # Respuestas tipadas de tools
mkf "$BASE/schemas/judge_rubric.py"      # Rúbrica del LLM-as-a-Judge

# ══════════════════════════════════════════════════════════════════
# PROMPTS — Constituciones como código (.md)
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/prompts"
mkf "$BASE/prompts/router_v1.md"          # Constitución: clasificador
mkf "$BASE/prompts/sommelier_v1.md"       # Constitución: sumiller
mkf "$BASE/prompts/orders_v1.md"          # Constitución: pedidos
mkf "$BASE/prompts/inventory_v1.md"       # Constitución: inventario
mkf "$BASE/prompts/support_v1.md"         # Constitución: soporte
mkf "$BASE/prompts/events_v1.md"          # Constitución: eventos
mkf "$BASE/prompts/judge_v1.md"           # Constitución: juez auditor
mkf "$BASE/prompts/enricher_v1.md"        # Constitución: enriquecedor de fichas

# ══════════════════════════════════════════════════════════════════
# CORE — Orquestador e Infraestructura
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/core"
mkf "$BASE/core/__init__.py"
mkf "$BASE/core/orchestrator.py"          # Motor PRAO + circuit breaker
mkf "$BASE/core/model_provider.py"        # Fallback resiliente (Claude → GPT-4o)
mkf "$BASE/core/idempotency.py"           # Gestión de idempotency keys
mkf "$BASE/core/guardrails.py"            # Guardrails entrada/salida + PII
mkf "$BASE/core/correlation.py"           # Correlation ID por sesión
mkf "$BASE/core/stuck_state.py"           # Detección y rescate de bucles

mkd "$BASE/core/memory"
mkf "$BASE/core/memory/__init__.py"
mkf "$BASE/core/memory/working_memory.py"   # Ventana deslizante (8 turnos)
mkf "$BASE/core/memory/episodic_store.py"   # PostgreSQL append-only
mkf "$BASE/core/memory/semantic_store.py"   # Perfil permanente cliente
mkf "$BASE/core/memory/summarizer.py"       # Compresión historial largo

mkd "$BASE/core/rag"
mkf "$BASE/core/rag/__init__.py"
mkf "$BASE/core/rag/vector_store.py"        # Conexión al índice vectorial
mkf "$BASE/core/rag/retriever.py"           # Recuperación selectiva por capa
mkf "$BASE/core/rag/embedder.py"            # Generación de embeddings

# ══════════════════════════════════════════════════════════════════
# API — Exposición FastAPI
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/api"
mkf "$BASE/api/__init__.py"
mkf "$BASE/api/main.py"                   # App FastAPI + lifespan

mkd "$BASE/api/routes"
mkf "$BASE/api/routes/__init__.py"
mkf "$BASE/api/routes/chat.py"            # POST /chat + streaming
mkf "$BASE/api/routes/webhook.py"         # POST /webhook (WhatsApp, MP)
mkf "$BASE/api/routes/approve.py"         # POST /pedido/{id}/aprobar (HITL)
mkf "$BASE/api/routes/health.py"          # GET  /health (DB + LLM ping)
mkf "$BASE/api/routes/admin.py"           # GET  /admin/metricas (dueño)

mkd "$BASE/api/middleware"
mkf "$BASE/api/middleware/__init__.py"
mkf "$BASE/api/middleware/auth.py"         # Autenticación de canales
mkf "$BASE/api/middleware/rate_limit.py"   # Rate limiting por canal
mkf "$BASE/api/middleware/logging.py"      # Request/response logging

# ══════════════════════════════════════════════════════════════════
# STORAGE — Persistencia
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/storage"
mkf "$BASE/storage/__init__.py"
mkf "$BASE/storage/postgres.py"           # PgAgentStorage (sesiones)
mkf "$BASE/storage/migrations.py"         # storage.create() + migraciones
mkf "$BASE/storage/immutable_log.py"      # Log de trazabilidad inmutable

# ══════════════════════════════════════════════════════════════════
# OBSERVABILITY — Telemetría y métricas
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/observability"
mkf "$BASE/observability/__init__.py"
mkf "$BASE/observability/tracer.py"       # Tracing cognitivo (latencia, tokens)
mkf "$BASE/observability/cost_tracker.py" # Costo por conversación / diario
mkf "$BASE/observability/metrics.py"      # KPIs: conversión, resolución, NPS
mkf "$BASE/observability/alerts.py"       # Umbrales: latencia > 8s, loops

# ══════════════════════════════════════════════════════════════════
# TESTS — QA con datasets
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/tests"
mkf "$BASE/tests/__init__.py"
mkf "$BASE/tests/conftest.py"

mkd "$BASE/tests/unit"
mkf "$BASE/tests/unit/__init__.py"
mkf "$BASE/tests/unit/test_tools.py"       # Mocks: tools sin tokens
mkf "$BASE/tests/unit/test_schemas.py"     # Validación Pydantic
mkf "$BASE/tests/unit/test_guardrails.py"  # Bloqueo de inyecciones

mkd "$BASE/tests/integration"
mkf "$BASE/tests/integration/__init__.py"
mkf "$BASE/tests/integration/test_sommelier_flow.py"  # E2E: recomendación
mkf "$BASE/tests/integration/test_order_flow.py"      # E2E: Two-Phase Commit
mkf "$BASE/tests/integration/test_react_resilience.py" # Inyección de HTTP 500

mkd "$BASE/tests/datasets"
mkf "$BASE/tests/datasets/golden_dataset.json"    # 50 interacciones perfectas
mkf "$BASE/tests/datasets/adversarial_dataset.json" # Fallos históricos corregidos

mkd "$BASE/tests/judge"
mkf "$BASE/tests/judge/__init__.py"
mkf "$BASE/tests/judge/run_judge.py"       # Runner del LLM-as-a-Judge en CI

# ══════════════════════════════════════════════════════════════════
# SCRIPTS — Utilidades operativas
# ══════════════════════════════════════════════════════════════════
mkd "$BASE/scripts"
mkf "$BASE/scripts/seed_catalog.py"        # Carga inicial del catálogo
mkf "$BASE/scripts/enrich_catalog.py"      # Enriquecimiento masivo (1 vez)
mkf "$BASE/scripts/run_pipeline.py"        # Trigger manual del knowledge pipeline
mkf "$BASE/scripts/export_metrics.py"      # Export CSV de KPIs al dueño
mkf "$BASE/scripts/rollback_knowledge.py"  # Revertir versión del catálogo RAG

# ══════════════════════════════════════════════════════════════════
# PLAYGROUND — Desarrollo local
# ══════════════════════════════════════════════════════════════════
mkf "$BASE/playground.py"                  # Agno Playground: uvicorn playground:app

# ══════════════════════════════════════════════════════════════════
# ÁRBOL VISUAL
# ══════════════════════════════════════════════════════════════════
echo -e "${SAGE}${BOLD}  ✓ Estructura creada exitosamente${RESET}"
echo ""
echo -e "${GOLD}${BOLD}  $PROJECT_NAME/${RESET}"

tree "$BASE" \
  --noreport \
  --charset utf-8 \
  -a \
  --dirsfirst \
  2>/dev/null \
  | tail -n +2 \
  | sed 's/^/  /' \
  | sed "s/\(agents\|knowledge\|tools\|schemas\|prompts\|core\|api\|storage\|observability\|tests\|scripts\)/$(printf '\033[0;33m')\1$(printf '\033[0m')/" \
  | sed "s/\.py$/$(printf '\033[0;90m')&$(printf '\033[0m')/" \
  | sed "s/\.md$/$(printf '\033[0;32m')&$(printf '\033[0m')/"

echo ""

# ══════════════════════════════════════════════════════════════════
# RESUMEN
# ══════════════════════════════════════════════════════════════════
DIRS=$(find "$BASE" -type d | wc -l)
FILES=$(find "$BASE" -type f | wc -l)

echo -e "${MUTED}  ────────────────────────────────────────${RESET}"
echo -e "  ${SLATE}Directorios:${RESET}  $DIRS"
echo -e "  ${SLATE}Archivos:${RESET}     $FILES"
echo ""
echo -e "${MUTED}  Próximos pasos:${RESET}"
echo -e "  ${GOLD}1.${RESET} cp .env.example .env"
echo -e "  ${GOLD}2.${RESET} uv sync  (o pip install -e .)"
echo -e "  ${GOLD}3.${RESET} docker-compose up -d db"
echo -e "  ${GOLD}4.${RESET} python storage/migrations.py"
echo -e "  ${GOLD}5.${RESET} uvicorn playground:app --reload"
echo ""
echo -e "${WINE}${BOLD}  ▓░ Listo para servir ░▓${RESET}"
echo ""
