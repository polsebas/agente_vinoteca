"""Carga de constituciones y construcción uniforme de agentes Agno 2.5."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.base import Model

from core.model_provider import get_resilient_model

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_constitution(filename: str) -> str:
    """Lee `prompts/<filename>` en UTF-8. Falla loud si está vacío o no existe."""
    path = PROMPTS_DIR / filename
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Constitución vacía: {path}")
    return text


def make_agent(
    *,
    name: str,
    description: str,
    prompt_file: str,
    temperature: float,
    model: Model | None = None,
    tools: list[Any] | None = None,
    output_schema: type | None = None,
    **extra: Any,
) -> Agent:
    """Instancia un `Agent` Agno 2.5 con constitución, tools y contrato."""
    if model is None:
        primary, fallbacks = get_resilient_model(temperature=temperature)
        extra.setdefault("fallback_models", fallbacks)
    else:
        primary = model
    return Agent(
        name=name,
        model=primary,
        description=description,
        instructions=load_constitution(prompt_file),
        tools=tools or [],
        output_schema=output_schema,
        markdown=False,
        **extra,
    )
