"""Memoria multinivel: working window, summarizer, episodic y semantic store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from core.memory import (
    SUMMARIZE_AFTER,
    WINDOW_SIZE,
    EpisodicStore,
    SemanticStore,
    WorkingMemory,
    summarize_history,
)
from schemas.customer_profile import CustomerProfile, PerfilClienteTipo, SegmentoCliente
from schemas.wine_catalog import Varietal


def test_working_memory_ventana_deslizante_8_turnos():
    wm = WorkingMemory(session_id="s1")
    for i in range(10):
        wm.add_turn("user", f"msg {i}")
    ctx = wm.get_context_window()
    assert WINDOW_SIZE == 8
    assert len(ctx) == 8
    assert ctx[0]["content"] == "msg 2"
    assert ctx[-1]["content"] == "msg 9"
    assert all("role" in t and "content" in t for t in ctx)


def test_working_memory_clear():
    wm = WorkingMemory()
    wm.add_turn("user", "hola")
    wm.clear()
    assert wm.get_context_window() == []
    assert wm.turn_count == 0
    assert wm.summary is None


def test_summarizer_preserva_preferencias_vinos_y_carrito():
    messages = [
        {"role": "user", "content": "Prefiero malbec de Catena Zapata"},
        {"role": "assistant", "content": "Agregué 2 botellas al pedido"},
        {"role": "user", "content": "ok gracias"},
    ]
    resumen = summarize_history(messages, max_tokens=500)
    assert "malbec" in resumen.lower()
    assert "Catena" in resumen
    assert "pedido" in resumen.lower() or "botellas" in resumen.lower()
    assert len(resumen) <= 500 * 4


def test_working_memory_comprime_al_llegar_a_12_turnos():
    wm = WorkingMemory()
    wm.add_turn("user", "Prefiero malbec y Catena Zapata para el asado")
    for i in range(SUMMARIZE_AFTER - 1):
        wm.add_turn("assistant" if i % 2 else "user", f"turno {i}")
    assert wm.turn_count >= 12
    assert wm.summary
    assert "malbec" in wm.summary.lower() or "Catena" in wm.summary
    assert len(wm.get_context_window()) == WINDOW_SIZE


def test_semantic_store_ttl_24_meses():
    store = SemanticStore()
    viejo = datetime.now(UTC) - timedelta(days=800)
    fresco = datetime.now(UTC) - timedelta(days=30)
    assert store.is_stale(viejo)
    assert not store.is_stale(fresco)


@pytest.mark.asyncio
async def test_semantic_store_get_profile_filtra_stale():
    store = SemanticStore()
    cliente = {
        "nombre": "Ana",
        "email": None,
        "telefono": None,
        "segmento": "frecuente",
        "perfil_tipo": "curioso",
    }
    prefs = [
        {
            "clave": "cepa_favorita",
            "valor": "malbec",
            "fuente": "chat",
            "updated_at": datetime.now(UTC),
        },
        {
            "clave": "cepa_favorita",
            "valor": "bonarda",
            "fuente": "chat",
            "updated_at": datetime.now(UTC) - timedelta(days=800),
        },
    ]
    stats = {"total": 3, "ultima": datetime.now(UTC)}
    with (
        patch("core.memory.semantic_store.fetchrow", new_callable=AsyncMock) as mock_row,
        patch("core.memory.semantic_store.fetch_all", new_callable=AsyncMock) as mock_all,
    ):
        mock_row.side_effect = [cliente, stats]
        mock_all.return_value = prefs
        perfil = await store.get_profile("cli-1")

    assert isinstance(perfil, CustomerProfile)
    assert perfil.nombre == "Ana"
    assert perfil.segmento == SegmentoCliente.FRECUENTE
    assert perfil.perfil_tipo == PerfilClienteTipo.CURIOSO
    assert Varietal.MALBEC in perfil.cepas_favoritas
    assert Varietal.BONARDA not in perfil.cepas_favoritas
    assert perfil.total_compras == 3


@pytest.mark.asyncio
async def test_episodic_store_get_orders():
    store = EpisodicStore()
    created = datetime.now(UTC)
    row = {
        "id": "ord-1",
        "estado": "preparada",
        "total": Decimal("12000.00"),
        "session_id": "sess-1",
        "cliente_id": "cli-1",
        "created_at": created,
    }
    with patch("core.memory.episodic_store.fetch_all", new_callable=AsyncMock) as mock_all:
        mock_all.return_value = [row]
        pedidos = await store.get_orders(cliente_id="cli-1")
        pendientes = await store.get_pending_orders(cliente_id="cli-1")

    assert len(pedidos) == 1
    assert pedidos[0].pedido_id == "ord-1"
    assert pedidos[0].total == Decimal("12000.00")
    assert len(pendientes) == 1
