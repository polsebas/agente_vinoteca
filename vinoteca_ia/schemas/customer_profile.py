"""Perfil del cliente con preferencias acumuladas y memoria semántica."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from schemas.wine_catalog import Varietal


class PerfilClienteTipo(StrEnum):
    """Persona cognitiva que el sommelier usa para elegir capa y tono."""

    COLECCIONISTA = "coleccionista"
    CURIOSO = "curioso"
    OCASION = "ocasion"
    GENERAL = "general"


class SegmentoCliente(StrEnum):
    """Nivel de relación / recurrencia del cliente."""

    NUEVO = "nuevo"
    OCASIONAL = "ocasional"
    FRECUENTE = "frecuente"
    CONNAISSEUR = "connaisseur"
    GENERAL = "general"


class PreferenciaRegistrada(BaseModel):
    """Una preferencia atómica capturada durante una interacción."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tipo: str = Field(
        description="Ej: 'varietal_favorito', 'rango_precio', 'region_preferida'",
        validation_alias=AliasChoices("tipo", "clave"),
    )
    valor: str
    confianza: float = Field(ge=0.0, le=1.0)
    origen_turno: int = Field(ge=0)
    registrado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CustomerProfile(BaseModel):
    """Perfil consolidado del cliente, leído por el sommelier antes de recomendar."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    cliente_id: str
    nombre: str | None = None
    segmento: SegmentoCliente = SegmentoCliente.NUEVO
    perfil_tipo: PerfilClienteTipo = PerfilClienteTipo.GENERAL
    cepas_favoritas: list[Varietal] = Field(
        default_factory=list,
        validation_alias=AliasChoices("cepas_favoritas", "varietales_favoritos"),
    )
    restricciones_dietarias: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("restricciones_dietarias", "alergias"),
    )
    rango_precio_habitual: tuple[int, int] | None = Field(
        default=None,
        validation_alias=AliasChoices("rango_precio_habitual", "rango_precio_preferido_ars"),
    )
    fecha_ultima_compra: datetime | None = None
    historial_preferencias: list[PreferenciaRegistrada] = Field(default_factory=list)
    total_compras: int = Field(default=0, ge=0)

    @property
    def varietales_favoritos(self) -> list[Varietal]:
        return self.cepas_favoritas

    @property
    def alergias(self) -> list[str]:
        return self.restricciones_dietarias
