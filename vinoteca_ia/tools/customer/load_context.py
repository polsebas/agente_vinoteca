"""Carga del contexto del cliente (perfil + preferencias clave/valor)."""

from __future__ import annotations

import asyncpg
from agno.tools import tool

from schemas.customer_profile import (
    CustomerProfile,
    PerfilClienteTipo,
    PreferenciaRegistrada,
    SegmentoCliente,
)
from schemas.tool_responses import CustomerContextResponse, ResultadoTool
from schemas.wine_catalog import Varietal
from storage.postgres import fetch_all, fetchrow


def _enum(cls, raw: str | None, default):
    try:
        return cls(raw or default.value)
    except ValueError:
        return default


def _cepas_desde_prefs(prefs: list) -> list[Varietal]:
    resultado: list[Varietal] = []
    for p in prefs:
        clave = str(p["clave"] if "clave" in p else p.get("tipo", ""))
        if clave not in {"cepa_favorita", "varietal_favorito", "cepas_favoritas"}:
            continue
        try:
            resultado.append(Varietal(str(p["valor"])))
        except ValueError:
            resultado.append(Varietal.OTRO)
    return resultado


@tool
async def cargar_contexto_cliente(cliente_id: str) -> CustomerContextResponse:
    """Leer perfil y preferencias persistidas del cliente identificado.

    Invocala al INICIO si hay `cliente_id`. No la uses con invitados.
    """
    if not cliente_id:
        return CustomerContextResponse(
            resultado=ResultadoTool.ERROR,
            encontrado=False,
            mensaje="cliente_id vacío.",
        )
    try:
        perfil_row = await fetchrow(
            """
            SELECT nombre, email, telefono, segmento, perfil_tipo
            FROM clientes
            WHERE id = $1
            """,
            cliente_id,
        )
    except asyncpg.UndefinedTableError:
        return CustomerContextResponse(
            resultado=ResultadoTool.ERROR,
            encontrado=False,
            mensaje="Esquema de clientes no inicializado.",
        )
    if perfil_row is None:
        return CustomerContextResponse(
            resultado=ResultadoTool.NO_ENCONTRADO,
            encontrado=False,
        )

    try:
        preferencias = await fetch_all(
            """
            SELECT clave, valor, fuente, updated_at
            FROM cliente_preferencias
            WHERE cliente_id = $1
            ORDER BY updated_at DESC
            LIMIT 20
            """,
            cliente_id,
        )
    except asyncpg.UndefinedTableError:
        preferencias = []

    historial = [
        PreferenciaRegistrada(
            tipo=p["clave"],
            valor=p["valor"],
            confianza=1.0,
            origen_turno=0,
            registrado_en=p["updated_at"],
        )
        for p in preferencias
    ]
    perfil = CustomerProfile(
        cliente_id=cliente_id,
        nombre=perfil_row["nombre"],
        segmento=_enum(SegmentoCliente, perfil_row["segmento"], SegmentoCliente.GENERAL),
        perfil_tipo=_enum(PerfilClienteTipo, perfil_row["perfil_tipo"], PerfilClienteTipo.GENERAL),
        cepas_favoritas=_cepas_desde_prefs(preferencias),
        historial_preferencias=historial,
    )
    return CustomerContextResponse(
        resultado=ResultadoTool.OK,
        encontrado=True,
        perfil=perfil,
    )
