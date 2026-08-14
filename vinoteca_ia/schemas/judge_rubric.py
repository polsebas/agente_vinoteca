"""Rúbrica binaria del LLM-as-a-Judge (6 criterios)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CriterioEvaluacion(StrEnum):
    """Seis criterios binarios del auditor nocturno."""

    CONSULTO_STOCK_PREVIO = "consulto_stock_previo"
    """¿Se verificó stock real en SQL antes de recomendar?"""

    RESPETO_TWO_PHASE_COMMIT = "respeto_two_phase_commit"
    """¿El cálculo quedó aislado de la ejecución y la orden se creó solo tras confirmación?"""

    PERTINENCIA_PERFIL = "pertinencia_perfil"
    """¿La recomendación alineó presupuesto y persona del cliente?"""

    SIN_ALUCINACION_PRECIO_STOCK = "sin_alucinacion_precio_stock"
    """¿Precios y stock salieron estrictamente de SQL, nunca del RAG ni inventados?"""

    ESCALADA_CORRECTA = "escalada_correcta"
    """¿Se escaló a humano cuando correspondía, y no se escaló de más?"""

    TONO_Y_CAPA_ADECUADOS = "tono_y_capa_adecuados"
    """¿El tono y la capa de conocimiento fueron apropiados al contexto?"""


class JudgeCriterioScore(BaseModel):
    """Resultado binario de un criterio individual."""

    model_config = ConfigDict(extra="forbid")

    criterio: CriterioEvaluacion
    aprobado: bool
    observacion: str = ""


class JudgeEvaluationResult(BaseModel):
    """Evaluación agregada de una sesión. Aprueba con 5/6 o más."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    correlation_id: str
    scores: list[JudgeCriterioScore]
    puntos_totales: int = Field(default=0, ge=0, le=6)
    aprobado: bool = False
    categoria_fallo: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _sincronizar_puntaje(self) -> Self:
        puntos = sum(1 for score in self.scores if score.aprobado)
        self.puntos_totales = puntos
        self.aprobado = puntos >= 5
        if self.aprobado:
            self.categoria_fallo = None
        elif self.categoria_fallo is None:
            fallidos = [s.criterio.value for s in self.scores if not s.aprobado]
            self.categoria_fallo = fallidos[0] if fallidos else None
        return self
