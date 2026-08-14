"""Entrada y salida tipada de cada agente.

Cada agente declara su `output_schema` con uno de estos modelos. Temperatura 0.0
garantiza que el LLM emite el JSON correcto de forma determinista.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from schemas.order import OrderLineItem
from schemas.wine_catalog import CatalogId


class IntentClass(StrEnum):
    """Clases cerradas de intención que el router puede emitir."""

    RECOMENDACION_OCASION = "recomendacion_ocasion"
    RECOMENDACION_REGALO = "recomendacion_regalo"
    MARIDAJE = "maridaje"
    CONSULTA_STOCK_PRECIO = "consulta_stock_precio"
    PEDIDO_DELIVERY = "pedido_delivery"
    EVENTO_DEGUSTACION = "evento_degustacion"
    SOPORTE_RECLAMO = "soporte_reclamo"
    DESCONOCIDO = "desconocido"
    # Aliases históricos (mismos strings que las clases canónicas).
    RECOMENDACION = "recomendacion_ocasion"
    CONSULTA_INVENTARIO = "consulta_stock_precio"
    PEDIDO = "pedido_delivery"
    SOPORTE = "soporte_reclamo"
    EVENTO = "evento_degustacion"


class AgenteDestino(StrEnum):
    """Agentes especialistas disponibles para derivación.

    Debe coincidir con los `members` del Team router (`router_team.py`).
    """

    SOMMELIER = "agente_sommelier"
    ORDERS = "agente_orders"
    INVENTORY = "agente_inventario"
    SUPPORT = "agente_support"
    EVENTS = "agente_events"
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
    accion_nula: bool = Field(
        default=False,
        description="True si confianza < 0.85 o el mensaje es ambiguo.",
    )
    pregunta_aclaracion: str | None = Field(
        default=None,
        description="Pregunta al cliente cuando accion_nula=True.",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Propagar el correlation_id del request. Formato corr_<session_id>.",
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

    vino_id: CatalogId
    nombre: str
    precio_ars: Decimal | None = None
    razon_recomendacion: str


class SommelierResponse(BaseModel):
    """Respuesta estructurada del sumiller.

    NUNCA inventa vinos ni precios: los `sugeridos` vienen exclusivamente del
    resultado de las tools (SQL / RAG indexado).
    """

    model_config = ConfigDict(extra="forbid")

    mensaje_cliente: str
    sugeridos: list[VinoSugerido] = Field(default_factory=list, max_length=3)
    requiere_mas_info: bool = False


LineaResumenPedido = OrderLineItem


class OrderResponse(BaseModel):
    """Respuesta del agente de pedidos.

    En Fase 1 devuelve `requiere_aprobacion=True` y el resumen. En Fase 2 devuelve
    `requiere_aprobacion=False` y `payment_link` poblado.
    """

    model_config = ConfigDict(extra="forbid")

    mensaje_cliente: str
    order_id: str | None = None
    lineas: list[OrderLineItem] = Field(default_factory=list)
    total_ars: Decimal | None = None
    requiere_aprobacion: bool = False
    payment_link: str | None = None


class SupportResponse(BaseModel):
    """Respuesta del agente de soporte."""

    model_config = ConfigDict(extra="forbid")

    mensaje_cliente: str
    escalado_a_humano: bool = False
    ticket_id: str | None = None


class InventoryResponse(BaseModel):
    """Respuesta del agente de inventario (SQL puro)."""

    model_config = ConfigDict(extra="forbid")

    mensaje_cliente: str
    encontrado: bool = True


class EventsResponse(BaseModel):
    """Respuesta del agente de eventos (catas y reservas)."""

    model_config = ConfigDict(extra="forbid")

    mensaje_cliente: str
    reserva_id: str | None = None
    requiere_confirmacion: bool = False
