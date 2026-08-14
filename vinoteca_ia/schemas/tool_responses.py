"""Modelos de respuesta tipados para todas las tools.

Cada tool declara su modelo de retorno. El agente nunca recibe un dict suelto.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from schemas.customer_profile import CustomerProfile
from schemas.knowledge_fragment import CapaConocimiento
from schemas.order import CalculatedOrder, ConfirmedOrder, Order
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


class RAGResult(BaseModel):
    """Un fragmento de `wine_knowledge` devuelto por búsqueda semántica."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    vino_id: str = Field(validation_alias=AliasChoices("vino_id", "producto_id"))
    nombre_vino: str
    capa: CapaConocimiento
    contenido: str
    score: float
    triples: list[str] = Field(default_factory=list)
    nodos: list[str] = Field(default_factory=list)
    modo_retrieval: str | None = None


class PrecioItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    vino_id: str = Field(validation_alias=AliasChoices("vino_id", "producto_id"))
    nombre: str
    precio_ars: Decimal = Field(gt=0, decimal_places=2)
    anada: int | None = None
    promocion: str | None = None


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
    fragmentos: list[RAGResult] = Field(default_factory=list)
    recomendaciones: list[VinoRecomendado] = Field(default_factory=list)
    mensaje: str | None = None


class OccasionResponse(BaseModel):
    """Respuesta de búsqueda semántica por ocasión (regalo, cena romántica, etc)."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    fragmentos: list[RAGResult] = Field(default_factory=list)
    recomendaciones: list[VinoRecomendado] = Field(default_factory=list)
    mensaje: str | None = None


class VerifyStockResponse(BaseModel):
    """Fase 1 del 2PC: lectura autoritativa. No reserva ni muta stock.

    Distinta de StockResponse (informativa). Si `todos_disponibles` es False,
    el agente no debe avanzar a `calcular_orden` / `crear_orden`.
    """

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    todos_disponibles: bool
    items: list[StockInfo] = Field(default_factory=list)
    faltantes: list[str] = Field(default_factory=list)
    reserva_token: str | None = Field(
        default=None,
        description="ID de la reserva creada. Sólo presente si la verificación tuvo éxito.",
    )
    reserva_expira_en: str | None = Field(
        default=None,
        description="Timestamp ISO-8601 en UTC del fin de vigencia de la reserva.",
    )
    mensaje: str | None = None


class CalculatedOrderResponse(BaseModel):
    """Respuesta del cálculo de totales (Fase 1 del 2PC). Determinista, sin LLM."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    order: CalculatedOrder | None = None
    mensaje: str | None = None

    @property
    def pedido(self) -> CalculatedOrder | None:
        return self.order

    @property
    def total(self) -> Decimal:
        return self.order.total if self.order is not None else Decimal("0")

    @property
    def envio(self) -> Decimal:
        return self.order.costo_envio if self.order is not None else Decimal("0")

    @property
    def lineas(self):
        return self.order.lineas if self.order is not None else []

    @property
    def subtotal_ars(self) -> Decimal:
        return self.order.subtotal if self.order is not None else Decimal("0")

    @property
    def envio_ars(self) -> Decimal:
        return self.envio

    @property
    def total_ars(self) -> Decimal:
        return self.total


# Alias de compatibilidad con callers de la Fase 1.
CalculationResponse = CalculatedOrderResponse


class CreateOrderResponse(BaseModel):
    """Respuesta de creación de orden (Fase 1 del Two-Phase Commit)."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    order: Order | ConfirmedOrder | None = None
    mensaje: str | None = None


class PaymentLinkResponse(BaseModel):
    """Respuesta del envío del link de pago (Fase 2)."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    order_id: str
    payment_link: str | None = None
    mensaje: str | None = None


class CustomerContextResponse(BaseModel):
    """Respuesta de carga de contexto del cliente."""

    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    encontrado: bool
    perfil: CustomerProfile | None = None
    perfil_resumen: str | None = None
    mensaje: str | None = None

    @model_validator(mode="after")
    def _completar_resumen(self) -> Self:
        if self.perfil is not None and not self.perfil_resumen:
            rango = self.perfil.rango_precio_habitual
            rango_txt = f"{rango[0]}-{rango[1]}" if rango else "N/A"
            cepas = ", ".join(c.value for c in self.perfil.cepas_favoritas) or "N/A"
            self.perfil_resumen = (
                f"Cliente {self.perfil.nombre or 'anónimo'} "
                f"(segmento: {self.perfil.segmento.value}, "
                f"perfil: {self.perfil.perfil_tipo.value}, "
                f"compras: {self.perfil.total_compras}). "
                f"Cepas favoritas: {cepas}. "
                f"Rango precio: {rango_txt} ARS."
            )
        return self


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


class VintageItem(BaseModel):
    """Añada de una misma etiqueta, comparada vía SQL."""

    model_config = ConfigDict(extra="forbid")

    producto_id: str
    nombre: str
    bodega: str
    anada: int
    precio: Decimal = Field(gt=0)
    activo: bool = True


class VintageComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    items: list[VintageItem] = Field(default_factory=list)
    mensaje: str | None = None


class DeliveryZoneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    codigo_postal: str
    zona: str
    cubre: bool
    costo_envio: Decimal = Field(ge=0)
    demora_dias: int | None = None
    mensaje: str | None = None


class EventoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    titulo: str
    descripcion: str | None = None
    fecha: datetime
    precio: Decimal = Field(ge=0)
    cupo_total: int = Field(ge=0)
    cupo_disponible: int = Field(ge=0)
    activo: bool = True


class EventsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    eventos: list[EventoItem] = Field(default_factory=list)
    mensaje: str | None = None


class EventReservationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resultado: ResultadoTool
    reserva_id: str | None = None
    evento_id: str | None = None
    cantidad: int | None = None
    total: Decimal | None = None
    estado: str | None = None
    mensaje: str | None = None
