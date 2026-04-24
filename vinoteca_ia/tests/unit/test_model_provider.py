"""Selección Anthropic vs OpenAI según prefijo del id en `LLM_*`."""

from __future__ import annotations

import pytest
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat

from core.model_provider import get_resilient_model


def test_primary_openai_when_id_not_claude(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PRIMARY", "gpt-4o-mini")
    monkeypatch.setenv("LLM_FALLBACK", "gpt-4o")
    primary, fallbacks = get_resilient_model(temperature=0.0)
    assert isinstance(primary, OpenAIChat)
    assert primary.id == "gpt-4o-mini"
    assert len(fallbacks) == 1
    assert isinstance(fallbacks[0], OpenAIChat)
    assert fallbacks[0].id == "gpt-4o"


def test_primary_claude_when_id_prefixed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PRIMARY", "claude-3-5-haiku-20241022")
    monkeypatch.setenv("LLM_FALLBACK", "gpt-4o-mini")
    primary, fallbacks = get_resilient_model(temperature=0.0)
    assert isinstance(primary, Claude)
    assert isinstance(fallbacks[0], OpenAIChat)
