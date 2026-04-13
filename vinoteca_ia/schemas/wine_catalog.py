"""
Modelos Pydantic del catálogo de vinos y sus cinco capas de conocimiento.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class WineKnowledge(BaseModel):
    """Las cinco capas de conocimiento cualitativo de un vino (solo para RAG)."""

    capa_1_dato_duro: str | None = None
    capa_2_terruño: str | None = None
    capa_3_historia: str | None = None
    capa_4_tendencia: str | None = None
    capa_5_voz_propia: str | None = None


class WineModel(BaseModel):
    """Representación completa de un vino del catálogo."""

    id: UUID
    nombre: str
    bodega: str
    varietal: str
    cosecha: int | None = None
    precio: float
    descripcion: str | None = None
    region: str | None = None
    sub_region: str | None = None
    alcohol: float | None = None
    maridajes: list[str] = Field(default_factory=list)
    activo: bool = True
    conocimiento: WineKnowledge | None = None

    @field_validator("precio")
    @classmethod
    def precio_positivo(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("El precio debe ser mayor a cero.")
        return v


class StockInfo(BaseModel):
    """Resultado de una consulta de stock. Siempre via SQL, nunca RAG."""

    vino_id: UUID
    nombre: str
    disponible: bool
    cantidad: int
    ubicacion: str = "deposito_principal"


class PrecioInfo(BaseModel):
    """Resultado de una consulta de precio. Siempre via SQL, nunca RAG."""

    vino_id: UUID
    nombre: str
    precio: float
    moneda: str = "ARS"
