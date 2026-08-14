"""DTOs de la API HTTP. Contratos de transporte, no de dominio cognitivo."""

from __future__ import annotations

from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    """Entrada del cliente al canal de chat."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    mensaje: str = Field(
        ...,
        min_length=1,
        description="Texto del usuario.",
        validation_alias=AliasChoices("mensaje", "message"),
    )
    session_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="ID de conversación persistente.",
    )
    cliente_id: str | None = Field(default=None, description="Si el cliente está identificado.")
    stream: bool = Field(
        default=True,
        description="True: SSE. False: JSON AgentResponse.",
    )
    canal: str = Field(default="web", description="web | whatsapp | playground")


class ApproveRequest(BaseModel):
    """Decisión explícita del aprobador humano (HitL)."""

    model_config = ConfigDict(extra="forbid")

    aprobar: bool = Field(..., description="True para continuar, False para rechazar.")
    session_id: str = Field(..., description="Session_id original del chat.")
    nota: str | None = Field(default=None, description="Nota del aprobador.")


class MPWebhookPaymentData(BaseModel):
    """Subconjunto tipado del `data` de Mercado Pago que nos importa."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    external_reference: str | None = None
    status: str | None = None


class MPWebhookPayload(BaseModel):
    """Notificación inbound de Mercado Pago. `extra=ignore` porque el payload es externo."""

    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    action: str | None = None
    data: MPWebhookPaymentData | None = None
    external_reference: str | None = None
    status: str | None = None


class WhatsAppInbound(BaseModel):
    """Inbound WhatsApp (Cloud API o payload simplificado)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    mensaje: str | None = None
    text: str | None = None
    from_number: str | None = Field(default=None, alias="from")
    session_id: str | None = None
    entry: list[dict] | None = None


class MetricasKPI(BaseModel):
    """KPIs operativos del gateway."""

    model_config = ConfigDict(extra="forbid")

    conversaciones_totales: int = 0
    pedidos_totales: int = 0
    tasa_conversion: float = 0.0
    tasa_escalada: float = 0.0
    latencia_promedio_ms: float = 0.0
    costo_tokens_estimado_usd: float = 0.0
    resolution_rate: float = 0.0
    stuck_state_rate: float = 0.0
    avg_tokens_per_session: float = 0.0
