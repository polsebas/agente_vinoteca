"""Modelos de catálogo de vinos. Fuente de verdad: SQL (no RAG)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from schemas.knowledge_fragment import CapaConocimiento

_UMBRAL_PUBLICACION = 3


def _coerce_catalog_id(value: Any) -> Any:
    if value is None:
        return value
    return str(value)


CatalogId = Annotated[str, BeforeValidator(_coerce_catalog_id)]


class Varietal(StrEnum):
    MALBEC = "malbec"
    CABERNET_SAUVIGNON = "cabernet_sauvignon"
    PINOT_NOIR = "pinot_noir"
    MERLOT = "merlot"
    CHARDONNAY = "chardonnay"
    SAUVIGNON_BLANC = "sauvignon_blanc"
    TORRONTES = "torrontes"
    BONARDA = "bonarda"
    TANNAT = "tannat"
    ROSADO = "rosado"
    ESPUMANTE = "espumante"
    OTRO = "otro"


class PerfilMaridaje(BaseModel):
    """Maridajes recomendados del vino. Datos cualitativos, alimentan el RAG."""

    model_config = ConfigDict(extra="forbid")

    carnes_rojas: bool = False
    carnes_blancas: bool = False
    pescados: bool = False
    pastas: bool = False
    quesos: bool = False
    postres: bool = False
    aperitivo: bool = False
    notas_libres: str | None = Field(
        default=None,
        description="Descripción narrativa del maridaje, indexada en RAG",
    )


class InfoAnada(BaseModel):
    """Información específica de una añada."""

    model_config = ConfigDict(extra="forbid")

    anada: int = Field(ge=1900, le=2100)
    puntaje_critico: int | None = Field(default=None, ge=0, le=100)
    notas_cata: str | None = None
    potencial_guarda_anos: int | None = Field(default=None, ge=0, le=100)


class StockInfo(BaseModel):
    """Disponibilidad de un vino. Siempre SQL, nunca RAG."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    vino_id: CatalogId = Field(validation_alias=AliasChoices("vino_id", "producto_id", "id"))
    nombre: str
    disponible: bool
    cantidad: int = Field(ge=0)
    ubicacion: str = "deposito_principal"


class WineProduct(BaseModel):
    """Vino del catálogo. Inmutable desde el punto de vista del agente.

    `apto_publicacion` es verdadero solo si el vino está activo y tiene al
    menos 3 de las 5 capas de conocimiento.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    vino_id: CatalogId = Field(validation_alias=AliasChoices("vino_id", "producto_id", "id"))
    nombre: str
    bodega: str
    varietal: Varietal
    region: str
    precio_ars: Decimal = Field(gt=0, decimal_places=2)
    anada_actual: int = Field(ge=1900, le=2100)
    descripcion: str | None = None
    perfil_maridaje: PerfilMaridaje = Field(default_factory=PerfilMaridaje)
    anadas: list[InfoAnada] = Field(default_factory=list)
    activo: bool = True
    capas_disponibles: list[CapaConocimiento] = Field(default_factory=list)
    stock_info: StockInfo | None = None
    apto_publicacion: bool = False

    @model_validator(mode="after")
    def _derivar_publicacion_y_stock(self) -> Self:
        capas_unicas = {int(capa) for capa in self.capas_disponibles}
        self.apto_publicacion = self.activo and len(capas_unicas) >= _UMBRAL_PUBLICACION
        if self.stock_info is None:
            self.stock_info = StockInfo(
                vino_id=self.vino_id,
                nombre=self.nombre,
                disponible=False,
                cantidad=0,
            )
        return self
