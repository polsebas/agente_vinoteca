"""Modelos de pedido. Crítico: todo pedido pasa por Two-Phase Commit."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class EstadoOrden(StrEnum):
    """Estados posibles de una orden."""

    PREPARADA = "preparada"
    APROBADA = "aprobada"
    PAGADA = "pagada"
    CANCELADA = "cancelada"
    FALLIDA = "fallida"


class OrderLine(BaseModel):
    """Línea individual de un pedido."""

    model_config = ConfigDict(extra="forbid")

    vino_id: UUID
    nombre_vino: str
    cantidad: int = Field(ge=1)
    precio_unitario_ars: Decimal = Field(gt=0, decimal_places=2)
    subtotal_ars: Decimal = Field(gt=0, decimal_places=2)


class Order(BaseModel):
    """Pedido completo. Se crea en estado PREPARADA (Fase 1) y pasa a
    APROBADA solo tras confirmación explícita del cliente (Fase 2).
    """

    model_config = ConfigDict(extra="forbid")

    order_id: UUID = Field(default_factory=uuid4)
    session_id: str
    cliente_id: str | None = None
    idempotency_key: str
    lineas: list[OrderLine] = Field(min_length=1)
    subtotal_ars: Decimal = Field(gt=0, decimal_places=2)
    envio_ars: Decimal = Field(ge=0, decimal_places=2, default=Decimal("0.00"))
    total_ars: Decimal = Field(gt=0, decimal_places=2)
    estado: EstadoOrden = EstadoOrden.PREPARADA
    payment_link: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_at: datetime | None = None
