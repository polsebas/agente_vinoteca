"""Observabilidad: latencia, costo de tokens, KPIs y alertas."""

from observability.alerts import AlertManager, get_alert_manager, reset_alert_manager
from observability.cost_tracker import (
    CostTracker,
    calculate_cost_usd,
    get_cost_tracker,
    lookup_pricing,
    reset_cost_tracker,
)
from observability.metrics import (
    KPIMetricsCollector,
    get_kpi_collector,
    reset_kpi_collector,
)
from observability.tracer import LATENCY_ALERT_SECONDS, LatencyTracer, log_latency_alert


def reset_observability() -> None:
    reset_alert_manager()
    reset_cost_tracker()
    reset_kpi_collector()


__all__ = [
    "LATENCY_ALERT_SECONDS",
    "AlertManager",
    "CostTracker",
    "KPIMetricsCollector",
    "LatencyTracer",
    "calculate_cost_usd",
    "get_alert_manager",
    "get_cost_tracker",
    "get_kpi_collector",
    "log_latency_alert",
    "lookup_pricing",
    "reset_observability",
]
