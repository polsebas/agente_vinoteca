"""Costos de tokens por sesión y bucket diario, con lookup de precios."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any

# USD por millón de tokens: (input, output).
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3.5-sonnet": (3.00, 15.00),
    "claude-3-haiku": (0.80, 4.00),
    "claude-3.5-haiku": (0.80, 4.00),
    "haiku": (0.80, 4.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}

_DEFAULT_MODEL = "claude-3-5-sonnet"


def lookup_pricing(model_name: str) -> tuple[float, float]:
    """Resuelve tarifas. Default: Sonnet 3.5 ($3 / $15 por M)."""
    key = (model_name or "").lower().strip()
    for prefix, rates in sorted(MODEL_PRICING.items(), key=lambda item: -len(item[0])):
        if prefix in key:
            return rates
    return MODEL_PRICING["claude-3-5-sonnet"]


def calculate_cost_usd(model_name: str, input_tokens: int, output_tokens: int) -> float:
    inp_rate, out_rate = lookup_pricing(model_name)
    cost = (input_tokens / 1_000_000) * inp_rate + (output_tokens / 1_000_000) * out_rate
    return round(cost, 8)


def extract_run_usage(result: Any) -> tuple[str, int, int]:
    """Lee tokens de un RunOutput de Agno. (0, 0) si no hay métricas."""
    model = os.environ.get("LLM_PRIMARY", _DEFAULT_MODEL)
    raw_model = getattr(result, "model", None)
    if raw_model is not None:
        model = getattr(raw_model, "id", None) or getattr(raw_model, "name", None) or str(raw_model)
    metrics = getattr(result, "metrics", None)
    if metrics is None:
        metrics = getattr(result, "usage", None)
    input_tokens = 0
    output_tokens = 0
    if isinstance(metrics, dict):
        input_tokens = int(metrics.get("input_tokens") or metrics.get("prompt_tokens") or 0)
        output_tokens = int(metrics.get("output_tokens") or metrics.get("completion_tokens") or 0)
    elif metrics is not None:
        input_tokens = int(
            getattr(metrics, "input_tokens", 0) or getattr(metrics, "prompt_tokens", 0) or 0
        )
        output_tokens = int(
            getattr(metrics, "output_tokens", 0) or getattr(metrics, "completion_tokens", 0) or 0
        )
    return str(model), input_tokens, output_tokens


class CostTracker:
    """Acumula costo USD por sesión y por día UTC."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._daily: dict[date, dict[str, Any]] = {}

    def track_usage(
        self,
        session_id: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        cost = calculate_cost_usd(model_name, input_tokens, output_tokens)
        sess = self._sessions.setdefault(
            session_id,
            {
                "session_id": session_id,
                "total_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "calls": 0,
                "models": [],
            },
        )
        sess["total_usd"] = round(float(sess["total_usd"]) + cost, 8)
        sess["input_tokens"] = int(sess["input_tokens"]) + input_tokens
        sess["output_tokens"] = int(sess["output_tokens"]) + output_tokens
        sess["calls"] = int(sess["calls"]) + 1
        models: list[str] = list(sess["models"])
        if model_name not in models:
            models.append(model_name)
        sess["models"] = models

        dia = datetime.now(UTC).date()
        bucket = self._daily.setdefault(
            dia,
            {
                "date": dia.isoformat(),
                "total_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "calls": 0,
                "sessions": set(),
            },
        )
        bucket["total_usd"] = round(float(bucket["total_usd"]) + cost, 8)
        bucket["input_tokens"] = int(bucket["input_tokens"]) + input_tokens
        bucket["output_tokens"] = int(bucket["output_tokens"]) + output_tokens
        bucket["calls"] = int(bucket["calls"]) + 1
        sessions: set[str] = bucket["sessions"]
        sessions.add(session_id)
        return cost

    def get_session_cost(self, session_id: str) -> dict[str, Any]:
        sess = self._sessions.get(session_id)
        if sess is None:
            return {
                "session_id": session_id,
                "total_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "calls": 0,
                "models": [],
            }
        return {
            "session_id": sess["session_id"],
            "total_usd": sess["total_usd"],
            "input_tokens": sess["input_tokens"],
            "output_tokens": sess["output_tokens"],
            "calls": sess["calls"],
            "models": list(sess["models"]),
        }

    def get_daily_summary(self, target: date | None = None) -> dict[str, Any]:
        dia = target or datetime.now(UTC).date()
        bucket = self._daily.get(dia)
        if bucket is None:
            return {
                "date": dia.isoformat(),
                "total_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "calls": 0,
                "sessions": 0,
            }
        return {
            "date": bucket["date"],
            "total_usd": bucket["total_usd"],
            "input_tokens": bucket["input_tokens"],
            "output_tokens": bucket["output_tokens"],
            "calls": bucket["calls"],
            "sessions": len(bucket["sessions"]),
        }

    def reset(self) -> None:
        self._sessions.clear()
        self._daily.clear()


_TRACKER: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    global _TRACKER
    if _TRACKER is None:
        _TRACKER = CostTracker()
    return _TRACKER


def reset_cost_tracker() -> None:
    global _TRACKER
    if _TRACKER is not None:
        _TRACKER.reset()
    _TRACKER = CostTracker()
