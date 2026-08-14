"""Integración de endpoints de dominio sin lifespan ni LLM real."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from schemas.agent_io import AgentResponse, IntentClass
from schemas.api import MetricasKPI


def _noop():
    async def _inner():
        return None

    return _inner


def _orch_mock(respuesta: str = "Te recomiendo un Malbec de Valle de Uco.") -> MagicMock:
    orch = MagicMock()
    orch.process_turn = AsyncMock(
        return_value=AgentResponse(
            session_id="sess-api",
            correlation_id="corr_sess-api_1",
            respuesta=respuesta,
            agente="agente_sommelier",
            intencion=IntentClass.MARIDAJE,
        )
    )
    return orch


def _build_app() -> FastAPI:
    from api.deps import admin_rate_limiter, chat_rate_limiter, optional_chat_key
    from api.routes.admin import router as admin_router
    from api.routes.chat import router as chat_router
    from api.routes.health import router as health_router
    from api.routes.webhook import router as webhook_router

    app = FastAPI()
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(webhook_router)
    app.include_router(admin_router)
    app.dependency_overrides[chat_rate_limiter] = _noop()
    app.dependency_overrides[admin_rate_limiter] = _noop()
    app.dependency_overrides[optional_chat_key] = _noop()
    return app


@pytest.fixture
def orch() -> MagicMock:
    return _orch_mock()


def test_health_healthy():
    mock_mgr = MagicMock()
    mock_mgr.ping = AsyncMock(return_value=True)
    with (
        patch("api.routes.health.ping_postgres", new_callable=AsyncMock, return_value=True),
        patch("api.routes.health.IdempotencyManager", return_value=mock_mgr),
        patch("api.routes.health.ping_graph", return_value=True),
    ):
        client = TestClient(_build_app())
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["db"] is True
    assert body["redis"] is True
    assert body["graph"] is True


def test_chat_json_sync(orch: MagicMock):
    with patch("api.routes.chat.get_orchestrator", return_value=orch):
        client = TestClient(_build_app())
        resp = client.post(
            "/chat",
            json={"mensaje": "vino para asado", "session_id": "sess-api", "stream": False},
        )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Correlation-ID")
    body = resp.json()
    assert "Malbec" in body["respuesta"]
    assert body["agente"] == "agente_sommelier"
    orch.process_turn.assert_awaited_once()


def test_chat_sse_stream(orch: MagicMock):
    with patch("api.routes.chat.get_orchestrator", return_value=orch):
        client = TestClient(_build_app())
        resp = client.post(
            "/chat",
            json={"mensaje": "vino para asado", "session_id": "sess-api", "stream": True},
        )
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert "event: token" in resp.text
    assert "event: done" in resp.text
    assert resp.headers.get("X-Correlation-ID")


def test_webhook_mercadopago_marca_pagada():
    pedido = {"id": "PED-abc123", "estado": "aprobada", "session_id": "sess-pay"}
    with (
        patch("api.routes.webhook.fetchrow", new_callable=AsyncMock, return_value=pedido),
        patch("api.routes.webhook.execute", new_callable=AsyncMock) as mock_exec,
        patch(
            "api.routes.webhook.fetch_all",
            new_callable=AsyncMock,
            return_value=[{"producto_id": "achaval-malbec-2022", "cantidad": 2}],
        ),
        patch("api.routes.webhook.registrar", new_callable=AsyncMock) as mock_log,
    ):
        client = TestClient(_build_app())
        resp = client.post(
            "/webhook/mercadopago",
            json={"external_reference": "vnt_PED-abc123", "status": "approved"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["estado"] == "pagada"
    assert mock_exec.await_count >= 2
    mock_log.assert_awaited()


def test_webhook_whatsapp_rutea_orquestador(orch: MagicMock):
    with patch("api.routes.webhook.get_orchestrator", return_value=orch):
        client = TestClient(_build_app())
        resp = client.post(
            "/webhook/whatsapp",
            json={"mensaje": "vino para asado", "session_id": "wa-1", "from": "54911"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert "Malbec" in body["respuesta"]
    orch.process_turn.assert_awaited()


def test_admin_metricas(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-admin")

    async def fake_fetchrow(_sql: str, *args):
        if "elapsed_ms" in _sql:
            return {"avg_ms": 120.0}
        if "pagada" in _sql:
            return {"n": 2}
        if "escala" in _sql:
            return {"n": 1}
        if "pedidos" in _sql.lower() and "COUNT(*)" in _sql:
            return {"n": 5}
        return {"n": 10}

    with patch("api.routes.admin.fetchrow", side_effect=fake_fetchrow):
        from api.deps import admin_rate_limiter
        from api.routes.admin import router as admin_router

        app = FastAPI()
        app.include_router(admin_router)
        app.dependency_overrides[admin_rate_limiter] = _noop()
        client = TestClient(app)
        resp = client.get("/admin/metricas", headers={"X-Admin-Token": "test-admin"})
    assert resp.status_code == 200, resp.text
    kpi = MetricasKPI.model_validate(resp.json())
    assert kpi.conversaciones_totales == 10
    assert kpi.pedidos_totales == 5
    assert kpi.tasa_conversion == 0.2
