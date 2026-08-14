"""Observabilidad: tracer, costos, KPIs, alertas y contratos de datasets."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from observability.alerts import AlertManager
from observability.cost_tracker import (
    CostTracker,
    calculate_cost_usd,
    extract_run_usage,
    lookup_pricing,
)
from observability.metrics import KPIMetricsCollector
from observability.tracer import LATENCY_ALERT_SECONDS, LatencyTracer
from schemas.agent_io import IntentClass
from schemas.evaluation import AdversarialExample, GoldenExample

DATASETS = Path(__file__).resolve().parent.parent / "datasets"


def test_latency_tracer_span_breakdown():
    tracer = LatencyTracer("sess-span")
    with tracer.trace_span("llm_reasoning"):
        total = sum(range(1000))
    with tracer.trace_span("tool_execution"):
        total += 1
    with tracer.trace_span("rag_retrieval"):
        total += 1
    assert total > 0
    summary = tracer.finish()
    assert summary["alerted"] is False
    assert summary["total_seconds"] < LATENCY_ALERT_SECONDS
    breakdown = summary["spans"]
    assert "llm_reasoning" in breakdown
    assert "tool_execution" in breakdown
    assert "rag_retrieval" in breakdown
    assert breakdown["llm_reasoning"] >= 0.0


def test_latency_tracer_alerta_si_supera_8s(monkeypatch):
    alerts = AlertManager()
    monkeypatch.setattr("observability.tracer.get_alert_manager", lambda: alerts)
    tracer = LatencyTracer("sess-slow")
    with tracer.trace_span("llm_reasoning"):
        pass
    tracer._start -= 8.2
    summary = tracer.finish()
    assert tracer.alerted is True
    assert summary["alerted"] is True
    assert summary["total_seconds"] > LATENCY_ALERT_SECONDS
    assert alerts.recent()
    assert alerts.recent()[-1]["category"] == "latency"


def test_cost_tracker_sonnet_haiku_gpt4o():
    tracker = CostTracker()
    sonnet = tracker.track_usage("s1", "claude-3-5-sonnet-20241022", 1_000_000, 1_000_000)
    assert sonnet == 18.0
    haiku = tracker.track_usage("s2", "claude-3-haiku", 1_000_000, 500_000)
    assert haiku == 2.8
    gpt = tracker.track_usage("s3", "gpt-4o", 2_000_000, 1_000_000)
    assert gpt == 15.0
    sess = tracker.get_session_cost("s1")
    assert sess["total_usd"] == 18.0
    assert sess["input_tokens"] == 1_000_000
    daily = tracker.get_daily_summary(datetime.now(UTC).date())
    assert daily["total_usd"] == 35.8
    assert daily["sessions"] == 3
    assert lookup_pricing("haiku") == (0.80, 4.00)
    assert calculate_cost_usd("gpt-4o", 0, 1_000_000) == 10.0


def test_extract_run_usage_desde_metrics():
    result = SimpleNamespace(
        model=SimpleNamespace(id="gpt-4o"),
        metrics={"input_tokens": 100, "output_tokens": 20},
    )
    model, inp, out = extract_run_usage(result)
    assert "gpt-4o" in model
    assert inp == 100
    assert out == 20


def test_kpi_resolution_conversion_stuck():
    kpis = KPIMetricsCollector()
    kpis.record_turn(
        "consult-1",
        intent=IntentClass.MARIDAJE,
        latency_ms=120,
        tokens=80,
        resolved=True,
    )
    kpis.record_turn(
        "consult-1",
        intent=IntentClass.PEDIDO_DELIVERY,
        latency_ms=200,
        tokens=40,
        order_created=True,
        resolved=True,
    )
    kpis.record_turn(
        "esc-1",
        intent=IntentClass.SOPORTE_RECLAMO,
        latency_ms=90,
        tokens=10,
        escalated=True,
        resolved=False,
    )
    kpis.record_turn(
        "stuck-1",
        intent=IntentClass.CONSULTA_STOCK_PRECIO,
        latency_ms=50,
        tokens=5,
        stuck=True,
        resolved=True,
    )
    dash = kpis.get_dashboard_metrics()
    assert dash["sessions"] == 3
    assert dash["turns"] == 4
    assert dash["conversion_rate"] == 1.0
    assert dash["resolution_rate"] == round(2 / 3, 4)
    assert dash["stuck_state_rate"] == 0.25
    assert dash["avg_latency_ms"] == round((120 + 200 + 90 + 50) / 4, 1)
    assert dash["avg_tokens_per_session"] == round(135 / 3, 1)
    kpis.record_hitl("consult-1", approved=True)
    assert kpis.get_dashboard_metrics()["orders"] == 1


def test_alert_manager_hooks():
    seen: list[str] = []
    mgr = AlertManager()
    mgr.add_hook(lambda level, cat, msg, meta: seen.append(cat))
    mgr.trigger_alert("error", "hitl", "rechazo", {"run_id": "x"})
    assert seen == ["hitl"]
    assert mgr.recent()[0]["level"] == "error"


def test_golden_dataset_exactamente_50():
    raw = json.loads((DATASETS / "golden_dataset.json").read_text(encoding="utf-8"))
    assert len(raw) == 50
    parsed = [GoldenExample.model_validate(item) for item in raw]
    ids = [item.id for item in parsed]
    assert len(set(ids)) == 50
    by_cat: dict[str, int] = {}
    by_profile: dict[str, int] = {}
    for item in parsed:
        by_cat[item.category] = by_cat.get(item.category, 0) + 1
        by_profile[item.client_profile] = by_profile.get(item.client_profile, 0) + 1
        assert 1 <= item.expected_layer <= 5
        assert item.expected_intent
        assert item.expected_tools
    assert by_cat["sommelier_coleccionista"] == 10
    assert by_cat["sommelier_curioso"] == 10
    assert by_cat["sommelier_ocasion"] == 10
    assert by_cat["orders_2pc"] == 10
    assert by_cat["inventory"] == 5
    assert by_cat["events"] == 5
    assert set(by_profile) == {"coleccionista", "curioso", "ocasion"}


def test_adversarial_dataset_minimo_25():
    raw = json.loads((DATASETS / "adversarial_dataset.json").read_text(encoding="utf-8"))
    assert len(raw) >= 25
    parsed = [AdversarialExample.model_validate(item) for item in raw]
    by_type: dict[str, int] = {}
    for item in parsed:
        by_type[item.attack_type.value] = by_type.get(item.attack_type.value, 0) + 1
    assert by_type["prompt_injection"] >= 8
    assert by_type["pii_extraction"] >= 6
    assert by_type["premature_charge"] >= 5
    stock_price = by_type.get("stock_hallucination", 0) + by_type.get("price_override", 0)
    assert stock_price >= 6
    injections = [p for p in parsed if p.attack_type.value == "prompt_injection"]
    assert all(p.expected_guardrail_block for p in injections)


@pytest.mark.asyncio
async def test_orchestrator_registra_kpis():
    from unittest.mock import AsyncMock

    from core.orchestrator import VinotecaOrchestrator
    from observability import reset_observability
    from observability.metrics import get_kpi_collector
    from schemas.agent_io import AgenteDestino, RouterOutput, SommelierResponse

    reset_observability()
    router = MagicMock()
    router.arun = AsyncMock(
        return_value=MagicMock(
            content=RouterOutput(
                intencion=IntentClass.MARIDAJE,
                confianza=0.95,
                agente_destino=AgenteDestino.SOMMELIER,
                razonamiento="test obs",
            ),
            metrics={"input_tokens": 10, "output_tokens": 5},
        )
    )
    sommelier = MagicMock()
    sommelier.arun = AsyncMock(
        return_value=MagicMock(
            content=SommelierResponse(
                mensaje_cliente="Malbec de Valle de Uco para el asado.",
                sugeridos=[],
            ),
            tools=[],
            metrics={"input_tokens": 20, "output_tokens": 15},
        )
    )
    orch = VinotecaOrchestrator(
        router=router,
        agents={
            "agente_sommelier": sommelier,
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

    resp = await orch.process_turn("sess-obs", "vino para asado")
    assert resp.agente == "agente_sommelier"
    dash = get_kpi_collector().get_dashboard_metrics()
    assert dash["turns"] >= 1
    assert dash["sessions"] >= 1
