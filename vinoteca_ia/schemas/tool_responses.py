"""
Respuestas tipadas de todas las tools. El agente nunca recibe diccionarios libres.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from schemas.wine_catalog import StockInfo


class StockQueryResult(BaseModel):
    """Resultado de consultar_stock. Fuente: SQL exclusivamente."""

    items: list[StockInfo]
    todos_disponibles: bool


class PriceQueryResult(BaseModel):
    """Resultado de consultar_precio. Fuente: SQL exclusivamente."""

    vino_id: UUID
    nombre: str
    precio: float
    moneda: str = "ARS"
    valido: bool = True
    razon_invalido: str | None = None


class OrderCalculation(BaseModel):
    """Cálculo del pedido en Fase 1 (sin mutaciones). Fuente: SQL."""

    lineas: list[dict]
    subtotal: float
    envio: float = 0.0
    total: float
    tipo_entrega: str
    advertencias: list[str] = []


class OrderCreationResult(BaseModel):
    """Resultado de crear_pedido en Fase 2 (con mutación)."""

    pedido_id: UUID
    idempotency_key: str
    estado: str
    total: float


class PaymentResult(BaseModel):
    """Resultado del envío de link de pago (mock en desarrollo)."""

    pedido_id: UUID
    url_pago: str
    external_reference: str
    es_mock: bool = True


class RAGResult(BaseModel):
    """Fragmento recuperado del vector store. Solo texto cualitativo."""

    vino_id: UUID
    nombre_vino: str
    capa: int
    contenido: str
    score: float
