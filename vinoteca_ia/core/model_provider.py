"""
Proveedor de modelos LLM con fallback automático.
Principal: Claude (Anthropic). Fallback: GPT-4o (OpenAI).
"""

from __future__ import annotations

import os

from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat


def get_primary_model(temperature: float = 0.0):
    """Modelo principal Claude para uso creativo o general."""
    return Claude(
        id=os.environ.get("LLM_PRIMARY", "claude-3-5-sonnet-20241022"),
        temperature=temperature,
        max_tokens=2048,
    )


def get_fast_model():
    """Modelo rápido y económico para clasificación y tool calls."""
    return Claude(
        id="claude-3-5-haiku-20241022",
        temperature=0.0,
        max_tokens=512,
    )


def get_fallback_model(temperature: float = 0.0):
    """Fallback a GPT-4o-mini si Claude no está disponible."""
    return OpenAIChat(
        id=os.environ.get("LLM_FALLBACK", "gpt-4o-mini"),
        temperature=temperature,
        max_tokens=2048,
    )
