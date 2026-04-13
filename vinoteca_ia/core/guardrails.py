"""
Guardrails de entrada: detección de PII, jailbreak y prompt injection.
Aplicar ANTES de enviar el mensaje al orquestador.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Patrones de PII básicos
_PII_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\d{16}\b"),                                    # tarjeta de crédito
    re.compile(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"),            # SSN (formato US)
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b"),  # email
    re.compile(r"\b(?:\+54|0)?(?:11|[2-9]\d)\d{7,8}\b"),         # teléfono argentino
]

# Frases de jailbreak y prompt injection más comunes
_JAILBREAK_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
    re.compile(r"you\s+are\s+now\s+(?:dan|jailbreak|free)", re.I),
    re.compile(r"act\s+as\s+(?:if\s+you\s+(?:are|were)\s+)?(?:an?\s+)?(?:evil|uncensored|unethical)", re.I),
    re.compile(r"forget\s+your\s+(rules|guidelines|instructions)", re.I),
    re.compile(r"system\s*prompt", re.I),
    re.compile(r"<\|im_start\|>|<\|im_end\|>|\[INST\]|\[\/INST\]"),  # tokens de sistema
    re.compile(r"###\s*(Human|Assistant|System)\s*:", re.I),
]


@dataclass
class GuardrailResult:
    bloqueado: bool
    razon: str | None = None
    tipo: str | None = None  # "pii" | "jailbreak"


def verificar_entrada(texto: str) -> GuardrailResult:
    """
    Invocar con cada mensaje entrante del usuario antes de pasarlo al agente.
    Si bloqueado=True, responder con el mensaje seguro y no continuar.
    """
    if not texto or not texto.strip():
        return GuardrailResult(bloqueado=False)

    for pattern in _PII_PATTERNS:
        if pattern.search(texto):
            return GuardrailResult(
                bloqueado=True,
                razon="El mensaje contiene información personal sensible (PII). "
                      "Por favor no compartas datos de tarjetas, documentos o teléfonos.",
                tipo="pii",
            )

    for pattern in _JAILBREAK_PATTERNS:
        if pattern.search(texto):
            return GuardrailResult(
                bloqueado=True,
                razon="No puedo procesar ese tipo de instrucción. "
                      "Soy un asistente de vinoteca y solo puedo ayudarte con vinos, pedidos y consultas.",
                tipo="jailbreak",
            )

    return GuardrailResult(bloqueado=False)


RESPUESTA_BLOQUEADA_PII = (
    "Por tu seguridad, detecté información sensible en tu mensaje. "
    "Por favor no compartas datos de tarjetas de crédito, documentos o teléfonos en el chat. "
    "¿En qué te puedo ayudar con nuestra selección de vinos?"
)

RESPUESTA_BLOQUEADA_JAILBREAK = (
    "Soy el asistente de la vinoteca y solo puedo ayudarte a elegir vinos, "
    "consultar stock, hacer pedidos o resolver dudas sobre nuestros productos. "
    "¿Qué vino te puedo recomendar hoy?"
)
