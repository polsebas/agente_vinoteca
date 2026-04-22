"""Entrada y salida tipada de cada agente.

Cada agente declara su `output_schema` con uno de estos modelos. Temperatura 0.0
garantiza que el LLM emite el JSON correcto de forma determinista.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IntentClass(StrEnum):
    """Clases cerradas de intención que el router puede emitir."""

    RECOMENDACION = "recomendacion"
    MARIDAJE = "maridaje"
    CONSULTA_INVENTARIO = "consulta_inventario"
    PEDIDO = "pedido"
    SOPORTE = "soporte"
    EVENTO = "evento"
    DESCONOCIDO = "desconocido"


class AgenteDestino(StrEnum):
    """Agentes especialistas disponibles para derivación.

    Debe coincidir con los `members` del Team router (`router_team.py`):
    sommelier, orders, support. No existe agente de eventos separado: la
    intención `evento` se deriva a soporte (catas, reservas, info de local).
    """

    SOMMELIER = "agente_sommelier"
    ORDERS = "agente_orders"
    SUPPORT = "agente_support"
    NINGUNO = "ninguno"


class RouterOutput(BaseModel):
    """Decisión de ruteo. Temperatura 0.0 + confianza mínima 0.85 o derivación nula."""

    model_config = ConfigDict(extra="forbid")

    intencion: IntentClass
    confianza: float = Field(ge=0.0, le=1.0)
    agente_destino: AgenteDestino
    razonamiento: str = Field(
        description="Una oración. Invisible al cliente. Sirve para tracing.",
    )


class SessionRequest(BaseModel):
    """Mensaje entrante al orquestador (canal → router)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    correlation_id: str
    mensaje: str = Field(..., min_length=1)
    cliente_id: str | None = None


class AgentResponse(BaseModel):
    """Salida unificada del orquestador hacia la capa de transporte."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    correlation_id: str
    respuesta: str
    agente: str
    intencion: IntentClass
    finalizado: bool = True
    metadata: dict[str, str] | None = None
    requiere_aprobacion: bool = False


class VinoSugerido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vino_id: UUID
    nombre: str
    precio_ars: Decimal
    razon_recomendacion: str


class SommelierResponse(BaseModel):
    """Respuesta estructurada del sumiller.

    NUNCA inventa vinos ni precios: los `sugeridos` vienen exclusivamente del
    resultado de las tools (SQL / RAG indexado).
    """

    model_config = ConfigDict(extra="forbid")

    mensaje_cliente: str
    sugeridos: list[VinoSugerido] = Field(default_factory=list, max_length=5)
    requiere_mas_info: bool = False


class LineaResumenPedido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vino_id: UUID
    nombre: str
    cantidad: int = Field(ge=1)
    precio_unitario_ars: Decimal
    subtotal_ars: Decimal


class OrderResponse(BaseModel):
    """Respuesta del agente de pedidos.

    En Fase 1 devuelve `requiere_aprobacion=True` y el resumen. En Fase 2 devuelve
    `requiere_aprobacion=False` y `payment_link` poblado.
    """

    model_config = ConfigDict(extra="forbid")

    mensaje_cliente: str
    order_id: UUID | None = None
    lineas: list[LineaResumenPedido] = Field(default_factory=list)
    total_ars: Decimal | None = None
    requiere_aprobacion: bool = False
    payment_link: str | None = None


class SupportResponse(BaseModel):
    """Respuesta del agente de soporte."""

    model_config = ConfigDict(extra="forbid")

    mensaje_cliente: str
    escalado_a_humano: bool = False
    ticket_id: str | None = None
