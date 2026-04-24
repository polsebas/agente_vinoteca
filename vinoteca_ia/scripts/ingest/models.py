"""Modelos Pydantic para la ingesta desde `product_details.txt`.

El archivo fuente usa keys con espacios (`"lugar de elaboracion"`,
`"altura (s.n.m.)"`) y valores mayormente string — incluidos los vacíos.
Trabajamos a nivel de `dict` normalizado (ver `normalizers.normalizar_fila`)
para evitar configurar un modelo Pydantic con alias para cada key con espacio.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class FilaCatalogo:
    """Fila del catálogo ya normalizada, lista para persistir en Postgres."""

    imagen_slug: str
    nombre: str
    bodega: str
    varietal: str
    region: str
    precio_ars: Decimal | None
    anada_actual: int | None
    descripcion: str | None
    ficha_tecnica: str | None
    corte: str | None
    alcohol_pct: Decimal | None
    volumen_ml: int | None
    tipo: str | None
    pais: str | None
    altura_msnm: int | None

    @property
    def es_persistible(self) -> bool:
        """Un vino es persistible si tiene los campos mínimos para venderlo.

        Política: sin precio positivo no se publica al catálogo. Las tools
        de precio y cálculo de orden fallarían contra una fila con precio
        NULL o cero.
        """
        return (
            bool(self.imagen_slug)
            and bool(self.nombre)
            and bool(self.bodega)
            and self.precio_ars is not None
            and self.precio_ars > 0
        )
