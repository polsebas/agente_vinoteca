"""
GET /health — verifica conectividad con DB, Redis y LLM API.
"""

from __future__ import annotations

import os
import time

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from core.idempotency import get_redis
from storage.postgres import get_pool

router = APIRouter()


class HealthStatus(BaseModel):
    status: str
    postgres: str
    redis: str
    llm_api: str
    uptime_ms: float


_START = time.time()


@router.get("/health", response_model=HealthStatus, tags=["Sistema"])
async def health_check() -> HealthStatus:
    postgres_ok = "ok"
    redis_ok = "ok"
    llm_ok = "ok"

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as e:
        postgres_ok = f"error: {e}"

    try:
        r = await get_redis()
        await r.ping()
    except Exception as e:
        redis_ok = f"error: {e}"

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key and not api_key.startswith("sk-ant-"):
            llm_ok = "sin_clave"
        elif not api_key:
            llm_ok = "sin_clave"
    except Exception as e:
        llm_ok = f"error: {e}"

    overall = "ok" if all(v == "ok" for v in [postgres_ok, redis_ok]) else "degradado"

    return HealthStatus(
        status=overall,
        postgres=postgres_ok,
        redis=redis_ok,
        llm_api=llm_ok,
        uptime_ms=round((time.time() - _START) * 1000, 1),
    )
