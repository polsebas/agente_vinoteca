"""Selección de modelo con fallback primario → secundario.

Los ids ``LLM_PRIMARY`` / ``LLM_FALLBACK`` que empiezan con ``claude-`` usan
Anthropic; el resto usa OpenAI (``gpt-*``, ``o4-*``, etc.).

Usa la configuración de fallbacks nativa de Agno 2.x: cuando el modelo primario
falla (rate limit, 5xx, timeout), Agno reintenta automáticamente con los de
`fallback_models`.
"""

from __future__ import annotations

import os

from agno.models.anthropic import Claude
from agno.models.base import Model
from agno.models.openai import OpenAIChat


def _make_model(model_id: str, *, temperature: float) -> Model:
    """Instancia Claude u OpenAIChat según el id (sin env extra).

    Convención: ids que empiezan con ``claude-`` → Anthropic; el resto → OpenAI
    (``gpt-*``, ``o3-*``, ``o4-*``, etc.).
    """
    if model_id.lower().startswith("claude-"):
        return Claude(id=model_id, temperature=temperature)
    return OpenAIChat(id=model_id, temperature=temperature)


def get_resilient_model(temperature: float = 0.0) -> tuple[Model, list[Model]]:
    """Devuelve (modelo_primario, lista_fallbacks) para inyectar en Agent.

    Args:
        temperature: 0.0 para todo lo que retorne JSON estructurado o invoque
            tools. 0.7 solo para agentes de generación creativa (descripciones
            narrativas de vinos, por ejemplo).
    """
    primary_id = os.environ.get("LLM_PRIMARY", "claude-3-5-sonnet-20241022")
    fallback_id = os.environ.get("LLM_FALLBACK", "gpt-4o-mini")

    primary = _make_model(primary_id, temperature=temperature)
    fallback = _make_model(fallback_id, temperature=temperature)
    return primary, [fallback]
