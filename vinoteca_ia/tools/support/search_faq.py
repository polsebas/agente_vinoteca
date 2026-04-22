"""Búsqueda de respuestas en la base de FAQ."""

from __future__ import annotations

from agno.tools import tool

from schemas.tool_responses import FAQResponse, ResultadoTool
from storage.postgres import fetchrow


@tool
async def buscar_faq(pregunta: str) -> FAQResponse:
    """Buscar la respuesta a una pregunta frecuente en la base de FAQ.

    Usá esta tool ANTES de escalar a humano cuando:
    - El cliente pregunta por envío, devoluciones, horarios, medios de pago.
    - Es una duda administrativa clara.

    Si la FAQ no tiene una respuesta relevante (`resultado=NO_ENCONTRADO`),
    intentá una vez más con una reformulación. Si vuelve a fallar, escalá
    a humano con `escalar_a_humano`.

    Args:
        pregunta: Texto libre de la pregunta del cliente.

    Returns:
        FAQResponse con la respuesta y fuente, o NO_ENCONTRADO.
    """
    if not pregunta.strip():
        return FAQResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="La pregunta no puede estar vacía.",
        )

    row = await fetchrow(
        """
        SELECT respuesta, fuente
        FROM faq
        WHERE ts_rank(search_vector, plainto_tsquery('spanish', $1)) > 0.1
        ORDER BY ts_rank(search_vector, plainto_tsquery('spanish', $1)) DESC
        LIMIT 1
        """,
        pregunta,
    )
    if row is None:
        return FAQResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            mensaje="Sin match en FAQ.",
        )
    return FAQResponse(
        resultado=ResultadoTool.OK,
        respuesta=row["respuesta"],
        fuente=row["fuente"],
    )
