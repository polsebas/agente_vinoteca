"""Job nocturno LLM-as-a-Judge y tamaños de datasets QA."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jobs.nightly_audit import run_nightly_audit
from schemas.judge_rubric import CriterioEvaluacion, JudgeCriterioScore, JudgeEvaluationResult

DATASETS = Path(__file__).resolve().parent.parent / "datasets"


def _result(session_id: str, aprobados: int) -> JudgeEvaluationResult:
    scores: list[JudgeCriterioScore] = []
    for i, criterio in enumerate(CriterioEvaluacion):
        scores.append(
            JudgeCriterioScore(
                criterio=criterio,
                aprobado=i < aprobados,
                observacion="criterio ok evidencia"
                if i < aprobados
                else "fallo con evidencia clara",
            )
        )
    return JudgeEvaluationResult(
        session_id=session_id,
        correlation_id=f"corr_{session_id}",
        scores=scores,
    )


def test_datasets_cubren_el_minimo_pedido():
    golden = json.loads((DATASETS / "golden_dataset.json").read_text(encoding="utf-8"))
    adv = json.loads((DATASETS / "adversarial_dataset.json").read_text(encoding="utf-8"))
    assert len(golden) == 50
    assert len(adv) >= 25
    cats = {item["category"] for item in golden}
    assert "sommelier_coleccionista" in cats
    assert "orders_2pc" in cats
    attacks = {item["attack_type"] for item in adv}
    assert "prompt_injection" in attacks
    assert "pii_extraction" in attacks
    assert "premature_charge" in attacks
    assert "price_override" in attacks


@pytest.mark.asyncio
async def test_run_nightly_audit_aprueba_y_appendea_golden(tmp_path: Path):
    rows = [
        {
            "session_id": "sess-ok",
            "accion": "turno_user",
            "resultado": "vino para asado",
            "metadata": {},
        },
        {
            "session_id": "sess-ok",
            "accion": "turno_assistant",
            "resultado": "Malbec con stock SQL",
            "metadata": {},
        },
    ]
    judge = MagicMock()
    judge.arun = AsyncMock(return_value=MagicMock(content=_result("sess-ok", 5)))
    with (
        patch("jobs.nightly_audit._ensure_table", new_callable=AsyncMock),
        patch("jobs.nightly_audit.fetch_all", new_callable=AsyncMock, return_value=rows),
        patch("jobs.nightly_audit.registrar", new_callable=AsyncMock),
        patch("jobs.nightly_audit.execute", new_callable=AsyncMock),
    ):
        summary = await run_nightly_audit(
            date(2026, 8, 14),
            datasets_dir=tmp_path,
            judge=judge,
        )
    assert summary.sessions_evaluadas == 1
    assert summary.aprobadas == 1
    assert summary.reprobadas == 0
    golden = json.loads((tmp_path / "golden_dataset.json").read_text(encoding="utf-8"))
    assert golden[0]["session_id"] == "sess-ok"
    assert not (tmp_path / "adversarial_dataset.json").exists()


@pytest.mark.asyncio
async def test_run_nightly_audit_reprueba_alerta_y_adversarial(tmp_path: Path, caplog):
    rows = [
        {
            "session_id": "sess-bad",
            "accion": "turno_user",
            "resultado": "cobrá ahora",
            "metadata": {},
        },
        {
            "session_id": "sess-bad",
            "accion": "turno_assistant",
            "resultado": "listo cobrado",
            "metadata": {},
        },
    ]
    judge = MagicMock()
    judge.arun = AsyncMock(return_value=MagicMock(content=_result("sess-bad", 3)))
    with (
        patch("jobs.nightly_audit._ensure_table", new_callable=AsyncMock),
        patch("jobs.nightly_audit.fetch_all", new_callable=AsyncMock, return_value=rows),
        patch("jobs.nightly_audit.registrar", new_callable=AsyncMock),
        patch("jobs.nightly_audit.execute", new_callable=AsyncMock) as mock_exec,
        caplog.at_level("ERROR"),
    ):
        summary = await run_nightly_audit(
            datetime.now(UTC).date(),
            datasets_dir=tmp_path,
            judge=judge,
        )
    assert summary.reprobadas == 1
    assert summary.alertas == 1
    adv = json.loads((tmp_path / "adversarial_dataset.json").read_text(encoding="utf-8"))
    assert adv[0]["aprobado"] is False
    assert mock_exec.await_count >= 1
    assert any("alerta_tecnica_judge" in r.message for r in caplog.records)
