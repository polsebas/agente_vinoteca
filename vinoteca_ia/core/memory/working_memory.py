"""Memoria de trabajo: ventana deslizante de 8 turnos en la sesión activa."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

WINDOW_SIZE = 8
SUMMARIZE_AFTER = 12


class WorkingMemory:
    """Historial reciente de la sesión. Stateless respecto al proceso: el
    orquestador posee la instancia y la hidrata turno a turno.

    `get_context_window()` nunca devuelve más de `WINDOW_SIZE` turnos. Cuando
    el historial llega a `SUMMARIZE_AFTER`, se comprimen los turnos viejos
    con el summarizer (preferencias, vinos mencionados, carrito).
    """

    def __init__(
        self,
        session_id: str | None = None,
        max_window: int = WINDOW_SIZE,
    ) -> None:
        self.session_id = session_id
        self._max_window = max_window
        self._turns: list[dict[str, Any]] = []
        self._summary: str | None = None

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    @property
    def summary(self) -> str | None:
        return self._summary

    def add_turn(self, role: str, content: str) -> None:
        """Agrega un turno. Dispara compresión si el historial ≥ 12."""
        self._turns.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._turns) >= SUMMARIZE_AFTER:
            self._refresh_summary()

    def get_context_window(self) -> list[dict]:
        """Últimos 8 turnos (vista, no copia profunda de campos mutables)."""
        return [dict(t) for t in self._turns[-self._max_window :]]

    def clear(self) -> None:
        self._turns.clear()
        self._summary = None

    def _refresh_summary(self) -> None:
        from core.memory.summarizer import summarize_history

        older = self._turns[: -self._max_window]
        if older:
            self._summary = summarize_history(older)
