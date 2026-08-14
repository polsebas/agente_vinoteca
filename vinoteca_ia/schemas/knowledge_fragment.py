"""Fragmentos de conocimiento del catálogo (5 capas). Solo RAG cualitativo."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CapaConocimiento(IntEnum):
    """Cinco capas de conocimiento de un vino. El SQL guarda el entero 1–5."""

    DATO_DURO = 1
    """Ficha técnica: varietal, añada, ABV, precio, región."""

    TERRUNO = 2
    """Altura, suelo, clima, valle y micro-clima."""

    HISTORIA = 3
    """Filosofía del enólogo, historia de bodega, decisiones de elaboración."""

    TENDENCIA = 4
    """Tendencia de mercado, natural/orgánico, reconocimiento crítico."""

    VOZ_PROPIA = 5
    """Cata y opinión del sumiller humano de la vinoteca."""


class FuenteConocimiento(StrEnum):
    """Origen del fragmento. Determina autoridad vía `JerarquiaFuente`."""

    SUMILLER = "sumiller"
    BODEGA_OFICIAL = "bodega_oficial"
    CRITICO = "critico"
    REDES_SOCIALES = "redes_sociales"
    CONCURSO = "concurso"


class JerarquiaFuente:
    """Prioridad de autoridad: SUMILLER > BODEGA_OFICIAL > CRITICO > REDES_SOCIALES.

    `CONCURSO` queda último: no forma parte de la cadena de prioridad del diseño.
    Menor índice = mayor autoridad.
    """

    ORDEN: tuple[FuenteConocimiento, ...] = (
        FuenteConocimiento.SUMILLER,
        FuenteConocimiento.BODEGA_OFICIAL,
        FuenteConocimiento.CRITICO,
        FuenteConocimiento.REDES_SOCIALES,
        FuenteConocimiento.CONCURSO,
    )

    @classmethod
    def prioridad(cls, fuente: FuenteConocimiento) -> int:
        try:
            return cls.ORDEN.index(fuente)
        except ValueError:
            return len(cls.ORDEN)

    @classmethod
    def comparar(cls, izquierda: FuenteConocimiento, derecha: FuenteConocimiento) -> int:
        """Negativo si `izquierda` tiene más autoridad que `derecha`."""
        return cls.prioridad(izquierda) - cls.prioridad(derecha)

    @classmethod
    def es_preferida(cls, candidata: FuenteConocimiento, otra: FuenteConocimiento) -> bool:
        return cls.prioridad(candidata) < cls.prioridad(otra)


class KnowledgeFragment(BaseModel):
    """Chunk semántico de una capa de un vino. Nunca contiene precio ni stock."""

    model_config = ConfigDict(extra="forbid")

    id: str
    producto_id: str = Field(description='Slug de producto, ej. "achaval-malbec-2022".')
    capa: CapaConocimiento
    fuente: FuenteConocimiento
    contenido: str = Field(min_length=1)
    validador_humano: bool = False
    version: int = Field(default=1, ge=1)
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
