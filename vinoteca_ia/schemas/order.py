"""
Modelos Pydantic para pedidos, líneas y estados del Two-Phase Commit.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class OrderEstado(str, Enum):
    PREPARANDO = "preparando"
    PENDIENTE_APROBACION = "pendiente_aprobacion"
    CONFIRMADO = "confirmado"
    CANCELADO = "cancelado"
    FALLIDO = "fallido"


class TipoEntrega(str, Enum):
    RETIRO = "retiro"
    ENVIO = "envio"


class OrderLineInput(BaseModel):
    """Input del cliente al armar un pedido."""

    vino_id: UUID
    cantidad: int = Field(ge=1, le=100)


class OrderLine(BaseModel):
    """Línea confirmada del pedido con precio snapshot."""

    id: UUID | None = None
    pedido_id: UUID | None = None
    vino_id: UUID
    nombre_vino: str
    cantidad: int
    precio_unitario: float
    subtotal: float


class OrderInput(BaseModel):
    """Lo que el agente de Pedidos arma en Fase 1 para mostrar al cliente."""

    session_id: str
    idempotency_key: str
    items: list[OrderLineInput]
    tipo_entrega: TipoEntrega = TipoEntrega.RETIRO
    direccion: str | None = None
    notas: str | None = None


class OrderResumen(BaseModel):
    """Resumen calculado en Fase 1 para confirmación del cliente (sin mutar nada)."""

    idempotency_key: str
    lineas: list[OrderLine]
    subtotal: float
    total: float
    tipo_entrega: TipoEntrega
    mensaje_confirmacion: str


class Order(BaseModel):
    """Pedido persistido en base de datos."""

    id: UUID
    session_id: str
    estado: OrderEstado
    tipo_entrega: TipoEntrega
    direccion: str | None = None
    subtotal: float | None = None
    total: float | None = None
    idempotency_key: str
    notas: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    lineas: list[OrderLine] = Field(default_factory=list)

    @field_validator("total", "subtotal", mode="before")
    @classmethod
    def total_no_negativo(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("El total no puede ser negativo.")
        return v


class AprobacionInput(BaseModel):
    """Señal HitL que llega al endpoint /aprobar."""

    pedido_id: UUID
    aprobado: bool
    operador_id: str | None = None
    notas: str | None = None


class PaymentLinkResult(BaseModel):
    """Resultado del mock de Mercado Pago."""

    pedido_id: UUID
    url_pago: str
    external_reference: str
    estado: str = "pendiente"
