"""
Generación y propagación del Correlation ID por conversación.
Formato: sess_{canal}_{timestamp_ms}_{random6}
"""

from __future__ import annotations

import random
import string
import time
from contextvars import ContextVar

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def generar(canal: str = "web") -> str:
    ts = int(time.time() * 1000)
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"sess_{canal}_{ts}_{suffix}"


def set_current(correlation_id: str) -> None:
    _correlation_id_var.set(correlation_id)


def get_current() -> str:
    return _correlation_id_var.get()
