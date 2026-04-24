# Vinoteca IA

Backend multi-agente para una vinoteca: recomendaciones tipo sommelier, consultas de catálogo/stock, pedidos con confirmación humana (human-in-the-loop), soporte y auditoría de corridas. Está construido sobre **[Agno](https://github.com/agno-agi/agno)** (≥ 2.5), expuesto como API **FastAPI** con **AgentOS** como capa de runtime (sesiones en Postgres, observabilidad opcional, dashboard de agentes).

---

## Tabla de contenidos

- [Qué hace el sistema](#qué-hace-el-sistema)
- [Arquitectura en pocas palabras](#arquitectura-en-pocas-palabras)
- [Requisitos](#requisitos)
- [Puesta en marcha](#puesta-en-marcha)
- [Variables de entorno](#variables-de-entorno)
- [Cómo ejecutar la API](#cómo-ejecutar-la-api)
- [Endpoints principales](#endpoints-principales)
- [AgentOS, seguridad y exposición pública](#agentos-seguridad-y-exposición-pública)
  - [Agent UI self-hosted](#agent-ui-self-hosted)
- [Jobs y scripts](#jobs-y-scripts)
- [Tests y calidad](#tests-y-calidad)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Documentación adicional](#documentación-adicional)

---

## Qué hace el sistema

| Área | Rol |
|------|-----|
| **Chat productivo** | `POST /chat` con **SSE**: un *Team* en modo *route* delega en sommelier, pedidos o soporte según el mensaje. |
| **Pedidos** | Flujo con tools que pueden pausar (`requires_confirmation`): el cliente recibe `event: paused` y un operador usa `POST /pedido/{run_id}/aprobar` con token. |
| **Salud** | `GET /health` comprueba Postgres y Redis. |
| **Admin / auditoría** | `POST /admin/auditor/run` dispara el auditor sobre una ventana temporal; el job nocturno vive en `jobs/nightly_audit.py`. |

Los agentes usan **tools** (catálogo, stock, órdenes, FAQ, etc.) y **instrucciones** versionadas en `prompts/*.md`. El modelo LLM se configura con primario + fallback (`LLM_PRIMARY` / `LLM_FALLBACK`).

---

## Arquitectura en pocas palabras

```text
Cliente  →  FastAPI (app base: /health, /chat, /pedido/*, /admin/*)
                ↓
         AgentOS.get_app()  ←  combina rutas Agno + tu app
                ↓
         Team "vinoteca_router" (Sommelier, Orders, Support) + DB Agno (Postgres)
```

- **`api/main.py`**: crea la app base (lifespan: pool asyncpg, tablas Agno, migraciones de dominio) y la envuelve con `build_agent_os()` → `agent_os.get_app()`.
- **`core/agent_os_factory.py`**: registra agentes “sueltos” (router y auditor) + el **Team** productivo (que ya incluye sommelier, orders y support como miembros). Evita duplicar instancias de los mismos roles.
- **`storage/postgres.py`**: pool **asyncpg** para el dominio (catálogo, pedidos, etc.) y **`PostgresDb`** de Agno para sesiones/memorias (`vinoteca_sessions`, `vinoteca_memories`).
- **`core/model_provider.py`**: Claude primario + OpenAI como fallback.

Diagramas HTML viven en `vinoteca_ia/docs/` (ver [Documentación adicional](#documentación-adicional)).

---

## Requisitos

- **Python** ≥ 3.11  
- **PostgreSQL** (recomendado: imagen con **pgvector** para RAG/embeddings)  
- **Redis** (rate limiting, idempotencia)  
- Claves **Anthropic** y/o **OpenAI** según los modelos que uses  

---

## Puesta en marcha

### 1. Clonar e instalar dependencias

Desde la raíz del repo:

```bash
cd vinoteca_ia
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

También podés usar `uv pip install -e ".[dev]"` si tenés [uv](https://github.com/astral-sh/uv) instalado.

### 2. Infra con Docker (Postgres + Redis)

```bash
cd vinoteca_ia
docker compose up -d
```

Eso levanta Postgres (`vinoteca` / `vinoteca_dev` / `vinoteca_db` en el puerto **5432**) y Redis en **6379**, alineado con el ejemplo de `DATABASE_URL` y `REDIS_URL` en `.env.example`.

En el **primer arranque del volumen** de Postgres, la imagen oficial ya crea la base `vinoteca_db` (no hace falta crearla a mano si solo usás ese compose). Si usás un Postgres propio o cambiaste el nombre de la base en `DATABASE_URL`, antes del primer `uvicorn` podés asegurar que exista:

```bash
python scripts/ensure_database.py
```

### 3. Variables de entorno

```bash
cp .env.example .env
# Editá ANTHROPIC_API_KEY, OPENAI_API_KEY, DATABASE_URL, REDIS_URL, tokens de prod, etc.
```

---

## Variables de entorno

Las más importantes están documentadas en [`vinoteca_ia/.env.example`](vinoteca_ia/.env.example). Resumen:

| Grupo | Variables |
|-------|-----------|
| LLM | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LLM_PRIMARY`, `LLM_FALLBACK` (id `claude-*` → Anthropic; si no, OpenAI — podés usar solo OpenAI poniendo ambos ids tipo `gpt-4o-mini`) |
| Datos | `DATABASE_URL`, `DATABASE_POOL_MIN`, `DATABASE_POOL_MAX`, `REDIS_URL` |
| Seguridad API | `APPROVAL_API_TOKEN`, `ADMIN_API_TOKEN`, `CHAT_API_KEY` (opcional en dev) |
| Rate limit | `RATE_LIMIT_CHAT_PER_MIN`, `RATE_LIMIT_APPROVAL_PER_MIN`, `RATE_LIMIT_ADMIN_PER_MIN` |
| Pagos (dev) | `MERCADOPAGO_*`, `MERCADOPAGO_MOCK_ENABLED` |
| Embeddings | `HF_EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, `EMBEDDING_MAX_LENGTH`, `EMBEDDING_DIM` |
| AgentOS | `AGENTOS_TRACING`, `AGENTOS_TELEMETRY`, `AGENTOS_PUBLIC_PATHS`, `AGENTOS_RELAX_LOOPBACK_GUARD`, `OS_SECURITY_KEY`, `AGENTOS_AUTHORIZATION`, `JWT_VERIFICATION_KEY` |

**Nota:** `DATABASE_URL` es obligatoria para **levantar el pool** en el lifespan del servidor; el import de la app puede tolerar su ausencia en entornos de tooling (stub interno para `PostgresDb`), pero en runtime real tenés que configurarla.

---

## Cómo ejecutar la API

Desde `vinoteca_ia/` con el venv activado:

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Al importar la app se carga automáticamente el archivo `.env` del directorio de trabajo (vía `python-dotenv`), así que `DATABASE_URL` definida ahí queda disponible para el proceso.

- Documentación interactiva: `http://localhost:8000/docs` (FastAPI + rutas que AgentOS agrega; las rutas sensibles de AgentOS quedan restringidas — ver sección siguiente).
- Entrypoint legado: `playground.py` reexporta la misma `app` que `api.main` (compatibilidad con `uvicorn playground:app`).

---

## Endpoints principales

| Método y ruta | Descripción |
|---------------|-------------|
| `GET /health` | Estado de Postgres y Redis. |
| `POST /chat` | Stream **SSE** del Team router. Headers opcionales: `X-Chat-Key` si definiste `CHAT_API_KEY`. |
| `POST /pedido/{run_id}/aprobar` | Reanuda un run pausado (HitL). Requiere `X-Approval-Token` = `APPROVAL_API_TOKEN`. |
| `POST /admin/auditor/run` | Ejecuta el auditor sobre las últimas N horas. Requiere `X-Admin-Token` = `ADMIN_API_TOKEN`. |

El cuerpo y los eventos SSE están descritos en los docstrings de [`vinoteca_ia/api/routes/chat.py`](vinoteca_ia/api/routes/chat.py) y [`vinoteca_ia/api/routes/approve.py`](vinoteca_ia/api/routes/approve.py).

---

## AgentOS, seguridad y exposición pública

AgentOS expone muchas rutas útiles en desarrollo (`/agents`, `/teams`, `/approvals`, migraciones de DB, etc.). En este proyecto, un middleware **`InternalPathsGuard`** (montado desde [`core/agent_os_factory.py`](vinoteca_ia/core/agent_os_factory.py)) hace lo siguiente:

- Solo los paths listados en **`AGENTOS_PUBLIC_PATHS`** (por defecto **`/health`**, **`/chat`** y **`/webhook`**) son accesibles desde cualquier IP.
- El resto de rutas (incluidas las de AgentOS) **solo responden si la conexión viene de loopback** (`127.0.0.1`, `::1`, `localhost`). Desde internet devuelven **404** genérico.

Así podés exponer públicamente el balanceador solo hacia `/chat` (y `/health` para probes), y usar port-forward o túnel local para el dashboard de AgentOS.

### UI en [os.agno.com](https://os.agno.com/)

El plan **Free** de Agno incluye el control plane para AgentOS **local**; el modo **Live** (URL HTTPS pública) entra en el flujo **Pro** — ver [pricing](https://www.agno.com/pricing). Para no pagar, el camino documentado es **Local** + tu API en `localhost` o IP.

**Alta del OS** ([Connect Your AgentOS](https://docs.agno.com/agent-os/connect-your-os)):

| Entorno | Qué URL va |
|--------|------------|
| **Local** | `http://localhost:PUERTO` o `http://IP_DE_TU_MÁQUINA:PUERTO` |
| **Live** | HTTPS público (Pro); no es el objetivo del plan free |

Si ves **“Local environment must use localhost or an IP address”**, estás en **Local** pero pegaste algo que no es host local (p. ej. URL `https://…trycloudflare.com`). Volvé a **Local** y usá solo `http://127.0.0.1:8000` (o el puerto que uses).

**Chrome y `https://os.agno.com` → `http://localhost`:** el control plane conecta **desde el navegador directo a tu runtime** ([Control plane](https://docs.agno.com/agent-os/control-plane)); Agno no hace de proxy. En **Chrome** a veces aparece *Permission was denied … loopback address space*: es una **restricción del navegador** entre un origen HTTPS público y loopback, no la API ni CORS. En muchos equipos **Firefox** (u otro motor) deja pasar el mismo flujo **Local** + localhost; si en otro proyecto “te anduvo local”, suele ser por **navegador o versión de Chrome** distinta. No hay nada que este repo pueda cambiar para forzar a Chrome.

**Vinoteca:** con tráfico realmente loopback, **`AGENTOS_RELAX_LOOPBACK_GUARD`** no hace falta para las rutas de AgentOS (el `InternalPathsGuard` ya deja pasar loopback). Dejalo en `false` salvo que uses túnel o IP no local.

En versiones anteriores del factory se pasaba `cors_allowed_origins=["*"]` a AgentOS; Agno **saca** el `*` al armar `CORSMiddleware` y el `allow_origins` quedaba **vacío**. Eso ya está corregido delegando en los defaults de Agno (incluyen `https://os.agno.com`).

Cuando quieras RBAC nativo de AgentOS: `AGENTOS_AUTHORIZATION=true` + `JWT_VERIFICATION_KEY` (ver [documentación de Agno](https://docs.agno.com/reference/agent-os/agent-os)); si activás autorización sin clave, la app falla al arrancar a propósito.

**Telemetría:** `AGENTOS_TELEMETRY` por defecto es `false` (opt-in hacia los servicios de Agno).

### Agent UI self-hosted

Si el control plane en [os.agno.com](https://os.agno.com/) te choca con el navegador (p. ej. HTTPS público → loopback), podés usar la **Agent UI** open source: corre en **tu** máquina (`http://localhost:3000`) y el browser llama a tu AgentOS en `localhost` **mismo origen “local”** (origen `http://localhost:3000` → API `http://localhost:8000`), sin pasar por un sitio HTTPS de terceros. Documentación: [AgentUI](https://docs.agno.com/other/agent-ui).

1. Levantá la API desde `vinoteca_ia/`: `uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload` (o el puerto que uses).
2. En una carpeta aparte (por ejemplo al lado del repo), creá la UI:
   ```bash
   npx create-agent-ui@latest
   ```
   Confirmá el proyecto, luego `cd agent-ui && npm run dev` (o seguí la doc para `pnpm` si clonás [agno-agi/agent-ui](https://github.com/agno-agi/agent-ui)).
3. Abrí `http://localhost:3000` y en el lateral poné el endpoint del OS, p. ej. **`http://127.0.0.1:8000`**. La doc muestra `localhost:7777` porque el ejemplo usa `agent_os.serve()` con el default de Agno; en este proyecto lo habitual es **8000** con `uvicorn`.
4. Con UI y API en la misma máquina, el tráfico al puerto de la API suele verse como **loopback** → **`AGENTOS_RELAX_LOOPBACK_GUARD`** no hace falta para el `InternalPathsGuard`.
5. Los defaults de CORS de Agno incluyen `http://localhost:3000` para esta UI.

---

## Jobs y scripts

| Componente | Uso |
|------------|-----|
| [`jobs/nightly_audit.py`](vinoteca_ia/jobs/nightly_audit.py) | Auditoría programada (ej. cron): `python -m jobs.nightly_audit` desde `vinoteca_ia/`. |
| [`scripts/ensure_database.py`](vinoteca_ia/scripts/ensure_database.py) | Crea la base del `DATABASE_URL` en el cluster si no existe (Postgres ya tiene que estar arriba). |
| [`scripts/ingest_product_details.py`](vinoteca_ia/scripts/ingest_product_details.py) | Ingesta masiva del catálogo desde `product_details.txt` (NDJSON). Upsert idempotente por `imagen` y fragmento `wine_knowledge` capa 1 listo para embeddings. |
| [`scripts/seed_catalog.py`](vinoteca_ia/scripts/seed_catalog.py) | Sembrar catálogo (dataset chico legacy). |
| [`scripts/enrich_catalog.py`](vinoteca_ia/scripts/enrich_catalog.py) | Generar embeddings locales (BETO en Hugging Face) para los fragmentos de `wine_knowledge` sin embedding. Corrida típica post-ingesta. |
| [`scripts/migrate_mongo.py`](vinoteca_ia/scripts/migrate_mongo.py) | Migración desde Mongo (si aplica). |

Orden recomendado para cargar el catálogo desde cero:

```bash
cd vinoteca_ia
python scripts/ingest_product_details.py --dry-run           # valida y muestra reporte
python scripts/ingest_product_details.py                      # persiste en Postgres
python scripts/enrich_catalog.py                              # completa embeddings con BETO (primer run descarga el modelo)
```

Notas:

- La tool [`buscar_por_ocasion`](vinoteca_ia/tools/catalog/search_by_occasion.py) joinea contra `vinos_ocasiones_embeddings`. Esa tabla aún no se genera en la ingesta base: la tool devolverá cero resultados hasta que se construya un job dedicado (fuera del alcance de este loader).
- Las filas sin `precio de lista` se omiten con un contador en el reporte. Las tools de precio asumen valores reales y fallarían contra filas con `NULL` o cero.
- Si migrás desde embeddings viejos (OpenAI 1536), el arranque aplica migración a `vector(768)` y deja `embedding = NULL`; corré `python scripts/enrich_catalog.py` para reindexar con BETO.

---

## Tests y calidad

```bash
cd vinoteca_ia
pytest -q
ruff check .
```

Hay tests de integración para aprobaciones HitL, montaje AgentOS + guard de rutas, reservas de stock, etc. Si algún test de schemas queda desalineado con los modelos Pydantic, conviene actualizar imports o el propio test en el mismo PR que cambie el schema.

---

## Estructura del proyecto

```text
agente_vinoteca/
└── vinoteca_ia/                 # Paquete principal (pyproject.toml acá)
    ├── api/                     # FastAPI: main, routes, deps, middleware
    ├── agents/                  # Fábricas de Agent y Team (router, sommelier, orders, …)
    ├── core/                    # AgentOS factory, modelos, guardrails, RAG, idempotencia
    ├── jobs/                    # Jobs batch (auditor nocturno)
    ├── prompts/                 # Constituciones en markdown por agente
    ├── schemas/                 # Pydantic: I/O de agentes, pedidos, auditoría, …
    ├── storage/                 # Postgres, migraciones
    ├── tools/                   # Tools Agno: catálogo, pedidos, soporte, auditoría, cliente
    ├── tests/                   # unit + integration
    ├── scripts/                 # seed, enrich, migrate
    ├── docs/                    # Diagramas y diseño (HTML)
    ├── static/                  # Assets estáticos si los hay
    ├── docker-compose.yml       # Postgres (pgvector) + Redis
    ├── .env.example
    └── pyproject.toml
```

---

## Documentación adicional

En `vinoteca_ia/docs/`:

- [`diagramas_agentes_vinoteca.html`](vinoteca_ia/docs/diagramas_agentes_vinoteca.html) — diagramas de agentes.  
- [`arquitectura_general_vinoteca.html`](vinoteca_ia/docs/arquitectura_general_vinoteca.html) — visión general.  
- [`agente_vinoteca_diseno.html`](vinoteca_ia/docs/agente_vinoteca_diseno.html) — diseño del agente.  
- [`knowledge_pipeline_sumiller.html`](vinoteca_ia/docs/knowledge_pipeline_sumiller.html) — pipeline de conocimiento / sumiller.

---

## Licencia y contribución

Si el repo define licencia en un archivo `LICENSE`, respetalo al redistribuir. Para contribuir: ramas cortas, tests verdes, y no subir `.env` con secretos reales.

---

## Enlaces útiles

- [Agno — documentación](https://docs.agno.com/)  
- [AgentOS — referencia](https://docs.agno.com/reference/agent-os/agent-os)  
- [FastAPI](https://fastapi.tiangolo.com/)  
- [Uvicorn](https://www.uvicorn.org/)
