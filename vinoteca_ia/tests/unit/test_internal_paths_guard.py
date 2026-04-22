"""Tests del middleware `InternalPathsGuard`.

Objetivo del guard: restringir el tráfico a loopback salvo por los paths
declarados como públicos (`/health`, `/chat` por default). Cubrimos:

- Public allowlist: prefijo exacto y prefijo con sub-path.
- Loopback passthrough: 127.0.0.1 y ::1 llegan a cualquier ruta.
- Bloqueo 404 para IP no local hacia rutas internas (incluye las que
  expondría AgentOS: `/agents/*`, `/approvals/*`, `/databases/*`).
- Override por env (`AGENTOS_PUBLIC_PATHS`).

TestClient levanta requests desde `testclient` (client.host == "testclient"),
que **no** es loopback a los fines del guard. Para simular llamadas locales
parcheamos el `request.client` vía un middleware auxiliar.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from core.agent_os_factory import (
    InternalPathsGuard,
    _public_paths,
    add_internal_paths_guard,
)


def _build_app(
    public_paths: tuple[str, ...] = ("/health", "/chat"),
    force_client_host: str | None = None,
) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/chat")
    def chat():
        return {"ok": True}

    @app.get("/chat/history")
    def chat_history():
        return {"ok": True}

    @app.post("/agents/{agent_id}/runs")
    def agent_runs(agent_id: str):
        return {"agent_id": agent_id}

    @app.post("/approvals/{approval_id}/resolve")
    def approvals_resolve(approval_id: str):
        return {"approval_id": approval_id}

    app.add_middleware(InternalPathsGuard, public_paths=public_paths)

    if force_client_host is not None:

        class _ForceClient(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                request.scope["client"] = (force_client_host, 0)
                return await call_next(request)

        app.add_middleware(_ForceClient)
    return app


def test_public_health_reaches_handler_from_external_ip():
    app = _build_app(force_client_host="8.8.8.8")
    client = TestClient(app)
    assert client.get("/health").status_code == 200


def test_public_chat_prefix_allows_subpath_from_external_ip():
    app = _build_app(force_client_host="8.8.8.8")
    client = TestClient(app)
    assert client.get("/chat/history").status_code == 200


def test_internal_agents_route_blocked_from_external_ip():
    app = _build_app(force_client_host="8.8.8.8")
    client = TestClient(app)
    resp = client.post("/agents/some-id/runs")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}


def test_internal_approvals_route_blocked_from_external_ip():
    app = _build_app(force_client_host="8.8.8.8")
    client = TestClient(app)
    resp = client.post("/approvals/abc/resolve")
    assert resp.status_code == 404


@pytest.mark.parametrize("loopback", ["127.0.0.1", "::1", "localhost"])
def test_loopback_passes_to_internal_routes(loopback: str):
    app = _build_app(force_client_host=loopback)
    client = TestClient(app)
    resp = client.post("/agents/x/runs")
    assert resp.status_code == 200


def test_public_paths_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTOS_PUBLIC_PATHS", "/alpha, /beta")
    assert _public_paths() == ("/alpha", "/beta")


def test_public_paths_env_default_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTOS_PUBLIC_PATHS", raising=False)
    assert _public_paths() == ("/health", "/chat")


def test_public_paths_env_empty_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("AGENTOS_PUBLIC_PATHS", "   ,  ")
    assert _public_paths() == ("/health", "/chat")


def test_add_internal_paths_guard_uses_env_when_no_arg(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("AGENTOS_PUBLIC_PATHS", "/only-this")
    app = FastAPI()

    @app.get("/only-this")
    def ok():
        return {"ok": True}

    @app.get("/secret")
    def secret():
        return {"ok": True}

    add_internal_paths_guard(app)

    class _ForceClient(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.scope["client"] = ("8.8.8.8", 0)
            return await call_next(request)

    app.add_middleware(_ForceClient)
    client = TestClient(app)
    assert client.get("/only-this").status_code == 200
    assert client.get("/secret").status_code == 404


def test_rbac_fail_fast_without_key(monkeypatch: pytest.MonkeyPatch):
    """Si `AGENTOS_AUTHORIZATION=true` y no hay JWT key, `_authorization_settings`
    falla loud antes de arrancar."""
    from core.agent_os_factory import _authorization_settings

    monkeypatch.setenv("AGENTOS_AUTHORIZATION", "true")
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="JWT_VERIFICATION_KEY"):
        _authorization_settings()


def test_rbac_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    from core.agent_os_factory import _authorization_settings

    monkeypatch.delenv("AGENTOS_AUTHORIZATION", raising=False)
    enabled, config = _authorization_settings()
    assert enabled is False
    assert config is None
