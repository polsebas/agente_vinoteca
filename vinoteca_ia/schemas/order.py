"""Modelos de pedido. Crítico: todo pedido pasa por Two-Phase Commit."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class EstadoOrden(StrEnum):
    """Estados posibles de una orden (Fase 1 = PREPARADA)."""

    PREPARADA = "preparada"
    APROBADA = "aprobada"
    PAGADA = "pagada"
    CANCELADA = "cancelada"
    FALLIDA = "fallida"


# Alias de compatibilidad para tests/código que usaba el nombre anterior.
OrderEstado = EstadoOrden


class TipoEntrega(StrEnum):
    ENVIO_DOMICILIO = "envio_domicilio"
    RETIRO_LOCAL = "retiro_local"


class LineaPedidoSolicitud(BaseModel):
    """Línea de entrada a las tools (sin precios). Los precios salen de SQL."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    producto_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("producto_id", "vino_id"),
    )
    cantidad: int = Field(gt=0)


class OrderLineItem(BaseModel):
    """Línea individual de un pedido, con precios autoritativos de SQL."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    producto_id: str = Field(validation_alias=AliasChoices("producto_id", "vino_id"))
    nombre: str = Field(validation_alias=AliasChoices("nombre", "nombre_vino"))
    cantidad: int = Field(gt=0)
    precio_unitario: Decimal = Field(
        ge=0,
        decimal_places=2,
        validation_alias=AliasChoices("precio_unitario", "precio_unitario_ars"),
    )
    subtotal: Decimal = Field(
        ge=0,
        decimal_places=2,
        validation_alias=AliasChoices("subtotal", "subtotal_ars"),
    )

    @property
    def vino_id(self) -> str:
        return self.producto_id


# Alias histórico usado por tools previas a la unificación del contrato.
OrderLine = OrderLineItem


class CalculatedOrder(BaseModel):
    """Fase 1 del 2PC: cálculo determinista, todavía no persistido ni cobrado."""

    model_config = ConfigDict(extra="forbid")

    lineas: list[OrderLineItem] = Field(min_length=1)
    subtotal: Decimal = Field(ge=0, decimal_places=2)
    descuento: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    costo_envio: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    total: Decimal = Field(ge=0, decimal_places=2)
    tipo_entrega: TipoEntrega = TipoEntrega.ENVIO_DOMICILIO
    requiere_confirmacion: bool = True


class Order(BaseModel):
    """Pedido persistido. Nace PREPARADA y pasa a APROBADA solo tras HitL."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        validation_alias=AliasChoices("id", "order_id"),
    )
    session_id: str
    cliente_id: str | None = None
    lineas: list[OrderLineItem] = Field(min_length=1)
    total: Decimal = Field(
        gt=0,
        decimal_places=2,
        validation_alias=AliasChoices("total", "total_ars"),
    )
    estado: EstadoOrden = EstadoOrden.PREPARADA
    tipo_entrega: TipoEntrega = TipoEntrega.ENVIO_DOMICILIO
    idempotency_key: str
    payment_link: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def order_id(self) -> str:
        return self.id

    @property
    def total_ars(self) -> Decimal:
        return self.total


class ConfirmedOrder(Order):
    """Orden ya confirmada (Fase 2 del 2PC)."""

    estado: EstadoOrden = EstadoOrden.APROBADA


class OrderStatusLine(BaseModel):
    """Línea proyectada en la consulta de estado (sin dicts libres)."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    cantidad: int = Field(gt=0)
    precio_unitario: Decimal = Field(ge=0)
    subtotal: Decimal = Field(ge=0)


class OrderStatusResponse(BaseModel):
    """Estado actual de un pedido para el agente o el cliente."""

    model_config = ConfigDict(extra="forbid")

    pedido_id: str
    estado: str
    total: Decimal | None = None
    tipo_entrega: TipoEntrega | None = None
    lineas: list[OrderStatusLine] = Field(default_factory=list)
    encontrado: bool
