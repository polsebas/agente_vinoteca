"""Listado de runs auditables en una ventana temporal.

Dos consumidores:
- El **agente auditor** (vía la tool `listar_runs_auditables`).
- El **job nocturno** (vía `fetch_audit_runs_window`), que no depende del LLM
  para fijar la ventana: así la auditoría es determinista respecto a `horas_atras`.

Cubre sesiones de tipo AGENT **y** TEAM. Para cada `TeamRunOutput` se aplana la
lista `member_responses` y cada `RunOutput` hijo se expone como un `RunAuditable`
con `agente_nombre = run.agent_id` (que es lo que propaga Agno tras
`_propagate_member_pause`).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from agno.db.base import SessionType
from agno.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from storage.postgres import get_agno_db

_AGENTES_AUDITABLES = {
    "agente_sommelier",
    "agente_orders",
    "agente_support",
}


class RunAuditable(BaseModel):
    """Proyección mínima de un run para el juez."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    session_id: str
    agente_nombre: str
    user_id: str | None = None
    input_usuario: str = Field(default="")
    output_agente: str = Field(default="")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class RunsAuditablesResponse(BaseModel):
    """Respuesta de `listar_runs_auditables`.

    `runs_devueltos` es el conteo real devuelto; `truncado` indica si se alcanzó
    el límite y quedaron runs afuera. No intentamos estimar un "total en ventana"
    para no mentir.
    """

    model_config = ConfigDict(extra="forbid")

    ventana_desde: datetime
    ventana_hasta: datetime
    runs_devueltos: int
    truncado: bool
    runs: list[RunAuditable]

    @property
    def total(self) -> int:
        """Alias de compatibilidad hacia atrás para consumidores antiguos."""
        return self.runs_devueltos


async def fetch_audit_runs_window(
    horas_atras: int = 24,
    limite: int = 50,
    agente: str | None = None,
) -> RunsAuditablesResponse:
    """Función pura reutilizable por la tool y por el job.

    Lee tanto `SessionType.AGENT` como `SessionType.TEAM` y aplana los
    `member_responses` de los runs de Team. El filtro por agente (opcional)
    se aplica después de aplanar, para que funcione igual en ambos tipos.
    """
    ahora = datetime.now(UTC)
    desde = ahora - timedelta(hours=max(1, horas_atras))
    limite = max(1, min(limite, 200))

    db = get_agno_db()
    agent_sessions, team_sessions = await asyncio.gather(
        asyncio.to_thread(
            db.get_sessions,
            session_type=SessionType.AGENT,
            start_timestamp=int(desde.timestamp()),
            end_timestamp=int(ahora.timestamp()),
            limit=limite,
            sort_by="created_at",
            sort_order="desc",
        ),
        asyncio.to_thread(
            db.get_sessions,
            session_type=SessionType.TEAM,
            start_timestamp=int(desde.timestamp()),
            end_timestamp=int(ahora.timestamp()),
            limit=limite,
            sort_by="created_at",
            sort_order="desc",
        ),
    )

    runs: list[RunAuditable] = []
    truncado = False

    for sess in agent_sessions or []:
        agent_id = getattr(sess, "agent_id", None) or "desconocido"
        if agent_id not in _AGENTES_AUDITABLES:
            continue
        if agente and agent_id != agente:
            continue
        for run in getattr(sess, "runs", None) or []:
            if len(runs) >= limite:
                truncado = True
                break
            runs.append(
                _proyectar_run(
                    run,
                    session_id=sess.session_id,
                    agente_nombre=agent_id,
                    user_id=getattr(sess, "user_id", None),
                )
            )

    for sess in team_sessions or []:
        if len(runs) >= limite:
            truncado = True
            break
        session_id = sess.session_id
        user_id = getattr(sess, "user_id", None)
        for team_run in getattr(sess, "runs", None) or []:
            if len(runs) >= limite:
                truncado = True
                break
            for child in _iter_member_runs(team_run):
                if len(runs) >= limite:
                    truncado = True
                    break
                child_dict = _to_dict(child)
                agent_id = str(
                    child_dict.get("agent_id") or child_dict.get("agent_name") or ""
                )
                if agent_id not in _AGENTES_AUDITABLES:
                    continue
                if agente and agent_id != agente:
                    continue
                runs.append(
                    _proyectar_run(
                        child,
                        session_id=session_id,
                        agente_nombre=agent_id,
                        user_id=user_id,
                    )
                )

    return RunsAuditablesResponse(
        ventana_desde=desde,
        ventana_hasta=ahora,
        runs_devueltos=len(runs),
        truncado=truncado,
        runs=runs,
    )


