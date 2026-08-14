"""Detección de Stuck State: el agente repite el mismo tool call sin avanzar.

El orquestador invoca esto en cada paso del bucle PRAO. `is_stuck=True` si
la misma herramienta (mismos parámetros) o el mismo error se registra 3
veces consecutivas.
"""

from __future__ import annotations

from collections import deque


class StuckStateDetector:
    """Detecta repetición de tool+args o errores consecutivos."""

    def __init__(self, ventana: int = 3) -> None:
        self._ventana = ventana
        self._historial: deque[str] = deque(maxlen=ventana)

    def registrar(self, tool_name: str, args_repr: str) -> bool:
        """Registra una firma. Devuelve True si a partir de ahora está atascado."""
        self._historial.append(f"{tool_name}:{args_repr}")
        return self.esta_atascado()

    def registrar_error(self, error: str) -> bool:
        return self.registrar("__error__", error)

    def esta_atascado(self) -> bool:
        if len(self._historial) < self._ventana:
            return False
        return len(set(self._historial)) == 1

    @property
    def is_stuck(self) -> bool:
        return self.esta_atascado()

    def reset(self) -> None:
        self._historial.clear()
