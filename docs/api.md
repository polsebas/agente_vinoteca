# API HTTP — Vinoteca IA

Base local recomendada: `http://127.0.0.1:8001`.

Contratos de transporte: `vinoteca_ia/schemas/api.py`. Contratos de dominio: `schemas/agent_io.py`, `schemas/order.py`. Casi todos usan `ConfigDict(extra="forbid")`.

## Autenticación

| Recurso | Header | Env | Si falta el env |
|---------|--------|-----|-----------------|
| `/chat` | `X-Chat-Key` opcional | `CHAT_API_KEY` | Abierto (dev) |
| `/pedido/{run_id}/aprobar` | `X-Approval-Token` | `APPROVAL_API_TOKEN` | **503** |
| `/admin/*` | `X-Admin-Token` | `ADMIN_API_TOKEN` | **503** |
| Canal (opt-in) | `X-Channel-Token` | `CHANNEL_AUTH_REQUIRED=true` | Passthrough |

Rate limits (ventana 60 s): `RATE_LIMIT_CHAT_PER_MIN` (30), approval (20), admin (5). Redis fail-open.

Todas las respuestas de chat incluyen **`X-Correlation-ID`**.

## `GET /health`

Siempre HTTP 200. Payload:

```json
{
  "status": "healthy",
  "db": true,
  "redis": true,
  "graph": true,
  "storage": "ok",
  "idempotency": "ok",
  "llm": "ok"
}
```

`graph` es readiness del engine MemGraphRAG (instanciado + hidratado al lifespan). `llm: "ok"` es estático: el fallback cubre un proveedor caído.

## `POST /chat`

Body (`ChatRequest`):

| Campo | Alias | Default | Notas |
|-------|-------|---------|--------|
| `mensaje` | `message` | requerido | Texto del usuario |
| `session_id` | | UUID | Conversación persistente |
| `cliente_id` | | null | Perfil semántico |
| `stream` | | **true** | SSE vs JSON |
| `canal` | | `web` | `web` \| `whatsapp` \| `playground` |

**`stream: false`** → JSON `AgentResponse` (`respuesta`, `agente`, `intencion`, `requiere_aprobacion`, `metadata`, `correlation_id`).

**`stream: true`** → `text/event-stream`. El turno se calcula entero en `process_turn` y después se emiten eventos (no es token-streaming del LLM):

| Evento | Contenido |
|--------|-----------|
| `token` | `{ "content": "<respuesta>", "agente": "…" }` |
| `paused` | Si `requiere_aprobacion`; en el camino PRAO `run_id` puede ser `null` |
| `done` | Payload completo de `AgentResponse` |
| `error` | Fallo interno (mensaje genérico al cliente) |

Ejemplo JSON:

```bash
curl -s http://127.0.0.1:8001/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess-01",
    "message": "¿Cuánto sale el Achaval Ferrer Malbec?",
    "canal": "whatsapp",
    "stream": false
  }'
```

## Webhooks

- `POST /webhook` y `POST /webhook/mercadopago` — notificación MP. Estados típicos `pagada` / `fallida`; actualiza `pedidos` y reservas.
- `POST /webhook/whatsapp` — inbound Cloud API o payload simplificado (`mensaje` / `text` / `from`).

## `POST /pedido/{run_id}/aprobar`

HitL sobre un **run del Team** pausado (`crear_orden` / `enviar_link_pago` con `requires_confirmation=True`). No aplica al JSON síncrono de PRAO, donde la Fase 2 se dispara con el texto **"confirmo"**.

```json
{ "aprobar": true, "session_id": "sess-01", "nota": null }
```

Reanuda con `team.acontinue_run`. Registra KPI HITL y alerta `hitl`.

## Admin

### `GET /admin/metricas`

Mezcla collector in-process + `CostTracker.get_daily_summary()` + totales SQL (fuente histórica). Campos: `conversaciones_totales`, `pedidos_totales`, `tasa_conversion` (pagadas/sesiones SQL), `tasa_escalada`, `latencia_promedio_ms`, `costo_tokens_estimado_usd`, `resolution_rate`, `stuck_state_rate`, `avg_tokens_per_session`.

### `POST /admin/auditor/run`

Dispara `correr_auditor(horas_atras=…)`. En producción el camino principal es el cron de `jobs/nightly_audit.py`.

## AgentOS

La app final es `build_agent_os(...).get_app()`. Rutas `/agents`, `/teams`, `/config` quedan en **loopback** salvo que estén en `AGENTOS_PUBLIC_PATHS` (default `/health,/chat,/webhook`). Ver [operations.md](operations.md).
