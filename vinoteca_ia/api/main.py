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
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes.approve import router as approve_router
from api.routes.audit import router as audit_router
from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.webhook import router as webhook_router
from core.agent_os_factory import build_agent_os
from storage.migrations import ensure_all_migrations
from storage.postgres import close_pool, get_agno_db, get_pool

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


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
    yield
    await close_pool()


def create_base_app() -> FastAPI:
    """FastAPI con lifespan y routers de dominio (sin AgentOS).

    El CORS se configura en `build_agent_os` vía `cors_allowed_origins` para
    tener una única fuente de verdad; el guard de acceso interno también
    lo aplica el factory.
    """
    app = FastAPI(
        title="Vinoteca IA",
        version="1.0.0",
        description="Sistema multi-agente para recomendación y venta de vinos.",
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(webhook_router)
    app.include_router(approve_router)
    app.include_router(audit_router)
    return app


def create_app() -> FastAPI:
    """Combina la app base con AgentOS y devuelve la app ASGI final."""
    base = create_base_app()
    agent_os = build_agent_os(base_app=base)
    return agent_os.get_app()


app = create_app()
