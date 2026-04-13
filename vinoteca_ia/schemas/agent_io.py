"""
Contratos de entrada/salida para la comunicación entre canal, orquestador y agentes.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IntentClass(str, Enum):
    RECOMENDACION = "recomendacion"
    MARIDAJE = "maridaje"
    CONSULTA_INVENTARIO = "consulta_inventario"
    PEDIDO = "pedido"
    SOPORTE = "soporte"
    EVENTO = "evento"
    DESCONOCIDO = "desconocido"


class PerfilCliente(str, Enum):
    COLECCIONISTA = "coleccionista"
    CURIOSO = "curioso"
    OCASION = "ocasion"
    DESCONOCIDO = "desconocido"


class SessionRequest(BaseModel):
    """Request validado que el API Gateway envía al orquestador."""

    mensaje: str = Field(..., min_length=1, max_length=2000)
    session_id: str
    correlation_id: str
    canal: str = "web"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentHandoff(BaseModel):
    """Mandato que el orquestador entrega a un agente especialista."""

    agente_destino: str
    intencion: IntentClass
    session_id: str
    correlation_id: str
    mensaje_original: str
    perfil_cliente: PerfilCliente = PerfilCliente.DESCONOCIDO
    contexto: dict[str, Any] = Field(default_factory=dict)
    confianza: float = Field(ge=0.0, le=1.0, default=1.0)


class AgentResponse(BaseModel):
    """Respuesta estructurada de cualquier agente al orquestador."""

    session_id: str
    correlation_id: str
    respuesta: str
    agente: str
    intencion: IntentClass
    metadata: dict[str, Any] = Field(default_factory=dict)
    requiere_aprobacion: bool = False
    pedido_id: str | None = None
    finalizado: bool = True


class RouterOutput(BaseModel):
    """Salida tipada del Agente Enrutador."""

    intencion: IntentClass
    confianza: float = Field(ge=0.0, le=1.0)
    agente_destino: str
    razonamiento: str | None = None


class ChatResponse(BaseModel):
    """Respuesta del endpoint /chat al frontend."""

    session_id: str
    correlation_id: str
    respuesta: str
    requiere_aprobacion: bool = False
    pedido_id: str | None = None
