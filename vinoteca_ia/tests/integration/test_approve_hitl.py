"""Integración de `/pedido/{run_id}/aprobar`.

Se mockea el Team para no depender de LLM ni Postgres: validamos solo el
contrato del endpoint. Reemplazamos `crear_router_team` por un fake que
retorna un `TeamRunOutput`-like con `requirements` pausados y verificamos:
- Sin token de aprobación, la respuesta es 401.
- Con token, cada `RunRequirement` recibe `confirm()` / `reject()`.
- `acontinue_run` se invoca con `run_response=<misma instancia>` (patrón
  documentado en el spike de Fase 0).
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeRequirement:
    def __init__(self, tool_name: str) -> None:
        self.tool_execution = SimpleNamespace(
            tool_name=tool_name,
            tool_call_id="call-1",
            tool_args={"session_id": "s1"},
            confirmed=None,
            confirmation_note=None,
            requires_confirmation=True,
        )
        self.needs_confirmation = True
        self.confirmed: bool | None = None
        self.note: str | None = None

    def confirm(self) -> None:
        self.confirmed = True
        self.tool_execution.confirmed = True

    def reject(self, note: str | None = None) -> None:
        self.confirmed = False
        self.note = note
        self.tool_execution.confirmed = False
        self.tool_execution.confirmation_note = note


def _build_app_with_mock_team(fake_team):
    patcher = patch("api.routes.approve.crear_router_team", return_value=fake_team)
    patcher.start()

    from api.deps import approval_rate_limiter
    from api.routes.approve import router

    app = FastAPI()
    app.include_router(router)

    async def _noop():
        return None

    app.dependency_overrides[approval_rate_limiter] = _noop
    return app, patcher


@pytest.fixture
def approval_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-approval-token"
    monkeypatch.setenv("APPROVAL_API_TOKEN", token)
    return token


def test_approve_requires_token():
    req1 = _FakeRequirement("crear_orden")
    fake_run = SimpleNamespace(requirements=[req1])
    fake_team = SimpleNamespace(
        aget_run_output=AsyncMock(return_value=fake_run),
        acontinue_run=AsyncMock(return_value=SimpleNamespace(content="ok")),
    )
    app, patcher = _build_app_with_mock_team(fake_team)
    try:
        client = TestClient(app)
        os.environ.pop("APPROVAL_API_TOKEN", None)
        resp = client.post(
            "/pedido/run-xyz/aprobar",
            json={"aprobar": True, "session_id": "s1"},
        )
        assert resp.status_code == 503, resp.text
    finally:
        patcher.stop()


def test_approve_confirms_requirements_and_resumes(approval_token):
    req1 = _FakeRequirement("crear_orden")
    fake_run = SimpleNamespace(requirements=[req1])
    resume_mock = AsyncMock(
        return_value=SimpleNamespace(
            content=SimpleNamespace(model_dump=lambda: {"mensaje_cliente": "listo"})
        )
    )
    fake_team = SimpleNamespace(
        aget_run_output=AsyncMock(return_value=fake_run),
        acontinue_run=resume_mock,
    )
    app, patcher = _build_app_with_mock_team(fake_team)
    try:
        client = TestClient(app)
        resp = client.post(
            "/pedido/run-xyz/aprobar",
            headers={"X-Approval-Token": approval_token},
            json={"aprobar": True, "session_id": "s1"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["aprobado"] is True
        assert req1.confirmed is True
        resume_mock.assert_awaited_once()
        kwargs = resume_mock.await_args.kwargs
        assert kwargs["run_response"] is fake_run
        assert kwargs["session_id"] == "s1"
        assert kwargs["stream"] is False
    finally:
        patcher.stop()


def test_approve_rejects_with_note(approval_token):
    req1 = _FakeRequirement("crear_orden")
    fake_run = SimpleNamespace(requirements=[req1])
    fake_team = SimpleNamespace(
        aget_run_output=AsyncMock(return_value=fake_run),
        acontinue_run=AsyncMock(
            return_value=SimpleNamespace(content=SimpleNamespace(model_dump=lambda: {}))
        ),
    )
    app, patcher = _build_app_with_mock_team(fake_team)
    try:
        client = TestClient(app)
        resp = client.post(
            "/pedido/run-xyz/aprobar",
            headers={"X-Approval-Token": approval_token},
            json={"aprobar": False, "session_id": "s1", "nota": "cliente rechazó"},
        )
        assert resp.status_code == 200, resp.text
        assert req1.confirmed is False
        assert req1.note == "cliente rechazó"
    finally:
        patcher.stop()


def test_approve_404_on_missing_run(approval_token):
    fake_team = SimpleNamespace(
        aget_run_output=AsyncMock(return_value=None),
        acontinue_run=AsyncMock(),
    )
    app, patcher = _build_app_with_mock_team(fake_team)
    try:
        client = TestClient(app)
        resp = client.post(
            "/pedido/run-nope/aprobar",
            headers={"X-Approval-Token": approval_token},
            json={"aprobar": True, "session_id": "s1"},
        )
        assert resp.status_code == 404
    finally:
        patcher.stop()
