"""Modelos de respuesta tipados para todas las tools.

Cada tool declara su modelo de retorno. El agente nunca recibe un dict suelto.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.order import Order
from schemas.wine_catalog import StockInfo, WineProduct


class ResultadoTool(StrEnum):
    OK = "ok"
    ERROR = "error"
    NO_ENCONTRADO = "no_encontrado"


class StockResponse(BaseModel):
    """Respuesta de consulta de stock."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    items: list[StockInfo] = Field(default_factory=list)
    todos_disponibles: bool = False
    mensaje: str | None = None


class PrecioItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vino_id: UUID
    nombre: str
    precio_ars: Decimal = Field(gt=0, decimal_places=2)
    anada: int


class PriceResponse(BaseModel):
    """Respuesta de consulta de precios. Precios SIEMPRE de SQL, nunca inventados."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    items: list[PrecioItem] = Field(default_factory=list)
    mensaje: str | None = None


class VinoRecomendado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vino: WineProduct
    score_relevancia: float = Field(ge=0.0, le=1.0)
    razon: str


class PairingResponse(BaseModel):
    """Respuesta de búsqueda semántica por maridaje. Los precios incluidos
    vienen de SQL, el ranking del vector store.
    """

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    recomendaciones: list[VinoRecomendado] = Field(default_factory=list)
    mensaje: str | None = None


class OccasionResponse(BaseModel):
    """Respuesta de búsqueda semántica por ocasión (regalo, cena romántica, etc)."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    recomendaciones: list[VinoRecomendado] = Field(default_factory=list)
    mensaje: str | None = None


class VerifyStockResponse(BaseModel):
    """Respuesta de verificación EXACTA de stock antes de crear orden.

    Distinta de StockResponse (informativa): esta es autoritativa y crea una
    **reserva temporal** cuando `todos_disponibles=True`. La reserva tiene TTL
    (default 15 min) y es consumida por `crear_orden`. Si expira antes de la
    confirmación, el agente debe reintentar la verificación.
    """

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    todos_disponibles: bool
    items: list[StockInfo] = Field(default_factory=list)
    faltantes: list[UUID] = Field(default_factory=list)
    reserva_token: str | None = Field(
        default=None,
        description="ID de la reserva creada. Sólo presente si la verificación tuvo éxito.",
    )
    reserva_expira_en: str | None = Field(
        default=None,
        description="Timestamp ISO-8601 en UTC del fin de vigencia de la reserva.",
    )
    mensaje: str | None = None


class CalculationResponse(BaseModel):
    """Respuesta del cálculo de totales. Determinista, sin LLM."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    subtotal_ars: Decimal
    envio_ars: Decimal
    total_ars: Decimal
    mensaje: str | None = None


class CreateOrderResponse(BaseModel):
    """Respuesta de creación de orden (Fase 1 del Two-Phase Commit)."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    order: Order | None = None
    mensaje: str | None = None


class PaymentLinkResponse(BaseModel):
    """Respuesta del envío del link de pago (Fase 2)."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    order_id: UUID
    payment_link: str | None = None
    mensaje: str | None = None


class CustomerContextResponse(BaseModel):
    """Respuesta de carga de contexto del cliente."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    encontrado: bool
    perfil_resumen: str | None = None
    mensaje: str | None = None


class SavePreferenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    preferencia_id: str | None = None
    mensaje: str | None = None


class EscalationResponse(BaseModel):
    """Respuesta de escalada a operador humano."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    ticket_id: str | None = None
    operador_notificado: bool = False
    mensaje: str | None = None


class FAQResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    respuesta: str | None = None
    fuente: str | None = None
    mensaje: str | None = None
