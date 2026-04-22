"""Modelos de catálogo de vinos. Fuente de verdad: SQL (no RAG)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class WineProduct(BaseModel):
    """Vino del catálogo. Inmutable desde el punto de vista del agente."""

    model_config = ConfigDict(extra="forbid")

    vino_id: UUID
    nombre: str
    bodega: str
    varietal: Varietal
    region: str
    precio_ars: Decimal = Field(gt=0, decimal_places=2)
    anada_actual: int = Field(ge=1900, le=2100)
    descripcion: str | None = None
    perfil_maridaje: PerfilMaridaje = Field(default_factory=PerfilMaridaje)
    activo: bool = True


class StockInfo(BaseModel):
    """Disponibilidad de un vino. Siempre SQL, nunca RAG."""

    model_config = ConfigDict(extra="forbid")

    vino_id: UUID
    nombre: str
    disponible: bool
    cantidad: int = Field(ge=0)
    ubicacion: str = "deposito_principal"
