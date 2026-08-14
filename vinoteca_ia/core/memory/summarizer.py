"""Compresión extractiva del historial de conversación.

Se dispara cuando hay ≥ 12 turnos. No llama al LLM: extrae preferencias del
cliente, vinos mencionados y estado del carrito para no perder señales duras
al recortar la ventana de working memory.
"""

from __future__ import annotations

import re

_MAX_CHARS_PER_TOKEN = 4

_PREFERENCIA_RE = re.compile(
    r"(?i)\b("
    r"prefiero|me\s+gusta|no\s+tomo|no\s+me\s+gusta|alergi[ao]|"
    r"presupuesto|rango\s+de\s+precio|cepa|varietal|malbec|cabernet|"
    r"pinot|chardonnay|torront[eé]s|bonarda|tannat"
    r")\b"
)
_VINO_RE = re.compile(
    r"\b(?:Catena|Achaval|Rutini|Zuccardi|Luigi\s+Bosca|Norton|"
    r"Trapiche|Salentein|Susana\s+Balbo|El\s+Enemigo|Cheval\s+des\s+Andes|"
    r"Malbec|Cabernet|Pinot\s+Noir|Chardonnay|Torront[eé]s)\b"
    r"(?:\s+\d{4})?",
    re.I,
)
_CARRITO_RE = re.compile(
    r"(?i)\b("
    r"pedido|carrito|agreg(?:ar|á|a)|botellas?|unidades?|"
    r"cantidad|checkout|pago|delivery|env[ií]o"
    r")\b"
)


def summarize_history(messages: list[dict], max_tokens: int = 500) -> str:
    """Comprime turnos viejos preservando preferencias, vinos y carrito.

    `messages` es una lista de dicts con claves `role`/`content` (o
    `rol`/`contenido`). El techo `max_tokens` se aproxima a 4 caracteres
    por token para no inflar el contexto del siguiente turno.
    """
    if not messages:
        return ""

    preferencias: list[str] = []
    vinos: list[str] = []
    carrito: list[str] = []

    for msg in messages:
        content = str(msg.get("content") or msg.get("contenido") or "").strip()
        if not content:
            continue
        if _PREFERENCIA_RE.search(content):
            preferencias.append(_clip(content, 180))
        for match in _VINO_RE.finditer(content):
            nombre = re.sub(r"\s+", " ", match.group(0)).strip()
            if nombre.lower() not in {v.lower() for v in vinos}:
                vinos.append(nombre)
        if _CARRITO_RE.search(content):
            carrito.append(_clip(content, 180))

    secciones: list[str] = []
    if preferencias:
        secciones.append("Preferencias: " + " | ".join(_unique(preferencias)[:6]))
    if vinos:
        secciones.append("Vinos mencionados: " + ", ".join(vinos[:8]))
    if carrito:
        secciones.append("Carrito/pedido: " + " | ".join(_unique(carrito)[:4]))

    if not secciones:
        ultimos = [
            _clip(str(m.get("content") or m.get("contenido") or ""), 120) for m in messages[-3:]
        ]
        secciones.append("Resumen reciente: " + " / ".join(t for t in ultimos if t))

    resumen = " ".join(secciones)
    limite = max(32, max_tokens * _MAX_CHARS_PER_TOKEN)
    if len(resumen) > limite:
        resumen = resumen[: limite - 1].rstrip() + "…"
    return resumen


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
