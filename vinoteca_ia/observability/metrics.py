"""KPIs de negocio y técnicos para el dashboard `/admin/metricas`."""

from __future__ import annotations

from typing import Any

from schemas.agent_io import IntentClass

_CONSULTATIVE = {
    IntentClass.RECOMENDACION_OCASION,
    IntentClass.RECOMENDACION_REGALO,
    IntentClass.MARIDAJE,
    IntentClass.RECOMENDACION,
}


class KPIMetricsCollector:
    """Contadores in-process: resolución, conversión, latencia y stuck state."""

    def __init__(self) -> None:
        self.turns = 0
        self.stuck_turns = 0
        self.latency_ms_sum = 0.0
        self._sessions: set[str] = set()
        self._consult_sessions: set[str] = set()
        self._order_sessions: set[str] = set()
        self._escalated_sessions: set[str] = set()
        self._tokens: dict[str, int] = {}
        self._resolved_without_human: set[str] = set()

    def record_turn(
        self,
        session_id: str,
        *,
        intent: IntentClass | str | None = None,
        latency_ms: float = 0.0,
        tokens: int = 0,
        stuck: bool = False,
        escalated: bool = False,
        order_created: bool = False,
        resolved: bool = True,
    ) -> None:
        self.turns += 1
        self.latency_ms_sum += max(0.0, latency_ms)
        self._sessions.add(session_id)
        self._tokens[session_id] = self._tokens.get(session_id, 0) + tokens
        if stuck:
            self.stuck_turns += 1
        if escalated:
            self._escalated_sessions.add(session_id)
        elif resolved:
            self._resolved_without_human.add(session_id)
        intent_enum = _coerce_intent(intent)
        if intent_enum in _CONSULTATIVE:
            self._consult_sessions.add(session_id)
        if order_created:
            self._order_sessions.add(session_id)

    def record_hitl(self, session_id: str, *, approved: bool) -> None:
        """Aprobación humana de 2PC: cuenta como orden o como no-resolución."""
        self._sessions.add(session_id)
        if approved:
            self._order_sessions.add(session_id)
        else:
            self._escalated_sessions.add(session_id)

    def get_dashboard_metrics(self) -> dict[str, Any]:
        sessions = len(self._sessions)
        consult = len(self._consult_sessions)
        converted = len(self._consult_sessions & self._order_sessions)
        escalated = len(self._escalated_sessions)
        resolved = len(self._resolved_without_human - self._escalated_sessions)
        token_total = sum(self._tokens.values())
        return {
            "sessions": sessions,
            "turns": self.turns,
            "orders": len(self._order_sessions),
            "resolution_rate": round((resolved / sessions) if sessions else 0.0, 4),
            "conversion_rate": round((converted / consult) if consult else 0.0, 4),
            "avg_latency_ms": round(
                (self.latency_ms_sum / self.turns) if self.turns else 0.0,
                1,
            ),
            "stuck_state_rate": round(
                (self.stuck_turns / self.turns) if self.turns else 0.0,
                4,
            ),
            "avg_tokens_per_session": round(
                (token_total / sessions) if sessions else 0.0,
                1,
            ),
            "escalation_rate": round((escalated / sessions) if sessions else 0.0, 4),
        }

    def reset(self) -> None:
        self.turns = 0
        self.stuck_turns = 0
        self.latency_ms_sum = 0.0
        self._sessions.clear()
        self._consult_sessions.clear()
        self._order_sessions.clear()
        self._escalated_sessions.clear()
        self._tokens.clear()
        self._resolved_without_human.clear()


def _coerce_intent(intent: IntentClass | str | None) -> IntentClass | None:
    if intent is None:
        return None
    if isinstance(intent, IntentClass):
        return intent
    try:
        return IntentClass(intent)
    except ValueError:
        return None


_COLLECTOR: KPIMetricsCollector | None = None


def get_kpi_collector() -> KPIMetricsCollector:
    global _COLLECTOR
    if _COLLECTOR is None:
        _COLLECTOR = KPIMetricsCollector()
    return _COLLECTOR


def reset_kpi_collector() -> None:
    global _COLLECTOR
    if _COLLECTOR is not None:
        _COLLECTOR.reset()
    _COLLECTOR = KPIMetricsCollector()
