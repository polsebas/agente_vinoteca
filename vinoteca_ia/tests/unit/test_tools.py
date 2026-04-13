"""
Tests unitarios de tools SQL.
Verifican que nunca usan vectores y que la validación semántica funciona.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.tool_responses import PriceQueryResult, StockQueryResult


# ── consultar_stock ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_consultar_stock_con_disponibilidad():
    vino_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, k: {
        "id": vino_id, "nombre": "Zuccardi", "cantidad": 20, "ubicacion": "deposito_principal"
    }[k]

    with patch("tools.catalog.consult_stock.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_row]
        from tools.catalog.consult_stock import consultar_stock
        result = await consultar_stock.entrypoint(vino_ids=[str(vino_id)])

    assert isinstance(result, StockQueryResult)
    assert result.todos_disponibles is True
    assert len(result.items) == 1
    assert result.items[0].cantidad == 20


@pytest.mark.asyncio
async def test_consultar_stock_vacio():
    with patch("tools.catalog.consult_stock.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        from tools.catalog.consult_stock import consultar_stock
        result = await consultar_stock.entrypoint(vino_ids=[])

    assert isinstance(result, StockQueryResult)
    assert result.todos_disponibles is False
    assert len(result.items) == 0


@pytest.mark.asyncio
async def test_consultar_stock_no_usa_rag():
    """Verifica que consultar_stock no importa ni llama a retriever."""
    import tools.catalog.consult_stock as module
    import inspect
    source = inspect.getsource(module)
    assert "retriever" not in source
    assert "vector" not in source.lower() or "pgvector" not in source.lower()


# ── consultar_precio ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_consultar_precio_valido():
    vino_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, k: {
        "id": vino_id, "nombre": "Achaval Ferrer", "precio": 4500.0
    }[k]

    with patch("tools.catalog.consult_price.fetch_one", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_row
        from tools.catalog.consult_price import consultar_precio
        result = await consultar_precio.entrypoint(vino_id=str(vino_id))

    assert isinstance(result, PriceQueryResult)
    assert result.valido is True
    assert result.precio == 4500.0


@pytest.mark.asyncio
async def test_consultar_precio_cero_invalido():
    vino_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, k: {
        "id": vino_id, "nombre": "Vino Test", "precio": 0.0
    }[k]

    with patch("tools.catalog.consult_price.fetch_one", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_row
        from tools.catalog.consult_price import consultar_precio
        result = await consultar_precio.entrypoint(vino_id=str(vino_id))

    assert result.valido is False
    assert "inválido" in result.razon_invalido.lower()


@pytest.mark.asyncio
async def test_consultar_precio_no_encontrado():
    vino_id = uuid.uuid4()

    with patch("tools.catalog.consult_price.fetch_one", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = None
        from tools.catalog.consult_price import consultar_precio
        result = await consultar_precio.entrypoint(vino_id=str(vino_id))

    assert result.valido is False


# ── verificar_stock_exacto ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_verificar_stock_exacto_ok():
    vino_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, k: {
        "id": vino_id, "nombre": "Catena", "cantidad": 10
    }[k]

    with patch("tools.orders.verify_stock_exact.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_row]
        from tools.orders.verify_stock_exact import verificar_stock_exacto
        result = await verificar_stock_exacto.entrypoint(
            items=[{"vino_id": str(vino_id), "cantidad": 5}]
        )

    assert result.todo_disponible is True
    assert len(result.faltantes) == 0


@pytest.mark.asyncio
async def test_verificar_stock_exacto_faltante():
    vino_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, k: {
        "id": vino_id, "nombre": "Catena", "cantidad": 2
    }[k]

    with patch("tools.orders.verify_stock_exact.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_row]
        from tools.orders.verify_stock_exact import verificar_stock_exacto
        result = await verificar_stock_exacto.entrypoint(
            items=[{"vino_id": str(vino_id), "cantidad": 10}]
        )

    assert result.todo_disponible is False
    assert len(result.faltantes) == 1
    assert result.faltantes[0]["disponible"] == 2
    assert result.faltantes[0]["solicitado"] == 10
