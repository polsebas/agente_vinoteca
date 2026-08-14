"""Upsert de preferencias clave/valor del cliente."""

from __future__ import annotations

import asyncpg
from agno.tools import tool

from schemas.customer_profile import PerfilClienteTipo, SegmentoCliente
from schemas.tool_responses import ResultadoTool, SavePreferenceResponse
from storage.postgres import execute, fetchrow

_SEGMENTOS = {s.value for s in SegmentoCliente}
_PERFILES = {p.value for p in PerfilClienteTipo}


@tool
async def guardar_preferencia(
    cliente_id: str,
    tipo: str,
    valor: str,
    confianza: float = 0.7,
    fuente: str = "conversacion",
) -> SavePreferenceResponse:
    """Persistir una preferencia explícita del cliente (upsert por clave).

    Usá esta tool con lo que el cliente dice claro (cepa, presupuesto, aversión).
    No persistas inferencias con confianza < 0.6. Si `tipo` es `segmento` o
    `perfil_tipo`, también actualiza `clientes`.
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
    if not tipo.strip() or not valor.strip():
        return SavePreferenceResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="clave y valor son obligatorios.",
        )

    try:
        exists = await fetchrow("SELECT id FROM clientes WHERE id = $1", cliente_id)
        if exists is None:
            await execute(
                """
                INSERT INTO clientes (id, segmento, perfil_tipo, created_at)
                VALUES ($1, 'general', 'general', NOW())
                """,
                cliente_id,
            )
        await execute(
            """
            INSERT INTO cliente_preferencias (cliente_id, clave, valor, fuente, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (cliente_id, clave)
            DO UPDATE SET valor = EXCLUDED.valor,
                          fuente = EXCLUDED.fuente,
                          updated_at = NOW()
            """,
            cliente_id,
            tipo.strip(),
            valor.strip(),
            fuente,
        )
        if tipo.strip() == "segmento" and valor.strip() in _SEGMENTOS:
            await execute(
                "UPDATE clientes SET segmento = $1 WHERE id = $2",
                valor.strip(),
                cliente_id,
            )
        if tipo.strip() == "perfil_tipo" and valor.strip() in _PERFILES:
            await execute(
                "UPDATE clientes SET perfil_tipo = $1 WHERE id = $2",
                valor.strip(),
                cliente_id,
            )
    except asyncpg.UndefinedTableError:
        return SavePreferenceResponse(
            resultado=ResultadoTool.ERROR,
            mensaje="Esquema de preferencias no inicializado.",
        )

    row = await fetchrow(
        """
        SELECT id FROM cliente_preferencias
        WHERE cliente_id = $1 AND clave = $2
        """,
        cliente_id,
        tipo.strip(),
    )
    pref_id = str(row["id"]) if row else None
    return SavePreferenceResponse(
        resultado=ResultadoTool.OK,
        preferencia_id=pref_id,
    )
