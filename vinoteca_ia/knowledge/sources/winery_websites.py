"""Conector de fichas oficiales de bodega (mock + hook HTTP)."""

from __future__ import annotations

import os

import httpx
from pydantic import BaseModel, ConfigDict, Field

from schemas.knowledge_fragment import FuenteConocimiento

_MOCK_ARTICLES: tuple[dict[str, str], ...] = (
    {
        "producto_id": "achaval-malbec-2022",
        "titulo": "Achaval Ferrer Malbec 2022 — ficha técnica",
        "url": "https://www.achaval-ferrer.com/malbec-2022",
        "contenido": (
            "Malbec 2022 de Valle de Uco, 14.5% ABV. Suelos aluviales a 1100 msnm. "
            "Filosofía de mínima intervención del enólogo. "
            "Crianza en roble francés. Sin precio ni stock en esta ficha."
        ),
    },
    {
        "producto_id": "catena-malbec-2021",
        "titulo": "Catena Malbec 2021 — ficha de bodega",
        "url": "https://www.catenawines.com/malbec-2021",
        "contenido": (
            "Malbec de Agrelo y Gualtallary. Altura y clima continental. "
            "Historia familiar de la bodega Catena. Varietal 100% Malbec."
        ),
    },
)


class RawSourceDocument(BaseModel):
    """Artículo crudo previo al enricher."""

    model_config = ConfigDict(extra="forbid")

    titulo: str
    url: str
    contenido: str
    fuente: FuenteConocimiento = FuenteConocimiento.BODEGA_OFICIAL
    producto_id: str | None = Field(default=None)


async def fetch_winery_articles(
    *,
    producto_id: str | None = None,
    url: str | None = None,
) -> list[RawSourceDocument]:
    """Ingesta mock por default. Si `WINERY_FETCH_URL` o `url`, hace GET."""
    target = url or os.environ.get("WINERY_FETCH_URL")
    if target:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(target)
            resp.raise_for_status()
            return [
                RawSourceDocument(
                    titulo=target,
                    url=target,
                    contenido=resp.text[:8000],
                    fuente=FuenteConocimiento.BODEGA_OFICIAL,
                    producto_id=producto_id,
                )
            ]
    docs = [RawSourceDocument.model_validate(item) for item in _MOCK_ARTICLES]
    if producto_id:
        docs = [d for d in docs if d.producto_id == producto_id]
    return docs
