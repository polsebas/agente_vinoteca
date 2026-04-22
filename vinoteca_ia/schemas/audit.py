"""Contratos del auditor nocturno (LLM-as-a-Judge).

Cada `AuditFinding` es un hallazgo atómico sobre una interacción concreta.
Un `AuditReport` agrega los hallazgos de una corrida.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class AuditSeverity(StrEnum):
    """Gravedad del hallazgo ordenada por impacto de negocio."""

    CRITICA = "critica"
    """Rompe invariantes del sistema: cobro sin orden, precio inventado,
    escalada omitida cuando correspondía. Requiere acción humana inmediata."""

    ALTA = "alta"
    """Viola la constitución pero sin daño consumado. Ej: agente recomendó
    sin consultar stock, pero el cliente no compró."""

    MEDIA = "media"
    """Oportunidad de mejora: tono inadecuado, respuesta demasiado larga,
    tool call redundante."""

    BAJA = "baja"
    """Observación de estilo o eficiencia."""


class AuditCategoria(StrEnum):
    """Taxonomía de hallazgos. Coherente con las constituciones vigentes."""

    HALUCINACION = "halucinacion"
    """El agente afirmó algo que no viene de tools (precio, stock, vino)."""

    TOOL_MAL_USADA = "tool_mal_usada"
    """Invocó la tool equivocada o en el orden equivocado."""

    TOOL_OMITIDA = "tool_omitida"
    """Debió invocar una tool y no lo hizo (ej. no verificó stock)."""

    ESCALADA_TARDIA = "escalada_tardia"
    """Support no escaló cuando la política exigía escalar."""

    ESCALADA_INNECESARIA = "escalada_innecesaria"
    """Support escaló antes de intentar la FAQ."""

    DOSFC_VIOLADO = "2pc_violado"
    """Orders ejecutó `crear_orden` sin confirmación del cliente, o cobró
    sin orden APROBADA."""

    TONO_INAPROPIADO = "tono_inapropiado"
    """Respuesta soberbia, fría, o inconsistente con el tono argentino."""

    RESPUESTA_INUTIL = "respuesta_inutil"
    """El cliente quedó sin respuesta concreta cuando había datos disponibles."""

    OTRO = "otro"


class AuditFinding(BaseModel):
    """Un hallazgo concreto sobre una run/turno específicos."""

    model_config = ConfigDict(extra="forbid")

    finding_id: UUID = Field(default_factory=uuid4)
    run_id: str = Field(..., description="ID del run auditado (de agno DB).")
    session_id: str | None = Field(default=None)
    agente_nombre: str = Field(..., description="Ej: agente_sommelier, agente_orders.")
    severidad: AuditSeverity
    categoria: AuditCategoria
    descripcion: str = Field(..., min_length=10, max_length=1000)
    evidencia: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Cita textual del input/output que respalda el hallazgo.",
    )
    recomendacion: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Acción concreta para el equipo (ajustar prompt, nueva tool, etc.).",
    )
    detectado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditReport(BaseModel):
    """Reporte agregado de una corrida del auditor."""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID = Field(default_factory=uuid4)
    ventana_desde: datetime
    ventana_hasta: datetime
    runs_evaluados: int = Field(..., ge=0)
    findings: list[AuditFinding] = Field(default_factory=list)
    resumen_ejecutivo: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Párrafo operativo: qué pasó en la ventana, qué atender primero.",
    )
    generado_en: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def criticas(self) -> int:
        return sum(1 for f in self.findings if f.severidad == AuditSeverity.CRITICA)

    @property
    def altas(self) -> int:
        return sum(1 for f in self.findings if f.severidad == AuditSeverity.ALTA)
