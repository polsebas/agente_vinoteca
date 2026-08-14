"""Resiliencia PRAO: stuck state, circuit breaker a 5 pasos y fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.orchestrator import MAX_STEPS, VinotecaOrchestrator
from schemas.agent_io import AgenteDestino, IntentClass, RouterOutput, SommelierResponse


def _router_out() -> RouterOutput:
    return RouterOutput(
        intencion=IntentClass.MARIDAJE,
        confianza=0.95,
        agente_destino=AgenteDestino.SOMMELIER,
        razonamiento="test resiliencia",
    )


def _orch(especialista: MagicMock) -> VinotecaOrchestrator:
    router = MagicMock()
    router.arun = AsyncMock(return_value=MagicMock(content=_router_out()))
    orch = VinotecaOrchestrator(
        router=router,
        agents={
            "agente_sommelier": especialista,
            "agente_orders": MagicMock(),
            "agente_inventario": MagicMock(),
            "agente_support": MagicMock(),
            "agente_events": MagicMock(),
        },
        semantic_store=AsyncMock(),
        episodic_store=AsyncMock(),
    )
    orch._semantic.get_profile = AsyncMock(return_value=None)
    orch._episodic.append_interaction = AsyncMock(return_value=None)
    orch._episodic.get_pending_orders = AsyncMock(return_value=[])
    return orch


@pytest.mark.asyncio
async def test_stuck_state_corta_a_los_3_pasos_identicos():
    tool = MagicMock()
    tool.tool_name = "consultar_stock"
    tool.tool_args = {"vino_id": "x"}
    especialista = MagicMock()
    especialista.arun = AsyncMock(return_value=MagicMock(content=None, tools=[tool]))
    orch = _orch(especialista)
    resp = await orch.process_turn("sess-stuck", "stock de x")
    assert especialista.arun.await_count == 3
    assert resp.metadata is not None
    assert resp.metadata.get("circuit_breaker") == "true"
    assert "reformular" in resp.respuesta.lower() or "trabé" in resp.respuesta.lower()
    assert "Traceback" not in resp.respuesta


@pytest.mark.asyncio
async def test_circuit_breaker_maximo_5_pasos():
    especialista = MagicMock()
    especialista.arun = AsyncMock(return_value=MagicMock(content=None, tools=[]))
    orch = _orch(especialista)
    resp = await orch.process_turn("sess-cb", "asado")
    assert especialista.arun.await_count <= MAX_STEPS
    assert resp.metadata is not None
    assert int(resp.metadata["pasos"]) <= MAX_STEPS
    assert resp.metadata["circuit_breaker"] == "true"
    assert resp.finalizado is True


@pytest.mark.asyncio
async def test_fallback_sin_stacktrace_ante_errores():
    especialista = MagicMock()
    especialista.arun = AsyncMock(side_effect=RuntimeError("boom interno"))
    orch = _orch(especialista)
    resp = await orch.process_turn("sess-fb", "recomendame algo")
    assert resp.finalizado is True
    assert "Traceback" not in resp.respuesta
    assert "boom interno" not in resp.respuesta
    assert especialista.arun.await_count == 3


@pytest.mark.asyncio
async def test_turno_sano_no_dispara_breaker():
    especialista = MagicMock()
    especialista.arun = AsyncMock(
        return_value=MagicMock(
            content=SommelierResponse(
                mensaje_cliente="Malbec de Valle de Uco para el asado.",
                sugeridos=[],
            ),
            tools=[],
        )
    )
    orch = _orch(especialista)
    resp = await orch.process_turn("sess-ok", "vino para asado")
    assert resp.agente == "agente_sommelier"
    assert resp.finalizado is True
    assert especialista.arun.await_count == 1
    assert not (resp.metadata or {}).get("circuit_breaker")
