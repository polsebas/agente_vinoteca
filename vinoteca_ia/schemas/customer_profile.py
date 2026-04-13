"""
Perfil del cliente: preferencias persistidas y contexto cargado por el Sumiller.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from schemas.agent_io import PerfilCliente


class CustomerProfile(BaseModel):
    id: UUID | None = None
    canal: str
    canal_user_id: str
    tipo_perfil: PerfilCliente = PerfilCliente.DESCONOCIDO
    preferencias: dict = Field(default_factory=dict)
    historial_ids: list[UUID] = Field(default_factory=list)
