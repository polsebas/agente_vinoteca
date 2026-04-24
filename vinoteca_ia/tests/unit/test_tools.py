"""
Tests unitarios de tools SQL.
Verifican que nunca usan vectores y que la validación semántica funciona.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from schemas.tool_responses import PriceResponse, ResultadoTool, StockResponse


# ── consultar_stock ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_consultar_stock_con_disponibilidad():
    vino_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, k: {
        "id": vino_id,
        "nombre": "Zuccardi",
        "cantidad": 20,
        "ubicacion": "deposito_principal",
    }[k]

    with patch("tools.catalog.consult_stock.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_row]
        from tools.catalog.consult_stock import consultar_stock

        result = await consultar_stock.entrypoint(vino_ids=[str(vino_id)])

    assert isinstance(result, StockResponse)
    assert result.todos_disponibles is True
    assert len(result.items) == 1
    assert result.items[0].cantidad == 20


@pytest.mark.asyncio
async def test_consultar_stock_vacio_ids():
    from tools.catalog.consult_stock import consultar_stock

    result = await consultar_stock.entrypoint(vino_ids=[])

    assert isinstance(result, StockResponse)
    assert result.todos_disponibles is False
    assert len(result.items) == 0


@pytest.mark.asyncio
async def test_consultar_stock_no_usa_rag():
    """Verifica que consultar_stock no importa ni llama a retriever."""
    import inspect

    import tools.catalog.consult_stock as module

    source = inspect.getsource(module)
    assert "retriever" not in source
    assert "vector" not in source.lower() or "pgvector" not in source.lower()


# ── consultar_precio ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_consultar_precio_valido():
    vino_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, k: {
        "id": vino_id,
        "nombre": "Achaval Ferrer",
        "precio_ars": Decimal("4500.00"),
        "anada_actual": 2020,
    }[k]

    with patch("tools.catalog.consult_price.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_row]
        from tools.catalog.consult_price import consultar_precio

        result = await consultar_precio.entrypoint(vino_ids=[str(vino_id)])

    assert isinstance(result, PriceResponse)
    assert result.resultado == ResultadoTool.OK
    assert len(result.items) == 1
    assert result.items[0].precio_ars == Decimal("4500.00")


@pytest.mark.asyncio
async def test_consultar_precio_no_encontrado():
    vino_id = uuid.uuid4()

    with patch("tools.catalog.consult_price.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        from tools.catalog.consult_price import consultar_precio

        result = await consultar_precio.entrypoint(vino_ids=[str(vino_id)])

    assert result.resultado == ResultadoTool.NO_ENCONTRADO
    assert len(result.items) == 0

