"""Contratos de datasets de evaluación (golden y adversarial)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClientProfileKind(StrEnum):
    COLECCIONISTA = "coleccionista"
    CURIOSO = "curioso"
    OCASION = "ocasion"


class AttackType(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    PII_EXTRACTION = "pii_extraction"
    PREMATURE_CHARGE = "premature_charge"
    STOCK_HALLUCINATION = "stock_hallucination"
    PRICE_OVERRIDE = "price_override"


class GoldenExample(BaseModel):
    """Par de referencia para el Judge / evals offline."""

    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    client_profile: Literal["coleccionista", "curioso", "ocasion"]
    input: str = Field(min_length=1)
    expected_intent: str
    expected_tools: list[str] = Field(default_factory=list)
    expected_response_elements: list[str] = Field(default_factory=list)
    expected_layer: int = Field(ge=1, le=5)


class AdversarialExample(BaseModel):
    """Caso de regresión / ataque para guardrails y 2PC."""

    model_config = ConfigDict(extra="forbid")

    id: str
    attack_type: AttackType
    input: str = Field(min_length=1)
    expected_behavior: str
    expected_guardrail_block: bool
