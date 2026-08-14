"""Búsqueda de FAQ (envío, devoluciones, políticas). SQL + fallback estático."""

from __future__ import annotations

import asyncpg
from agno.tools import tool

from schemas.tool_responses import FAQResponse, ResultadoTool
from storage.postgres import fetchrow

_FAQ_FALLBACK: tuple[tuple[str, str, str], ...] = (
    (
        "envio",
        "Hacemos envíos a CABA, GBA e interior. Envío gratis superando $30.000 ARS. "
        "CABA 24h, GBA 48h, interior 5 días hábiles.",
        "politicas_envio_v1",
    ),
    (
        "devolucion",
        "Aceptamos devoluciones de botellas cerradas dentro de los 10 días. "
        "Vinos abiertos o defectuosos: reclamo con foto y lote.",
        "politicas_devolucion_v1",
    ),
    (
        "pago",
        "Aceptamos Mercado Pago, transferencia y efectivo en retiro. "
        "El link de pago vence a los 30 minutos.",
        "politicas_pago_v1",
    ),
    (
        "horario",
        "Local: martes a sábado 11 a 20. Retiros el mismo día si hay stock.",
        "politicas_horario_v1",
    ),
)


def _sin_tildes(texto: str) -> str:
    return texto.translate(str.maketrans("áéíóúüÁÉÍÓÚÜ", "aeiouuAEIOUU")).lower()


def _fallback(pregunta: str) -> FAQResponse | None:
    q = _sin_tildes(pregunta)
    for clave, respuesta, fuente in _FAQ_FALLBACK:
        if clave in q:
            return FAQResponse(
                resultado=ResultadoTool.OK,
                respuesta=respuesta,
                fuente=fuente,
            )
    return None


@tool
async def buscar_faq(pregunta: str) -> FAQResponse:
    """Buscar políticas de envío, devolución, pago u horarios.

    Probá esta tool ANTES de escalar. Si no hay match, reformulá una vez;
    si falla de nuevo, `escalar_a_humano`.
    """
    if not pregunta.strip():
        return FAQResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La pregunta no puede estar vacía.",
        )
    try:
        row = await fetchrow(
            """
            SELECT respuesta, fuente
            FROM faq
            WHERE search_vector @@ plainto_tsquery('spanish', $1)
            ORDER BY ts_rank(search_vector, plainto_tsquery('spanish', $1)) DESC
            LIMIT 1
            """,
            pregunta,
        )
    except asyncpg.UndefinedTableError:
        row = None
    if row is not None:
        return FAQResponse(
            resultado=ResultadoTool.OK,
            respuesta=row["respuesta"],
            fuente=row["fuente"],
        )
    fb = _fallback(pregunta)
    if fb is not None:
        return fb
    return FAQResponse(
        resultado=ResultadoTool.NO_ENCONTRADO,
        mensaje="Sin match en FAQ.",
    )
