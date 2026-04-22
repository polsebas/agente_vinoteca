"""Selección de modelo con fallback primario → secundario.

Usa la configuración de fallbacks nativa de Agno 2.x: cuando el modelo primario
falla (rate limit, 5xx, timeout), Agno reintenta automáticamente con los de
`fallback_models`. Así, si Claude cae, GPT-4o toma el turno sin perder la sesión.
"""

from __future__ import annotations

import os

from agno.models.anthropic import Claude
from agno.models.base import Model
from agno.models.openai import OpenAIChat


def get_resilient_model(temperature: float = 0.0) -> tuple[Model, list[Model]]:
    """Devuelve (modelo_primario, lista_fallbacks) para inyectar en Agent.

    Args:
        temperature: 0.0 para todo lo que retorne JSON estructurado o invoque
            tools. 0.7 solo para agentes de generación creativa (descripciones
            narrativas de vinos, por ejemplo).
    """
    primary_id = os.environ.get("LLM_PRIMARY", "claude-3-5-sonnet-20241022")
    fallback_id = os.environ.get("LLM_FALLBACK", "gpt-4o-mini")

    primary = Claude(id=primary_id, temperature=temperature)
    fallback = OpenAIChat(id=fallback_id, temperature=temperature)
    return primary, [fallback]
