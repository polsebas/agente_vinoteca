"""KPIs operativos del gateway (`GET /admin/metricas`)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.deps import admin_rate_limiter, require_admin_token
from observability.cost_tracker import get_cost_tracker
from observability.metrics import get_kpi_collector
from schemas.api import MetricasKPI
from storage.postgres import fetchrow

logger = logging.getLogger("vinoteca.api.admin")

router = APIRouter(tags=["admin"])


@router.get(
    "/admin/metricas",
    response_model=MetricasKPI,
    dependencies=[Depends(require_admin_token), Depends(admin_rate_limiter)],
)
async def metricas() -> MetricasKPI:
    """Combina KPIs in-process (telemetría) con totales SQL como fallback."""
    dash = get_kpi_collector().get_dashboard_metrics()
    daily = get_cost_tracker().get_daily_summary()
    sql = await _sql_kpis()

    # SQL es la fuente de verdad histórica; el collector cubre el proceso actual.
    sql_sessions = int(sql["conversaciones"])
    sessions = sql_sessions or int(dash["sessions"])
    pedidos = int(sql["pedidos"] or dash["orders"])
    conversion = float(sql["tasa_conversion"]) if sql_sessions else float(dash["conversion_rate"])
    escalation = float(sql["tasa_escalada"]) if sql_sessions else float(dash["escalation_rate"])
    latencia = float(dash["avg_latency_ms"] if dash["turns"] else sql["latencia_ms"])
    costo = float(daily["total_usd"] or sql["costo_usd"])
    return MetricasKPI(
        conversaciones_totales=sessions,
        pedidos_totales=pedidos,
        tasa_conversion=round(conversion, 4),
        tasa_escalada=round(escalation, 4),
        latencia_promedio_ms=round(latencia, 1),
        costo_tokens_estimado_usd=round(costo, 4),
        resolution_rate=float(dash["resolution_rate"]),
        stuck_state_rate=float(dash["stuck_state_rate"]),
        avg_tokens_per_session=float(dash["avg_tokens_per_session"]),
    )


async def _sql_kpis() -> dict[str, float]:
    try:
        conv_row = await fetchrow(
            """
            SELECT COUNT(DISTINCT session_id) AS n
            FROM log_inmutable
            WHERE session_id IS NOT NULL AND session_id <> ''
            """
        )
        pedidos_row = await fetchrow("SELECT COUNT(*) AS n FROM pedidos")
        pagadas_row = await fetchrow("SELECT COUNT(*) AS n FROM pedidos WHERE estado = 'pagada'")
        escaladas_row = await fetchrow(
            """
            SELECT COUNT(*) AS n FROM log_inmutable
            WHERE accion ILIKE '%escala%' OR accion ILIKE '%human%'
            """
        )
        lat_row = await fetchrow(
            """
            SELECT AVG((metadata->>'elapsed_ms')::float) AS avg_ms
            FROM log_inmutable
            WHERE metadata ? 'elapsed_ms'
            """
        )
    except Exception as exc:
        logger.warning("metricas SQL failopen: %s", exc)
        return {
            "conversaciones": 0,
            "pedidos": 0,
            "tasa_conversion": 0.0,
            "tasa_escalada": 0.0,
            "latencia_ms": 0.0,
            "costo_usd": 0.0,
        }

    conversaciones = int(conv_row["n"] or 0) if conv_row else 0
    pedidos = int(pedidos_row["n"] or 0) if pedidos_row else 0
    pagadas = int(pagadas_row["n"] or 0) if pagadas_row else 0
    escaladas = int(escaladas_row["n"] or 0) if escaladas_row else 0
    latencia = float(lat_row["avg_ms"] or 0.0) if lat_row and lat_row["avg_ms"] is not None else 0.0
    return {
        "conversaciones": conversaciones,
        "pedidos": pedidos,
        "tasa_conversion": (pagadas / conversaciones) if conversaciones else 0.0,
        "tasa_escalada": (escaladas / conversaciones) if conversaciones else 0.0,
        "latencia_ms": latencia,
        "costo_usd": round(conversaciones * 0.004, 4),
    }
