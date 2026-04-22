"""Job nocturno de auditoría.

Uso típico desde cron (3:00 AM ART):

    0 6 * * * cd /app && .venv/bin/python -m jobs.nightly_audit

O disparado por el scheduler de AgentOS si lo activás (`scheduler=True`).

La ventana (`horas_atras`) la fija el job, no el LLM: llamamos directamente a
`fetch_audit_runs_window`. El agente recibe el JSON ya filtrado; su trabajo es
solo juzgar e invocar `guardar_hallazgo`. Al cerrar, el `AuditReport` se arma
**desde DB** (fuente de verdad) para que conteos y listas concuerden con lo
efectivamente persistido, aunque el LLM produzca su propio draft.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime

from agents.auditor_agent import crear_agente_auditor
from schemas.audit import AuditCategoria, AuditFinding, AuditReport, AuditSeverity
from storage.postgres import close_pool, fetch_all, get_pool
from tools.audit.fetch_runs import fetch_audit_runs_window

logger = logging.getLogger("vinoteca.auditor")


async def _ensure_table() -> None:
    """Crea `audit_findings` si no existe. Idempotente.

    La columna `dedupe_hash` con índice único garantiza que `guardar_hallazgo`
    no duplique filas aunque el LLM repita la evaluación.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_findings (
                finding_id        UUID PRIMARY KEY,
                run_id            TEXT NOT NULL,
                session_id        TEXT,
                agente_nombre     TEXT NOT NULL,
                severidad         TEXT NOT NULL,
                categoria         TEXT NOT NULL,
                descripcion       TEXT NOT NULL,
                evidencia         TEXT NOT NULL,
                recomendacion     TEXT NOT NULL,
                detectado_en      TIMESTAMPTZ NOT NULL,
                dedupe_hash       TEXT
            )
            """
        )
        await conn.execute(
            "ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS dedupe_hash TEXT"
        )
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_findings_dedupe "
            "ON audit_findings(dedupe_hash) WHERE dedupe_hash IS NOT NULL"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_findings_run ON audit_findings(run_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_findings_sev ON audit_findings(severidad)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_findings_detectado "
            "ON audit_findings(detectado_en)"
        )


async def correr_auditor(horas_atras: int = 24) -> AuditReport:
    """Ejecuta una pasada completa del auditor y devuelve el reporte."""
    await _ensure_table()

    runs_response = await fetch_audit_runs_window(horas_atras=horas_atras, limite=200)

    auditor = crear_agente_auditor()
    prompt = _build_auditor_prompt(runs_response.model_dump_json(), horas_atras)

    result = await auditor.arun(
        input=prompt,
        session_id=f"audit-{datetime.now(UTC).date().isoformat()}",
        stream=False,
    )

    resumen = _extraer_resumen(result)
    findings_db = await _leer_findings_ventana(
        runs_response.ventana_desde,
    )

    return AuditReport(
        ventana_desde=runs_response.ventana_desde,
        ventana_hasta=runs_response.ventana_hasta,
        runs_evaluados=runs_response.runs_devueltos,
        findings=findings_db,
        resumen_ejecutivo=resumen,
    )


def _build_auditor_prompt(runs_json: str, horas_atras: int) -> str:
    return (
        f"Auditá los runs de las últimas {horas_atras} horas listados a "
        "continuación. Por cada violación concreta de la constitución "
        "correspondiente, invocá `guardar_hallazgo` con evidencia textual. "
        "No invoques `listar_runs_auditables`: ya tenés la ventana filtrada. "
        "Al final, devolvé un `AuditReport` con un `resumen_ejecutivo` breve y "
        "operativo.\n\nRUNS JSON:\n" + runs_json
    )


def _extraer_resumen(result) -> str:
    """Extrae `resumen_ejecutivo` del output del auditor con fallback seguro."""
    content = getattr(result, "content", None)
    if content is None:
        return "Auditoría completada. Revisar findings en DB."
    if isinstance(content, AuditReport):
        return content.resumen_ejecutivo
    if hasattr(content, "resumen_ejecutivo"):
        return getattr(content, "resumen_ejecutivo") or ""
    if isinstance(content, dict) and "resumen_ejecutivo" in content:
        return str(content["resumen_ejecutivo"])
    return "Auditoría completada. Revisar findings en DB."


async def _leer_findings_ventana(desde: datetime) -> list[AuditFinding]:
    """Relee todos los findings detectados a partir de `desde`."""
    rows = await fetch_all(
        """
        SELECT finding_id, run_id, session_id, agente_nombre, severidad,
               categoria, descripcion, evidencia, recomendacion, detectado_en
        FROM audit_findings
        WHERE detectado_en >= $1
        ORDER BY detectado_en ASC
        """,
        desde,
    )
    findings: list[AuditFinding] = []
    for row in rows:
        findings.append(
            AuditFinding(
                finding_id=row["finding_id"],
                run_id=row["run_id"],
                session_id=row["session_id"],
                agente_nombre=row["agente_nombre"],
                severidad=AuditSeverity(row["severidad"]),
                categoria=AuditCategoria(row["categoria"]),
                descripcion=row["descripcion"],
                evidencia=row["evidencia"],
                recomendacion=row["recomendacion"],
                detectado_en=row["detectado_en"],
            )
        )
    return findings


async def _main(horas: int) -> int:
    try:
        report = await correr_auditor(horas_atras=horas)
    except Exception as exc:
        logger.exception("Falló la auditoría: %s", exc)
        return 1
    finally:
        await close_pool()

    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    horas_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    sys.exit(asyncio.run(_main(horas_arg)))
