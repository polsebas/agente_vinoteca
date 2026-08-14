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
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from agents.auditor_agent import crear_agente_auditor
from agents.judge_agent import get_judge_agent
from schemas.audit import (
    AuditCategoria,
    AuditFinding,
    AuditReport,
    AuditSeverity,
    AuditSummary,
)
from schemas.judge_rubric import CriterioEvaluacion, JudgeCriterioScore, JudgeEvaluationResult
from storage.immutable_log import registrar
from storage.postgres import close_pool, execute, fetch_all, get_pool
from tools.audit.fetch_runs import fetch_audit_runs_window

_DEFAULT_DATASETS = Path(__file__).resolve().parent.parent / "tests" / "datasets"

_CRITERIO_A_CATEGORIA: dict[CriterioEvaluacion, AuditCategoria] = {
    CriterioEvaluacion.CONSULTO_STOCK_PREVIO: AuditCategoria.TOOL_OMITIDA,
    CriterioEvaluacion.RESPETO_TWO_PHASE_COMMIT: AuditCategoria.DOSFC_VIOLADO,
    CriterioEvaluacion.PERTINENCIA_PERFIL: AuditCategoria.RESPUESTA_INUTIL,
    CriterioEvaluacion.SIN_ALUCINACION_PRECIO_STOCK: AuditCategoria.HALUCINACION,
    CriterioEvaluacion.ESCALADA_CORRECTA: AuditCategoria.ESCALADA_TARDIA,
    CriterioEvaluacion.TONO_Y_CAPA_ADECUADOS: AuditCategoria.TONO_INAPROPIADO,
}

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
        await conn.execute("ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS dedupe_hash TEXT")
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


async def run_nightly_audit(
    target_date: date | None = None,
    *,
    datasets_dir: Path | None = None,
    judge=None,
) -> AuditSummary:
    """Evalúa las sesiones del día con JudgeAgent (rúbrica 6 criterios).

    Aprueba con ≥ 5/6: se appendea a `golden_dataset.json`.
    Reprueba: alerta técnica + `adversarial_dataset.json`.
    """
    await _ensure_table()
    dia = target_date or datetime.now(UTC).date()
    inicio = datetime.combine(dia, time.min, tzinfo=UTC)
    ds_dir = datasets_dir or _DEFAULT_DATASETS
    agente = judge or get_judge_agent()

    sesiones = await _cargar_sesiones(dia)
    aprobadas = 0
    reprobadas = 0
    alertas = 0
    ids: list[str] = []

    for session_id, user_in, agent_out, correlation_id in sesiones:
        result = await _evaluar_sesion(
            agente,
            session_id=session_id,
            user_in=user_in,
            agent_out=agent_out,
            correlation_id=correlation_id,
        )
        ids.append(session_id)
        await _persistir_evaluacion(result)
        entry = {
            "id": f"judge-{dia.isoformat()}-{session_id}",
            "session_id": session_id,
            "input": user_in,
            "output": agent_out,
            "puntos_totales": result.puntos_totales,
            "aprobado": result.aprobado,
            "categoria_fallo": result.categoria_fallo,
        }
        if result.aprobado:
            aprobadas += 1
            _append_dataset(ds_dir / "golden_dataset.json", entry)
        else:
            reprobadas += 1
            alertas += 1
            _append_dataset(ds_dir / "adversarial_dataset.json", entry)
            _alertar_tecnica(result)

    return AuditSummary(
        fecha=inicio,
        sessions_evaluadas=len(sesiones),
        aprobadas=aprobadas,
        reprobadas=reprobadas,
        alertas=alertas,
        resultados=ids,
    )


async def _cargar_sesiones(dia: date) -> list[tuple[str, str, str, str]]:
    """Agrupa turnos del día desde `log_inmutable` y, si falta, runs Agno."""
    inicio = datetime.combine(dia, time.min, tzinfo=UTC)
    fin = inicio + timedelta(days=1)
    grouped: dict[str, list[tuple[str, str]]] = {}
    try:
        rows = await fetch_all(
            """
            SELECT session_id, accion, resultado, metadata
            FROM log_inmutable
            WHERE timestamp >= $1 AND timestamp < $2
              AND session_id IS NOT NULL AND session_id <> ''
            ORDER BY session_id, timestamp
            """,
            inicio,
            fin,
        )
        for row in rows:
            sid = str(row["session_id"])
            accion = str(row["accion"] or "")
            resultado = str(row["resultado"] or "")
            grouped.setdefault(sid, []).append((accion, resultado))
    except Exception as exc:
        logger.warning("No se pudo leer log_inmutable: %s", exc)

    sesiones: list[tuple[str, str, str, str]] = []
    for sid, events in grouped.items():
        user_bits = [r for a, r in events if "user" in a.lower() or a.startswith("turno_user")]
        asst_bits = [
            r for a, r in events if "assistant" in a.lower() or a.startswith("turno_assistant")
        ]
        if not user_bits and not asst_bits:
            user_bits = [a for a, _ in events]
            asst_bits = [r for _, r in events]
        sesiones.append(
            (
                sid,
                "\n".join(user_bits)[:4000],
                "\n".join(asst_bits)[:4000],
                f"corr_{sid}_{dia.isoformat()}",
            )
        )

    if sesiones:
        return sesiones

    try:
        runs = await fetch_audit_runs_window(horas_atras=24, limite=200)
    except Exception as exc:
        logger.warning("No se pudieron leer runs Agno: %s", exc)
        return []
    for run in runs.runs:
        if run.created_at.astimezone(UTC).date() != dia:
            continue
        sesiones.append(
            (
                run.session_id,
                run.input_usuario,
                run.output_agente,
                f"corr_{run.session_id}_{run.run_id}",
            )
        )
    return sesiones


