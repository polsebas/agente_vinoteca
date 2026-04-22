"""Persistencia de hallazgos del auditor con deduplicación por contenido."""

from __future__ import annotations

import hashlib
import unicodedata
from uuid import UUID

from agno.tools import tool

from schemas.audit import AuditCategoria, AuditFinding, AuditSeverity
from schemas.tool_responses import ResultadoTool
from storage.postgres import execute, fetchrow


def _normalize(text: str) -> str:
    """Normaliza para dedupe: minúsculas, sin acentos, espacios compactados."""
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def _dedupe_hash(run_id: str, categoria: str, evidencia: str) -> str:
    raw = f"{run_id}|{categoria}|{_normalize(evidencia)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@tool
async def guardar_hallazgo(
    run_id: str,
    agente_nombre: str,
    severidad: str,
    categoria: str,
    descripcion: str,
    evidencia: str,
    recomendacion: str,
    session_id: str | None = None,
) -> dict:
    """Persistir un hallazgo concreto de auditoría en `audit_findings`.

    Usá esta tool UNA VEZ por hallazgo detectado, después de contrastar el
    run contra la constitución correspondiente. NO llames a esta tool para
    runs limpios: ausencia de findings es una señal válida.

    La dedupe es por `(run_id, categoria, evidencia-normalizada)`. Si ya
    existe un hallazgo equivalente, devuelve el `finding_id` existente con
    `resultado=duplicado`, sin duplicar filas.

    Args:
        run_id: ID del run auditado (viene de `listar_runs_auditables`).
        agente_nombre: "agente_sommelier" | "agente_orders" | "agente_support".
        severidad: "critica" | "alta" | "media" | "baja".
        categoria: Valor de `AuditCategoria` (snake_case, ej "halucinacion").
        descripcion: Resumen del hallazgo (10-1000 chars).
        evidencia: Cita textual que respalda el hallazgo.
        recomendacion: Acción concreta para el equipo.
        session_id: Si está disponible, el session_id del run.

    Returns:
        Dict con `resultado` (`ok`|`duplicado`|`error`) y `finding_id`.
    """
    try:
        finding = AuditFinding(
            run_id=run_id,
            session_id=session_id,
            agente_nombre=agente_nombre,
            severidad=AuditSeverity(severidad),
            categoria=AuditCategoria(categoria),
            descripcion=descripcion,
            evidencia=evidencia,
            recomendacion=recomendacion,
        )
    except (ValueError, TypeError) as exc:
        return {
            "resultado": ResultadoTool.ERROR.value,
            "mensaje": f"Hallazgo mal formado: {exc}",
        }

    dhash = _dedupe_hash(finding.run_id, finding.categoria.value, finding.evidencia)

    existing = await fetchrow(
        "SELECT finding_id FROM audit_findings WHERE dedupe_hash = $1",
        dhash,
    )
    if existing is not None:
        return {
            "resultado": "duplicado",
            "finding_id": str(existing["finding_id"]),
        }

    await execute(
        """
        INSERT INTO audit_findings (
            finding_id, run_id, session_id, agente_nombre,
            severidad, categoria, descripcion, evidencia,
            recomendacion, detectado_en, dedupe_hash
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (dedupe_hash) DO NOTHING
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
        dhash,
    )
    return {
        "resultado": ResultadoTool.OK.value,
        "finding_id": str(finding.finding_id),
    }


async def contar_hallazgos_por_run(run_id: str) -> int:
    """Helper interno para reporting: cantidad de findings asociadas a un run."""
    row = await fetchrow(
        "SELECT COUNT(*)::int AS n FROM audit_findings WHERE run_id = $1",
        UUID(run_id) if _is_uuid(run_id) else run_id,
    )
    return int((row or {}).get("n", 0))


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False
