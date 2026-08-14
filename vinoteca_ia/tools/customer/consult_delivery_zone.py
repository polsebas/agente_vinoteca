"""Evaluación de zona de entrega por código postal. Determinista, sin LLM."""

from __future__ import annotations

from decimal import Decimal

from agno.tools import tool

from schemas.tool_responses import DeliveryZoneResponse, ResultadoTool

_COSTO_CABA = Decimal("1500.00")
_COSTO_GBA = Decimal("2500.00")
_COSTO_INTERIOR = Decimal("4500.00")


def _clasificar(cp: str) -> tuple[str, bool, Decimal, int]:
    digits = "".join(ch for ch in cp.upper() if ch.isdigit())
    if len(digits) < 4:
        return ("desconocida", False, Decimal("0.00"), 0)
    prefix = digits[:2]
    if cp.upper().startswith("C") or prefix in {"10", "11", "12", "13", "14"}:
        return ("caba", True, _COSTO_CABA, 1)
    if prefix in {"16", "17", "18", "19", "15"}:
        return ("gba", True, _COSTO_GBA, 2)
    return ("interior", True, _COSTO_INTERIOR, 5)


@tool
async def consultar_zona_entrega(codigo_postal: str) -> DeliveryZoneResponse:
    """Calcular si cubrimos el CP, costo de envío y demora en días.

    Usá esta tool antes de cotizar un envío a domicilio. No consulta RAG.
    El umbral de envío gratis ($30.000) lo aplica `calcular_orden`.
    """
    if not codigo_postal.strip():
        return DeliveryZoneResponse(
            resultado=ResultadoTool.ERROR,
            codigo_postal=codigo_postal,
            zona="desconocida",
            cubre=False,
            costo_envio=Decimal("0.00"),
            mensaje="Código postal vacío.",
        )
    zona, cubre, costo, dias = _clasificar(codigo_postal.strip())
    return DeliveryZoneResponse(
        resultado=ResultadoTool.OK if cubre else ResultadoTool.NO_ENCONTRADO,
        codigo_postal=codigo_postal.strip(),
        zona=zona,
        cubre=cubre,
        costo_envio=costo,
        demora_dias=dias if cubre else None,
        mensaje=None if cubre else "No cubrimos esa zona con el CP indicado.",
    )
