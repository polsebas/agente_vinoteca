"""Monitor de prensa y puntajes críticos (mock + hook HTTP)."""

from __future__ import annotations

import os

import httpx
from pydantic import BaseModel, ConfigDict, Field

from schemas.knowledge_fragment import FuenteConocimiento

_MOCK_PRESS: tuple[dict[str, str], ...] = (
    {
        "producto_id": "achaval-malbec-2022",
        "titulo": "Descorchados: Achaval Malbec 2022",
        "url": "https://descorchados.example/achaval-2022",
        "contenido": (
            "Puntaje 94. Tendencia de malbecs de altura en Valle de Uco. "
            "Notas de crítica: fruta negra, taninos firmes, guarda de 8 años."
        ),
    },
    {
        "producto_id": "catena-malbec-2021",
        "titulo": "Wine Advocate — Catena Malbec",
        "url": "https://press.example/catena-2021",
        "contenido": (
            "Reconocimiento crítico internacional. Estilo orgánico emergente. "
            "Parker destaca el equilibrio del 2021."
        ),
    },
)


class PressMention(BaseModel):
    """Mención de prensa previa al enricher."""

    model_config = ConfigDict(extra="forbid")

    titulo: str
    url: str
    contenido: str
    fuente: FuenteConocimiento = FuenteConocimiento.CRITICO
    producto_id: str | None = Field(default=None)


async def fetch_press_mentions(
    *,
    producto_id: str | None = None,
    url: str | None = None,
) -> list[PressMention]:
    """Ingesta mock por default. `PRESS_FETCH_URL` habilita GET real."""
    target = url or os.environ.get("PRESS_FETCH_URL")
    if target:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(target)
            resp.raise_for_status()
            return [
                PressMention(
                    titulo=target,
                    url=target,
                    contenido=resp.text[:8000],
                    fuente=FuenteConocimiento.CRITICO,
                    producto_id=producto_id,
                )
            ]
    docs = [PressMention.model_validate(item) for item in _MOCK_PRESS]
    if producto_id:
        docs = [d for d in docs if d.producto_id == producto_id]
    return docs
