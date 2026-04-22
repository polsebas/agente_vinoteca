"""Carga del contexto del cliente (perfil + últimas preferencias)."""

from __future__ import annotations

from agno.tools import tool

from schemas.tool_responses import CustomerContextResponse, ResultadoTool
from storage.postgres import fetch_all, fetchrow


@tool
async def cargar_contexto_cliente(cliente_id: str) -> CustomerContextResponse:
    """Leer perfil, segmento y últimas preferencias del cliente.

    Usá esta tool al INICIO de toda interacción con un cliente identificado,
    antes de recomendar nada. Te permite personalizar recomendaciones
    (ej. "como te gustan los Malbec de Mendoza, probá este...").

    NO la uses si no hay `cliente_id` (cliente invitado): en ese caso
    recomendá con heurísticas generales.

    Args:
        cliente_id: Identificador único del cliente en la DB.

    Returns:
        CustomerContextResponse con un resumen narrativo del perfil (apto para
        inyectar en el contexto del LLM). Si no se encuentra, `encontrado=False`.
    """
    if not cliente_id:
        return CustomerContextResponse(
            resultado=ResultadoTool.ERROR,
            encontrado=False,
            mensaje="cliente_id vacío.",
        )

    perfil = await fetchrow(
        """
        SELECT nombre, segmento, total_compras,
               varietales_favoritos, rango_precio_min, rango_precio_max
        FROM clientes
        WHERE id = $1
        """,
        cliente_id,
    )
    if perfil is None:
        return CustomerContextResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            encontrado=False,
        )

    preferencias = await fetch_all(
        """
        SELECT tipo, valor, confianza
        FROM cliente_preferencias
        WHERE cliente_id = $1
        ORDER BY registrado_en DESC
        LIMIT 8
        """,
        cliente_id,
    )

    prefs_txt = ", ".join(f"{p['tipo']}={p['valor']}" for p in preferencias) or "sin preferencias"
    resumen = (
        f"Cliente {perfil['nombre'] or 'anónimo'} "
        f"(segmento: {perfil['segmento']}, compras: {perfil['total_compras']}). "
        f"Varietales favoritos: {perfil['varietales_favoritos'] or 'N/A'}. "
        f"Rango precio: {perfil['rango_precio_min']}-{perfil['rango_precio_max']} ARS. "
        f"Últimas preferencias: {prefs_txt}."
    )
    return CustomerContextResponse(
        resultado=ResultadoTool.OK,
        encontrado=True,
        perfil_resumen=resumen,
    )
