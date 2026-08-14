"""Guardrails de entrada y salida.

Input: bloquea prompt injection / jailbreak / leak de system prompt.
Enmascara PII (tarjetas con Luhn, DNI, passwords, email, teléfono).
Output: nunca filtra stack traces ni dumps internos al cliente.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# ── PII ────────────────────────────────────────────────────────────────
_CARD_CANDIDATE_RE = re.compile(r"(?:\d[ \-]*?){13,19}")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE_AR_RE = re.compile(r"\b(?:\+54|0)?(?:11|[2-9]\d)\d{7,8}\b")
_DNI_RE = re.compile(
    r"(?i)\b(?:dni|documento(?:\s+nacional)?(?:\s+de\s+identidad)?)\s*[:#]?\s*"
    r"(\d{1,2}\.?\d{3}\.?\d{3})\b"
)
_PASSWORD_RE = re.compile(r"(?i)\b(password|passwd|contrase[nñ]a|clave)\s*[:=]\s*\S+")

# ── Injection / jailbreak ──────────────────────────────────────────────
_JAILBREAK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
    re.compile(r"you\s+are\s+now\s+(?:dan|jailbreak|free)", re.I),
    re.compile(
        r"act\s+as\s+(?:if\s+you\s+(?:are|were)\s+)?(?:an?\s+)?"
        r"(?:evil|uncensored|unethical)",
        re.I,
    ),
    re.compile(r"forget\s+your\s+(rules|guidelines|instructions)", re.I),
    re.compile(r"(?:reveal|show|print|dump)\s+(your\s+)?(system\s+)?prompt", re.I),
    re.compile(r"system\s*prompt", re.I),
    re.compile(r"<\|im_start\|>|<\|im_end\|>|\[INST\]|\[\/INST\]"),
    re.compile(r"###\s*(Human|Assistant|System)\s*:", re.I),
    re.compile(
        r"ignor[aeá]\s+(todas\s+((las|tus)\s+)?)?instrucciones?\s+(anteriores|previas)",
        re.I,
    ),
    re.compile(r"revel[aeá]\s+(el\s+)?(system\s+)?prompt", re.I),
    re.compile(r"mostr[aeá]\s+tu\s+(prompt|instrucci[oó]n)", re.I),
]

_TRACEBACK_BLOCK_RE = re.compile(
    r"Traceback \(most recent call last\):\n"
    r"(?:[ \t].*\n)*"
    r"(?:[A-Za-z_][\w.]*:\s.*\n)?"
)
_FILE_LINE_RE = re.compile(r'File "[^"]+", line \d+[^\n]*')
_INTERNAL_KEYS = frozenset(
    {
        "system_prompt",
        "instructions",
        "stack",
        "traceback",
        "stack_trace",
        "razonamiento",
    }
)


@dataclass
class GuardrailResult:
    bloqueado: bool
    razon: str | None = None
    tipo: str | None = None  # "pii" | "jailbreak"
    sanitized: str = ""


def _luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _mask_cards(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if _luhn_ok(digits):
            return f"****-****-****-{digits[-4:]}"
        if len(digits) == 16:
            return "****-****-****-****"
        return raw

    return _CARD_CANDIDATE_RE.sub(repl, text)


def _mask_pii(text: str) -> str:
    masked = _mask_cards(text)
    masked = _EMAIL_RE.sub("[email]", masked)
    masked = _PHONE_AR_RE.sub("[telefono]", masked)
    masked = _DNI_RE.sub(lambda m: m.group(0).replace(m.group(1), "[dni]"), masked)
    masked = _PASSWORD_RE.sub(
        lambda m: re.split(r"[:=]", m.group(0), maxsplit=1)[0] + "=[redacted]",
        masked,
    )
    return masked


def check_input_guardrails(user_message: str) -> tuple[bool, str, str | None]:
    """Valida el mensaje del usuario antes del orquestador.

    Returns:
        (is_safe, sanitized_message, block_reason). `is_safe=False` solo
        para injection/jailbreak. La PII se enmascara y el mensaje sigue.
    """
    if not user_message or not user_message.strip():
        return True, user_message or "", None

    for pattern in _JAILBREAK_PATTERNS:
        if pattern.search(user_message):
            return (
                False,
                "",
                (
                    "No puedo procesar ese tipo de instrucción. "
                    "Soy un asistente de vinoteca y solo puedo ayudarte con vinos, "
                    "pedidos y consultas."
                ),
            )

    sanitized = _mask_pii(user_message)
    return True, sanitized, None


def verificar_entrada(texto: str) -> GuardrailResult:
    """Compatibilidad: wrapper sobre `check_input_guardrails`."""
    if not texto or not texto.strip():
        return GuardrailResult(bloqueado=False, sanitized=texto or "")

    is_safe, sanitized, reason = check_input_guardrails(texto)
    if not is_safe:
        return GuardrailResult(
            bloqueado=True,
            razon=reason,
            tipo="jailbreak",
            sanitized="",
        )
    tipo = "pii" if sanitized != texto else None
    return GuardrailResult(bloqueado=False, tipo=tipo, sanitized=sanitized)


def sanitize_output(output_text: str) -> str:
    """Elimina traces internos, dumps JSON accidentales y stack traces."""
    if not output_text or not str(output_text).strip():
        return RESPUESTA_FALLBACK_INTERNO

    text = str(output_text)
    text = _TRACEBACK_BLOCK_RE.sub("", text)
    text = _FILE_LINE_RE.sub("", text)
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        extracted = _extract_cliente_text(stripped)
        if extracted:
            return extracted
    if any(key in text.lower() for key in ("traceback", "stack_trace", "system_prompt")):
        text = re.sub(r"(?i)system_prompt\s*[:=]\s*.+", "", text)
        text = re.sub(r"(?i)stack_trace\s*[:=]\s*.+", "", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    return cleaned or RESPUESTA_FALLBACK_INTERNO


def _extract_cliente_text(raw_json: str) -> str | None:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if _INTERNAL_KEYS & set(data):
        for key in ("mensaje_cliente", "respuesta", "message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    mensaje = data.get("mensaje_cliente")
    if isinstance(mensaje, str) and mensaje.strip():
        return mensaje.strip()
    return None


RESPUESTA_BLOQUEADA_PII = (
    "Por tu seguridad, detecté información sensible en tu mensaje. "
    "Por favor no compartas datos de tarjetas de crédito, documentos o teléfonos "
    "en el chat. ¿En qué te puedo ayudar con nuestra selección de vinos?"
)

RESPUESTA_BLOQUEADA_JAILBREAK = (
    "Soy el asistente de la vinoteca y solo puedo ayudarte a elegir vinos, "
    "consultar stock, hacer pedidos o resolver dudas sobre nuestros productos. "
    "¿Qué vino te puedo recomendar hoy?"
)

RESPUESTA_FALLBACK_INTERNO = (
    "Lo siento, en este momento no puedo procesar tu consulta correctamente. "
    "Por favor intentá de nuevo en unos instantes."
)
