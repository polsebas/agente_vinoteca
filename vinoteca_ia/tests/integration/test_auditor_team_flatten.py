"""Integración del auditor: aplanado de `TeamSession.member_responses`.

Mockeamos `get_agno_db()` para devolver sesiones sintéticas y validamos que
`fetch_audit_runs_window`:
- Incluye runs de `SessionType.AGENT` cuando el `agent_id` está en la lista.
- Aplana los `RunOutput` dentro de `TeamRunOutput.member_responses`, asociando
  `agente_nombre` a `run.agent_id` del hijo.
- Respeta el flag `truncado` cuando se alcanza el límite.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _agent_session(agent_id: str, runs: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=f"agent-sess-{agent_id}",
        agent_id=agent_id,
        user_id="u1",
        runs=runs,
    )


def _team_session(member_responses: list[dict]) -> SimpleNamespace:
    team_run = {"run_id": "team-run-1", "member_responses": member_responses}
    return SimpleNamespace(
        session_id="team-sess-1",
        user_id="u1",
        runs=[team_run],
    )


def _mock_db(agent_sessions, team_sessions):
    def _get_sessions(*, session_type, **_kwargs):
        from agno.db.base import SessionType

        if session_type == SessionType.AGENT:
            return agent_sessions
        if session_type == SessionType.TEAM:
            return team_sessions
        return []

    return SimpleNamespace(get_sessions=_get_sessions)


@pytest.mark.asyncio
async def test_fetch_window_flattens_team_members():
    from tools.audit.fetch_runs import fetch_audit_runs_window

    agent_sessions = [
        _agent_session(
            "agente_sommelier",
            [{"run_id": "r-agent-1", "content": "un tinto joven", "tools": []}],
        ),
        _agent_session(
            "agente_router",
            [{"run_id": "r-router-noise", "content": "ignorar", "tools": []}],
        ),
    ]
    team_sessions = [
        _team_session(
            [
                {
                    "run_id": "r-member-1",
                    "agent_id": "agente_orders",
                    "content": "orden preparada",
                    "tools": [],
                },
                {
                    "run_id": "r-member-2",
                    "agent_id": "agente_sommelier",
                    "content": "reco",
                    "tools": [],
                },
                {
                    "run_id": "r-member-skip",
                    "agent_id": "agente_router",
                    "content": "routing",
                    "tools": [],
                },
            ]
        )
    ]

    with patch(
        "tools.audit.fetch_runs.get_agno_db",
        return_value=_mock_db(agent_sessions, team_sessions),
    ):
        resp = await fetch_audit_runs_window(horas_atras=24, limite=50)

    agent_names = [r.agente_nombre for r in resp.runs]
    assert "agente_sommelier" in agent_names
    assert "agente_orders" in agent_names
    assert "agente_router" not in agent_names
    assert resp.runs_devueltos == len(resp.runs)
    assert resp.truncado is False

    orders_run = next(r for r in resp.runs if r.run_id == "r-member-1")
    assert orders_run.session_id == "team-sess-1"
    assert orders_run.agente_nombre == "agente_orders"


@pytest.mark.asyncio
async def test_fetch_window_marks_truncado_when_limit_reached():
    from tools.audit.fetch_runs import fetch_audit_runs_window

    many_runs = [
        {"run_id": f"r-{i}", "content": "x", "tools": []} for i in range(10)
    ]
    agent_sessions = [_agent_session("agente_sommelier", many_runs)]

    with patch(
        "tools.audit.fetch_runs.get_agno_db",
        return_value=_mock_db(agent_sessions, []),
    ):
        resp = await fetch_audit_runs_window(horas_atras=24, limite=3)

    assert resp.runs_devueltos == 3
    assert resp.truncado is True
