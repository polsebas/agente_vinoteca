"""Trazas de latencia por turno y alerta si el turno supera 8s."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from observability.alerts import get_alert_manager

LATENCY_ALERT_SECONDS = 8.0


class LatencyTracer:
    """Mide el turno completo y spans (llm_reasoning, tool_execution, rag)."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._start = time.perf_counter()
        self._spans: list[dict[str, Any]] = []
        self.alerted = False
        self.total_seconds = 0.0

    @contextmanager
    def trace_span(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self._spans.append({"name": name, "seconds": round(elapsed, 4)})

    def finish(self) -> dict[str, Any]:
        """Cierra el turno. Si total > 8s dispara alerta de latencia."""
        self.total_seconds = time.perf_counter() - self._start
        breakdown = self.span_breakdown()
        if self.total_seconds > LATENCY_ALERT_SECONDS:
            self.alerted = True
            log_latency_alert(self.session_id, self.total_seconds, breakdown)
        return {
            "session_id": self.session_id,
            "total_seconds": round(self.total_seconds, 4),
            "total_ms": round(self.total_seconds * 1000, 1),
            "spans": breakdown,
            "alerted": self.alerted,
        }

    def span_breakdown(self) -> dict[str, float]:
        aggregated: dict[str, float] = {}
        for span in self._spans:
            aggregated[span["name"]] = round(
                aggregated.get(span["name"], 0.0) + float(span["seconds"]),
                4,
            )
        return aggregated


def log_latency_alert(
    session_id: str,
    total_seconds: float,
    span_breakdown: dict[str, float],
) -> None:
    get_alert_manager().trigger_alert(
        level="warning",
        category="latency",
        message=(
            f"Turno {session_id} tardó {total_seconds:.2f}s (umbral {LATENCY_ALERT_SECONDS:.1f}s)"
        ),
        metadata={
            "session_id": session_id,
            "total_seconds": round(total_seconds, 4),
            "span_breakdown": span_breakdown,
        },
    )
