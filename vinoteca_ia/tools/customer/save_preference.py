"""Persistencia de preferencias del cliente en almacén semántico."""

from __future__ import annotations

from uuid import uuid4

from agno.tools import tool

from schemas.tool_responses import ResultadoTool, SavePreferenceResponse
from storage.postgres import execute


@tool
async def guardar_preferencia(
    cliente_id: str,
    tipo: str,
    valor: str,
    confianza: float = 0.7,
) -> SavePreferenceResponse:
    """Persistir una preferencia detectada durante la conversación.

    Usá esta tool cuando el cliente dice explícitamente algo como:
    - "No me gusta el tinto dulce" → tipo="aversion", valor="tinto_dulce"
    - "Prefiero Malbec de Mendoza" → tipo="varietal_favorito", valor="malbec_mendoza"
    - "Mi presupuesto es hasta 15k" → tipo="rango_precio_max", valor="15000"

    NO la uses para guardar inferencias especulativas (confianza<0.6). Solo
    para lo que el cliente manifiesta con claridad. Las preferencias guardadas
    se usarán en futuras sesiones por `cargar_contexto_cliente`.

    Args:
        cliente_id: ID del cliente registrado. Si es None o vacío, la
            preferencia NO se persiste (invitado).
        tipo: Categoría de la preferencia (snake_case).
        valor: Valor concreto.
        confianza: 0.0-1.0 (mínimo recomendado: 0.6).

    Returns:
        SavePreferenceResponse con `preferencia_id` o error.
    """
    if not cliente_id:
        return SavePreferenceResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="Cliente invitado: no se persisten preferencias.",
        )
    if confianza < 0.6:
        return SavePreferenceResponse(
            resultado=ResultadoTool.ERROR,
            mensaje=f"Confianza {confianza:.2f} < 0.6 — no se persiste.",
        )

    pref_id = str(uuid4())
    await execute(
        """
        INSERT INTO cliente_preferencias (
            id, cliente_id, tipo, valor, confianza, registrado_en
        ) VALUES ($1, $2, $3, $4, $5, NOW())
        """,
        pref_id,
        cliente_id,
        tipo,
        valor,
        confianza,
    )
    return SavePreferenceResponse(
        resultado=ResultadoTool.OK,
        preferencia_id=pref_id,
    )
