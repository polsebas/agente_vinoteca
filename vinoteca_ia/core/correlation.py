"""Generación y propagación del Correlation ID por conversación.

Formatos:
- `generate_correlation_id(session_id)` → `corr_<session_id>_<timestamp>`
- `generar(canal)` → `sess_{canal}_{timestamp_ms}_{random6}` (compat)
"""

from __future__ import annotations

import random
import re
import string
import time
from contextvars import ContextVar

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
_SAFE_ID = re.compile(r"[^a-zA-Z0-9_-]+")


def generate_correlation_id(session_id: str) -> str:
    """Correlation id canónico: `corr_<session_id>_<timestamp_ms>`."""
    safe = _SAFE_ID.sub("_", session_id.strip()) or "anon"
    ts = int(time.time() * 1000)
    return f"corr_{safe}_{ts}"


def generar(canal: str = "web") -> str:
    ts = int(time.time() * 1000)
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"sess_{canal}_{ts}_{suffix}"


def set_current(correlation_id: str) -> None:
    _correlation_id_var.set(correlation_id)


def get_current() -> str:
    return _correlation_id_var.get()
