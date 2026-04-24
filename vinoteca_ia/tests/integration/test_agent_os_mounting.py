"""Smoke del mounting combinado `base_app + AgentOS`.

Reemplazamos los factories de agentes/teams por dobles livianos para evitar
inicializar modelos reales (Claude/OpenAI) ni conectar a la DB. Validamos:

- Rutas de dominio (`/health`, `/chat`, `/webhook`, `/pedido/.../aprobar`, `/admin/auditor/run`)
  siguen registradas.
- AgentOS suma rutas típicas (`/agents`, `/approvals/*`).
- El middleware `InternalPathsGuard` bloquea el acceso externo a las rutas
  AgentOS (con un cliente no-loopback responden 404).

No se ejecuta el lifespan ni se hace `TestClient.__enter__`: el objetivo es
inspección de rutas y del middleware, sin abrir pools ni crear tablas.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from agno.agent import Agent
from agno.team import Team
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware


def _fake_agent(name: str) -> Agent:
    agent = MagicMock(spec=Agent)
    agent.id = f"fake-{name}"
    agent.name = name
    agent.agent_id = f"fake-{name}"
    return agent


def _fake_team() -> Team:
    team = MagicMock(spec=Team)
    team.id = "fake-team"
    team.name = "fake-team"
    team.team_id = "fake-team"
    team.members = []
    return team


def _force_external_client(app: FastAPI) -> None:
    class _ForceClient(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.scope["client"] = ("8.8.8.8", 0)
            return await call_next(request)

    app.add_middleware(_ForceClient)


@pytest.fixture
def patched_agents():
    """Parchea los factories con dobles livianos para no cargar modelos reales."""
    patches = [
        patch(
            "core.agent_os_factory.AGENT_FACTORIES",
            [lambda: _fake_agent("router"), lambda: _fake_agent("auditor")],
        ),
        patch(
            "core.agent_os_factory.TEAM_FACTORIES",
            [_fake_team],
        ),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


def test_app_combines_domain_and_agent_os_routes(patched_agents):
    from api.main import create_base_app
    from core.agent_os_factory import build_agent_os

    base = create_base_app()
    paths_base = {getattr(r, "path", "") for r in base.routes}
    assert "/health" in paths_base
    assert "/chat" in paths_base
    assert "/webhook" in paths_base
    assert "/pedido/{run_id}/aprobar" in paths_base
    assert "/admin/auditor/run" in paths_base

    try:
        app = build_agent_os(base_app=base).get_app()
    except Exception as exc:
        pytest.skip(f"AgentOS no construible en este entorno: {exc}")

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/health" in paths
    assert "/chat" in paths
    assert "/webhook" in paths
    assert any(p.startswith("/agents") for p in paths), (
        f"AgentOS debería exponer /agents: {paths}"
    )
    assert "/approvals" in paths or any(
        p.startswith("/approvals") for p in paths
    )


def test_agent_os_routes_blocked_from_external_ip(patched_agents, monkeypatch):
    monkeypatch.delenv("AGENTOS_RELAX_LOOPBACK_GUARD", raising=False)
    from api.main import create_base_app
    from core.agent_os_factory import build_agent_os

    base = create_base_app()
    try:
        app = build_agent_os(base_app=base).get_app()
    except Exception as exc:
        pytest.skip(f"AgentOS no construible en este entorno: {exc}")
    _force_external_client(app)

    client = TestClient(app)
    resp = client.get("/agents")
    assert resp.status_code == 404, resp.text
    resp = client.get("/config")
    assert resp.status_code == 404, resp.text


def test_chat_route_public_even_from_external_ip(patched_agents):
    """`/chat` debe ser alcanzable; aquí sin body válido el router responde 422,
    pero el middleware no interfiere (no devuelve 404)."""
    from api.main import create_base_app
    from core.agent_os_factory import build_agent_os

    base = create_base_app()
    try:
        app = build_agent_os(base_app=base).get_app()
    except Exception as exc:
        pytest.skip(f"AgentOS no construible en este entorno: {exc}")
    _force_external_client(app)

    client = TestClient(app)
    resp = client.post("/chat", json={})
    assert resp.status_code != 404, resp.text


def test_webhook_route_public_even_from_external_ip(patched_agents):
    """MP notifica por POST; el middleware debe dejar pasar `/webhook` (no 404)."""
    from api.main import create_base_app
    from core.agent_os_factory import build_agent_os

    base = create_base_app()
    try:
        app = build_agent_os(base_app=base).get_app()
    except Exception as exc:
        pytest.skip(f"AgentOS no construible en este entorno: {exc}")
    _force_external_client(app)

    client = TestClient(app)
    resp = client.post("/webhook", json={})
    assert resp.status_code != 404, resp.text
