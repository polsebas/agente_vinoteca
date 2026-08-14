"""Alertas técnicas y de negocio. Logging + hooks (webhook opcional)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("vinoteca.observability.alerts")

AlertHook = Callable[[str, str, str, dict[str, Any]], None]


class AlertManager:
    """Dispara alertas estructuradas. Los hooks cubren webhooks/PagerDuty/etc."""

    def __init__(self, *, webhook_url: str | None = None) -> None:
        self.webhook_url = webhook_url or os.environ.get("ALERT_WEBHOOK_URL")
        self._hooks: list[AlertHook] = []
        self._history: list[dict[str, Any]] = []

    def add_hook(self, hook: AlertHook) -> None:
        self._hooks.append(hook)

    def trigger_alert(
        self,
        level: str,
        category: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Registra la alerta, la loguea y notifica hooks (fail-open)."""
        record: dict[str, Any] = {
            "level": level,
            "category": category,
            "message": message,
            "metadata": metadata or {},
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._history.append(record)
        log_fn = logger.error if level in {"error", "critical"} else logger.warning
        log_fn(
            "alerta_%s category=%s message=%s",
            level,
            category,
            message,
            extra={"metadata": record["metadata"]},
        )
        payload = dict(record)
        for hook in self._hooks:
            try:
                hook(level, category, message, payload)
            except Exception as exc:
                logger.warning("hook de alerta falló: %s", exc)
        if self.webhook_url:
            self._post_webhook(payload)
        return record

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._history[-limit:])

    def reset(self) -> None:
        self._history.clear()
        self._hooks.clear()

    def _post_webhook(self, payload: dict[str, Any]) -> None:
        try:
            import httpx

            httpx.post(self.webhook_url, json=payload, timeout=2.0)
        except Exception as exc:
            logger.warning("webhook de alerta failopen: %s", exc)


_MANAGER: AlertManager | None = None


def get_alert_manager() -> AlertManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = AlertManager()
    return _MANAGER


def reset_alert_manager() -> None:
    global _MANAGER
    if _MANAGER is not None:
        _MANAGER.reset()
    _MANAGER = AlertManager()
