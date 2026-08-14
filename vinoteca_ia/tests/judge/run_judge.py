"""CLI para ejecutar el Judge sobre sesiones o entradas de dataset.

Uso:
    uv run python -m tests.judge.run_judge --session sess-1
    uv run python -m tests.judge.run_judge --dataset golden
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from agents.judge_agent import get_judge_agent
from jobs.nightly_audit import _evaluar_sesion
from schemas.judge_rubric import JudgeEvaluationResult

DATASETS = Path(__file__).resolve().parent.parent / "datasets"


async def run_judge(
    *,
    session_id: str | None = None,
    dataset: str | None = None,
    entry_id: str | None = None,
) -> list[JudgeEvaluationResult]:
    """Evalúa una sesión (vía dataset) o todas las entradas de un JSON."""
    judge = get_judge_agent()
    items: list[dict] = []
    if dataset:
        path = DATASETS / f"{dataset}_dataset.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else list(raw.get("items", []))
        if entry_id:
            items = [i for i in items if i.get("id") == entry_id]
        if session_id:
            items = [i for i in items if i.get("session_id") == session_id]
    elif session_id:
        items = [{"id": session_id, "session_id": session_id, "input": "", "output": ""}]
    else:
        raise ValueError("Indicá --session o --dataset.")

    results: list[JudgeEvaluationResult] = []
    for item in items:
        sid = str(item.get("session_id") or item.get("id") or "anon")
        result = await _evaluar_sesion(
            judge,
            session_id=sid,
            user_in=str(item.get("input") or ""),
            agent_out=str(item.get("output") or ""),
            correlation_id=f"corr_judge_{sid}",
        )
        results.append(result)
    return results


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Runner LLM-as-a-Judge")
    parser.add_argument("--session", default=None, help="session_id a evaluar")
    parser.add_argument(
        "--dataset",
        default=None,
        choices=["golden", "adversarial"],
        help="Dataset JSON en tests/datasets/",
    )
    parser.add_argument("--entry", default=None, help="id de entrada dentro del dataset")
    return parser.parse_args(argv)


async def _main(argv: list[str]) -> int:
    args = _parse_args(argv)
    results = await run_judge(
        session_id=args.session,
        dataset=args.dataset,
        entry_id=args.entry,
    )
    payload = [r.model_dump(mode="json") for r in results]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(r.aprobado for r in results) or not results else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
