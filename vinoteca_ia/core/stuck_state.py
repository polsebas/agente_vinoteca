"""
Detección de Stuck State: el agente repite el mismo tool call sin avanzar.
El orquestador invoca esto en cada paso del bucle PRAO.
"""

from __future__ import annotations

from collections import deque


class StuckStateDetector:
    """
    Detecta cuando el agente repite la misma herramienta con los mismos
    argumentos 2 o más veces consecutivas dentro de la misma sesión.
    """

    def __init__(self, ventana: int = 2) -> None:
        self._ventana = ventana
        self._historial: deque[str] = deque(maxlen=ventana)

    def registrar(self, tool_name: str, args_repr: str) -> None:
        self._historial.append(f"{tool_name}:{args_repr}")

    def esta_atascado(self) -> bool:
        if len(self._historial) < self._ventana:
            return False
        return len(set(self._historial)) == 1

    def reset(self) -> None:
        self._historial.clear()
