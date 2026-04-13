"""
Aplicación FastAPI principal de Vinoteca IA.
Lifespan: inicializa pools de DB y Redis, registra middleware y rutas.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.middleware.auth import AuthMiddleware
from api.middleware.logging import LoggingMiddleware
from api.middleware.rate_limit import RateLimitMiddleware
from api.routes import approve, chat, health, webhook
from core.idempotency import close_redis
from storage.postgres import close_pool, get_pool

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("vinoteca_ia_startup")
    await get_pool()
    logger.info("postgres_pool_ready")
    yield
    await close_pool()
    await close_redis()
    logger.info("vinoteca_ia_shutdown")


app = FastAPI(
    title="Vinoteca IA",
    description="Sistema multi-agente de recomendación y ventas para vinoteca.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(approve.router)
app.include_router(webhook.router)

import os
_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
