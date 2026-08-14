"""Estado de sesión tipado. Nunca se persiste como dict libre."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.customer_profile import PerfilClienteTipo
from schemas.order import CalculatedOrder


class Canal(StrEnum):
    """Canal por el que entra el mensaje del cliente."""

    WEB = "web"
    WHATSAPP = "whatsapp"
    PLAYGROUND = "playground"


class EstadoPedidoPendiente(StrEnum):
    """Estado del Two-Phase Commit para un pedido en curso."""

    NINGUNO = "ninguno"
    PREPARADO = "preparado"
    APROBADO = "aprobado"
    RECHAZADO = "rechazado"


class TurnoHistorial(BaseModel):
    """Un turno individual del diálogo."""

    model_config = ConfigDict(extra="forbid")

    rol: str
    contenido: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agente: str | None = None
    tool_name: str | None = None


class SessionState(BaseModel):
    """Estado inmutable de la sesión de un cliente.

    Se reconstruye en cada turno desde Postgres. Las mutaciones devuelven
    copias nuevas (nunca in-place) para preservar inmutabilidad del estado
    cognitivo del agente.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    correlation_id: str
    cliente_id: str | None = None
    canal: Canal = Canal.WEB
    historial: list[TurnoHistorial] = Field(default_factory=list)
    pedido_pendiente_id: UUID | None = None
    pedido_pendiente_estado: EstadoPedidoPendiente = EstadoPedidoPendiente.NINGUNO
    pedido_en_preparacion: CalculatedOrder | None = None
    perfil_inferido: PerfilClienteTipo = PerfilClienteTipo.GENERAL
    run_id_pausado: str | None = None
    pasos_actuales: int = 0
    max_pasos: int = 5
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def con_turno(self, rol: str, contenido: str, **kwargs: str) -> SessionState:
        turno = TurnoHistorial(rol=rol, contenido=contenido, **kwargs)
        return self.model_copy(
            update={
                "historial": [*self.historial, turno],
                "pasos_actuales": self.pasos_actuales + 1,
                "updated_at": datetime.now(UTC),
            }
        )

    def ultimos_turnos(self, n: int = 8) -> list[TurnoHistorial]:
        return self.historial[-n:]
