"""Perfil del cliente con preferencias acumuladas."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from schemas.wine_catalog import Varietal


class SegmentoCliente(StrEnum):
    """Nivel de conocimiento / relación del cliente."""

    NUEVO = "nuevo"
    OCASIONAL = "ocasional"
    FRECUENTE = "frecuente"
    CONNAISSEUR = "connaisseur"


class PreferenciaRegistrada(BaseModel):
    """Una preferencia atómica capturada durante una interacción."""

    model_config = ConfigDict(extra="forbid")

    tipo: str = Field(
        description="Ej: 'varietal_favorito', 'rango_precio', 'region_preferida'",
    )
    valor: str
    confianza: float = Field(ge=0.0, le=1.0)
    origen_turno: int = Field(ge=0)
    registrado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CustomerProfile(BaseModel):
    """Perfil consolidado del cliente, leído por el sommelier antes de recomendar."""

    model_config = ConfigDict(extra="forbid")

    cliente_id: str
    nombre: str | None = None
    segmento: SegmentoCliente = SegmentoCliente.NUEVO
    varietales_favoritos: list[Varietal] = Field(default_factory=list)
    rango_precio_preferido_ars: tuple[int, int] | None = None
    alergias: list[str] = Field(default_factory=list)
    historial_preferencias: list[PreferenciaRegistrada] = Field(default_factory=list)
    total_compras: int = Field(ge=0, default=0)