@tool
async def listar_runs_auditables(
    horas_atras: int = 24,
    limite: int = 50,
    agente: str | None = None,
) -> RunsAuditablesResponse:
    """Obtener los runs de los últimos N horas para auditoría.

    Usá esta tool al INICIO de la corrida nocturna. Devuelve runs con input,
    output y tool calls, suficientes para evaluar adherencia a la constitución
    del agente correspondiente.

    Filtra a los agentes auditables: `agente_sommelier`, `agente_orders`,
    `agente_support`. El Router y los Teams no se auditan como entidades:
    los runs delegados a miembros sí (se aplanan automáticamente).

    Args:
        horas_atras: Tamaño de la ventana temporal (default 24h).
        limite: Máximo de runs a devolver (default 50, máximo 200).
        agente: Filtro por nombre específico ("agente_sommelier", etc.).

    Returns:
        `RunsAuditablesResponse` con ventana, conteo devuelto, flag de truncado
        y la lista de runs.
    """
    return await fetch_audit_runs_window(
        horas_atras=horas_atras, limite=limite, agente=agente
    )


def _iter_member_runs(team_run: Any):
    """Itera los `RunOutput` de miembros dentro de un `TeamRunOutput`.

    Soporta tanto objetos Agno como su forma serializada (dict persistido por
    PostgresDb). Si un miembro es a su vez un Team, recurre.
    """
    run_dict = _to_dict(team_run)
    members = run_dict.get("member_responses") or []
    for m in members:
        m_dict = _to_dict(m)
        if m_dict.get("member_responses") is not None:
            yield from _iter_member_runs(m_dict)
        else:
            yield m


def _proyectar_run(
    run: Any,
    session_id: str,
    agente_nombre: str,
    user_id: str | None,
) -> RunAuditable:
    """Extrae los campos relevantes de un run Agno, robusto a variaciones de schema."""
    run_dict = run if isinstance(run, dict) else _to_dict(run)
    run_id = str(run_dict.get("run_id") or run_dict.get("id") or "")
    input_msg = _extraer_input(run_dict)
    output_msg = _extraer_output(run_dict)
    tool_calls = _extraer_tool_calls(run_dict)
    created = _ts_to_datetime(run_dict.get("created_at"))
    return RunAuditable(
        run_id=run_id,
        session_id=session_id,
        agente_nombre=agente_nombre,
        user_id=user_id,
        input_usuario=input_msg[:4000],
        output_agente=output_msg[:4000],
        tool_calls=tool_calls,
        created_at=created,
    )


def _to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {}


def _extraer_input(run: dict[str, Any]) -> str:
    for key in ("input", "message", "user_message"):
        v = run.get(key)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict) and isinstance(v.get("content"), str):
            return v["content"]
    for msg in run.get("messages") or []:
        if isinstance(msg, dict) and msg.get("role") == "user":
            c = msg.get("content")
            if isinstance(c, str):
                return c
    return ""


def _extraer_output(run: dict[str, Any]) -> str:
    v = run.get("content") or run.get("output")
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, default=str)
    for msg in reversed(run.get("messages") or []):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            c = msg.get("content")
            if isinstance(c, str):
                return c
    return ""


def _extraer_tool_calls(run: dict[str, Any]) -> list[dict[str, Any]]:
    tools = run.get("tools") or []
    proyectado: list[dict[str, Any]] = []
    for t in tools:
        td = t if isinstance(t, dict) else _to_dict(t)
        proyectado.append(
            {
                "tool_name": td.get("tool_name"),
                "tool_args": td.get("tool_args"),
                "error": td.get("tool_call_error"),
                "confirmed": td.get("confirmed"),
                "requires_confirmation": td.get("requires_confirmation"),
            }
        )
    return proyectado


def _ts_to_datetime(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if isinstance(ts, int | float):
        return datetime.fromtimestamp(float(ts), tz=UTC)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)