async def _evaluar_sesion(
    judge,
    *,
    session_id: str,
    user_in: str,
    agent_out: str,
    correlation_id: str,
) -> JudgeEvaluationResult:
    prompt = (
        f"session_id={session_id}\ncorrelation_id={correlation_id}\n\n"
        f"INPUT DEL CLIENTE:\n{user_in}\n\nOUTPUT DEL AGENTE:\n{agent_out}\n\n"
        "Evaluá los 6 criterios binarios. Si un criterio no aplica, aprobado=true."
    )
    try:
        result = await judge.arun(
            input=prompt,
            session_id=f"judge-{session_id}",
            stream=False,
        )
        content = getattr(result, "content", result)
    except Exception as exc:
        logger.exception("Judge falló para %s: %s", session_id, exc)
        content = None
    return _parse_judge(content, session_id, correlation_id)


def _parse_judge(content, session_id: str, correlation_id: str) -> JudgeEvaluationResult:
    if isinstance(content, JudgeEvaluationResult):
        return content.model_copy(
            update={"session_id": session_id, "correlation_id": correlation_id}
        )
    payload = content
    if hasattr(content, "model_dump"):
        try:
            payload = content.model_dump()
        except Exception:
            payload = None
    if isinstance(payload, str):
        try:
            return JudgeEvaluationResult.model_validate_json(payload)
        except Exception:
            payload = None
    if isinstance(payload, dict):
        payload = {
            **payload,
            "session_id": session_id,
            "correlation_id": correlation_id,
        }
        try:
            return JudgeEvaluationResult.model_validate(payload)
        except Exception:
            pass
    scores = [
        JudgeCriterioScore(
            criterio=criterio,
            aprobado=False,
            observacion="No se pudo parsear la evaluación del juez.",
        )
        for criterio in CriterioEvaluacion
    ]
    return JudgeEvaluationResult(
        session_id=session_id,
        correlation_id=correlation_id,
        scores=scores,
    )


async def _persistir_evaluacion(result: JudgeEvaluationResult) -> None:
    await registrar(
        "judge_evaluation",
        session_id=result.session_id,
        correlation_id=result.correlation_id,
        payload=result.model_dump(mode="json"),
    )
    if result.aprobado:
        return
    for score in result.scores:
        if score.aprobado:
            continue
        categoria = _CRITERIO_A_CATEGORIA.get(score.criterio, AuditCategoria.OTRO)
        finding = AuditFinding(
            run_id=f"judge-{result.session_id}",
            session_id=result.session_id,
            agente_nombre="agente_judge",
            severidad=AuditSeverity.ALTA,
            categoria=categoria,
            descripcion=f"Criterio {score.criterio.value} reprobado ({result.puntos_totales}/6).",
            evidencia=score.observacion or result.categoria_fallo or score.criterio.value,
            recomendacion="Revisar el turno y reentrenar o ajustar guardrails.",
        )
        try:
            await execute(
                """
                INSERT INTO audit_findings (
                    finding_id, run_id, session_id, agente_nombre, severidad,
                    categoria, descripcion, evidencia, recomendacion, detectado_en
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (finding_id) DO NOTHING
                """,
                finding.finding_id,
                finding.run_id,
                finding.session_id,
                finding.agente_nombre,
                finding.severidad.value,
                finding.categoria.value,
                finding.descripcion,
                finding.evidencia,
                finding.recomendacion,
                finding.detectado_en,
            )
        except Exception as exc:
            logger.warning("No se persistió finding judge: %s", exc)


def _append_dataset(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    items: list = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = raw if isinstance(raw, list) else list(raw.get("items", []))
        except (json.JSONDecodeError, OSError):
            items = []
    entry_id = entry.get("id")
    if entry_id and any(isinstance(i, dict) and i.get("id") == entry_id for i in items):
        return
    items.append(entry)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _alertar_tecnica(result: JudgeEvaluationResult) -> None:
    logger.error(
        "alerta_tecnica_judge session=%s score=%s/%s fallo=%s",
        result.session_id,
        result.puntos_totales,
        6,
        result.categoria_fallo,
    )


async def _main_judge() -> int:
    try:
        summary = await run_nightly_audit()
    except Exception as exc:
        logger.exception("Falló el judge nocturno: %s", exc)
        return 1
    finally:
        await close_pool()
    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


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
    if "--judge" in sys.argv:
        sys.exit(asyncio.run(_main_judge()))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    horas_arg = int(args[0]) if args else 24
    sys.exit(asyncio.run(_main(horas_arg)))
