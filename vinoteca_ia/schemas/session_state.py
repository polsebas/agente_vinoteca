"""
Estado inmutable de sesión. Nunca usar diccionarios libres para persistir contexto.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from schemas.agent_io import IntentClass, PerfilCliente


class TurnoHistorial(BaseModel):
    """Un turno de conversación (usuario o agente)."""

    rol: str  # "user" | "assistant" | "tool"
    contenido: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agente: str | None = None
    tool_name: str | None = None


class SessionState(BaseModel):
    """
    Estado inmutable de sesión. No usar dicts libres.
    Se persiste en sesiones_agente y se reconstruye en cada turno.
    """

    session_id: str
    correlation_id: str
    canal: str = "web"
    perfil_cliente: PerfilCliente = PerfilCliente.DESCONOCIDO
    intencion_actual: IntentClass = IntentClass.DESCONOCIDO
    historial: list[TurnoHistorial] = Field(default_factory=list)
    pedido_pendiente_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    pasos_actuales: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def agregar_turno(self, rol: str, contenido: str, **kwargs: Any) -> "SessionState":
        """Retorna una nueva instancia con el turno agregado (inmutabilidad)."""
        nuevo_turno = TurnoHistorial(rol=rol, contenido=contenido, **kwargs)
        return self.model_copy(
            update={
                "historial": self.historial + [nuevo_turno],
                "pasos_actuales": self.pasos_actuales + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    def ultimos_turnos(self, n: int = 8) -> list[TurnoHistorial]:
        """Ventana deslizante de los últimos n turnos para el contexto del LLM."""
        return self.historial[-n:]
