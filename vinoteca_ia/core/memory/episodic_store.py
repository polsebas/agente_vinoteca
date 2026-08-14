"""Memoria episódica: compras, estados de pedido y logs de interacción.

Append-only. Lee `pedidos` / `log_inmutable`. Nunca usa RAG para montos
ni estados transaccionales.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from storage.immutable_log import log_transaction_event
from storage.postgres import fetch_all


class EpisodicOrder(BaseModel):
    """Cabecera de un pedido histórico (SQL, no RAG)."""

    model_config = ConfigDict(extra="forbid")

    pedido_id: str
    estado: str
    total: Decimal | None = None
    session_id: str | None = None
    cliente_id: str | None = None
    created_at: datetime | None = None


class InteractionRecord(BaseModel):
    """Turno o evento de sesión persistido en el log inmutable."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    accion: str
    resultado: str
    timestamp: datetime
    contenido: str | None = None


class EpisodicStore:
    """Consulta e inserción de episodios transaccionales por cliente/sesión."""

    async def get_orders(
        self,
        *,
        cliente_id: str | None = None,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[EpisodicOrder]:
        if not cliente_id and not session_id:
            return []
        rows = await fetch_all(
            """
            SELECT id, estado, total, session_id, cliente_id, created_at
            FROM pedidos
            WHERE ($1::text IS NULL OR cliente_id = $1)
              AND ($2::text IS NULL OR session_id = $2)
            ORDER BY created_at DESC NULLS LAST
            LIMIT $3
            """,
            cliente_id,
            session_id,
            limit,
        )
        return [
            EpisodicOrder(
                pedido_id=str(row["id"]),
                estado=str(row["estado"]),
                total=Decimal(str(row["total"])) if row["total"] is not None else None,
                session_id=row["session_id"],
                cliente_id=row["cliente_id"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def get_pending_orders(
        self,
        *,
        cliente_id: str | None = None,
        session_id: str | None = None,
    ) -> list[EpisodicOrder]:
        pedidos = await self.get_orders(cliente_id=cliente_id, session_id=session_id)
        pendientes = {"preparada", "aprobada"}
        return [p for p in pedidos if p.estado in pendientes]

    async def get_interaction_logs(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[InteractionRecord]:
        if not session_id:
            return []
        rows = await fetch_all(
            """
            SELECT timestamp, session_id, accion, resultado, metadata
            FROM log_inmutable
            WHERE session_id = $1
            ORDER BY timestamp DESC
            LIMIT $2
            """,
            session_id,
            limit,
        )
        records: list[InteractionRecord] = []
        for row in rows:
            meta = row["metadata"] or {}
            if not isinstance(meta, dict):
                meta = {}
            contenido = meta.get("content") or meta.get("contenido")
            records.append(
                InteractionRecord(
                    session_id=str(row["session_id"] or session_id),
                    accion=str(row["accion"]),
                    resultado=str(row["resultado"]),
                    timestamp=row["timestamp"],
                    contenido=str(contenido) if contenido else None,
                )
            )
        return records

    async def append_interaction(
        self,
        session_id: str,
        role: str,
        content: str,
        agente: str | None = None,
    ) -> None:
        """Inserta un turno en el log append-only (sin UPDATE/DELETE)."""
        await log_transaction_event(
            session_id=session_id,
            accion=f"turno_{role}",
            payload={"role": role, "content": content[:2000]},
            idempotency_key=None,
            resultado="ok",
            metadata={
                "content": content[:2000],
                "agente": agente or "",
                "role": role,
            },
        )
