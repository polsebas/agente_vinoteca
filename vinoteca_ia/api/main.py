"""App FastAPI: ciclo de vida, routers de dominio y runtime AgentOS.

La app final (`app`) es el resultado de envolver el FastAPI base con un
`AgentOS` vía `base_app`/`get_app()`. De esa manera obtenemos en un solo
proceso:

- Los routers de dominio (`/health`, `/chat`, `/pedido/*`, `/admin/*`).
- La superficie estándar de AgentOS (dashboard y endpoints de agentes)
  con persistencia de sesiones/memoria en Postgres vía `PostgresDb`.

El lifespan vive en la app base: inicializa el pool de asyncpg, las tablas
de Agno y las migraciones de dominio antes de aceptar tráfico.
"""

from __future__ import annotations

import logging
import os
import warnings
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.middleware.auth import AuthMiddleware
from api.middleware.logging import LoggingMiddleware
from api.middleware.rate_limit import RateLimitMiddleware
from api.routes.admin import router as admin_router
from api.routes.approve import router as approve_router
from api.routes.audit import router as audit_router
from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.webhook import router as webhook_router
from core.agent_os_factory import build_agent_os
from core.correlation import get_current
from core.rag.memgraph_adapter import hydrate_engine_from_sql
from observability import get_alert_manager, get_cost_tracker, get_kpi_collector
from storage.migrations import ensure_all_migrations
from storage.postgres import close_pool, get_agno_db, get_pool

load_dotenv()

# Agno 2.5.x: `GET /config` y `GET .../configs/{version}` comparten operation_id
# "get_config" (router base vs components). OpenAPI duplica el id; el aviso es ruido.
warnings.filterwarnings(
    "ignore",
    message=r"^Duplicate Operation ID get_config for function get_config_version\b",
    category=UserWarning,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("vinoteca.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa pool de Postgres y tablas antes del primer request."""
    await get_pool()
    db = get_agno_db()
    if hasattr(db, "create"):
        db.create()
    elif hasattr(db, "acreate"):
        await db.acreate()
    await ensure_all_migrations()
    try:
        hydrated = await hydrate_engine_from_sql()
        logger.info("MemGraphRAG listo (%s fragmentos)", hydrated)
    except Exception:
        logger.exception("No se pudo hidratar MemGraphRAG; el health seguirá degradable")
    app.state.alerts = get_alert_manager()
    app.state.cost_tracker = get_cost_tracker()
    app.state.kpis = get_kpi_collector()
    yield
    await close_pool()


def _correlation_headers() -> dict[str, str]:
    cid = get_current()
    return {"X-Correlation-ID": cid} if cid else {}


def create_base_app() -> FastAPI:
    """FastAPI con lifespan, middlewares y routers de dominio (sin AgentOS).

    El CORS de AgentOS se configura en `build_agent_os`; acá cubrimos la app
    base para tests y para el caso sin wrapping.
    """
    app = FastAPI(
        title="Vinoteca IA",
        version="1.0.0",
        description="Sistema multi-agente para recomendación y venta de vinos.",
        lifespan=lifespan,
    )
    origins = [
        o.strip()
        for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(LoggingMiddleware)

    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(webhook_router)
    app.include_router(approve_router)
    app.include_router(audit_router)
    app.include_router(admin_router)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=_correlation_headers(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors()},
            headers=_correlation_headers(),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Error no controlado: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno. Reintentá en un momento."},
            headers=_correlation_headers(),
        )

    return app


def create_app() -> FastAPI:
    """Combina la app base con AgentOS y devuelve la app ASGI final."""
    base = create_base_app()
    agent_os = build_agent_os(base_app=base)
    return agent_os.get_app()


app = create_app()
