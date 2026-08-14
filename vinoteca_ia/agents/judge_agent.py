"""Juez de rúbrica binaria sobre una sesión (T=0.0, sin tools)."""

from __future__ import annotations

from agno.agent import Agent
from agno.models.base import Model

from agents.constitution import make_agent
from schemas.judge_rubric import JudgeEvaluationResult

JUDGE_TEMPERATURE = 0.0


def get_judge_agent(model: Model | None = None) -> Agent:
    """Factory Agno 2.5: evalúa input del cliente + output del agente."""
    return make_agent(
        name="agente_judge",
        description="Audita una sesión con rúbrica binaria de 6 criterios.",
        prompt_file="judge_v1.md",
        temperature=JUDGE_TEMPERATURE,
        model=model,
        output_schema=JudgeEvaluationResult,
        tool_call_limit=1,
    )


crear_agente_judge = get_judge_agent
