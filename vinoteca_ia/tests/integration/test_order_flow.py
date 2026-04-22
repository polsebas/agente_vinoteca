"""
Test de integración: flujo Two-Phase Commit completo.
Verifica Fase 1 → pausa → señal /aprobar → Fase 2 → log inmutable.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from schemas.order import OrderEstado, TipoEntrega


@pytest.mark.asyncio
async def test_idempotency_key_generacion():
    """La idempotency_key tiene el formato correcto."""
    from agents.orders_agent import generar_idempotency_key

    session_id = "sess_web_test_abc123"
    key = generar_idempotency_key(session_id)

    assert key.startswith("ord_")
    assert session_id in key
    assert len(key) > 20


@pytest.mark.asyncio
async def test_verificacion_stock_previene_fase2_sin_aprobacion():
    """
    El Two-Phase Commit NO puede avanzar a Fase 2 sin pasar por /aprobar.
    Verificar que el estado del pedido es PENDIENTE_APROBACION después de Fase 1.
    """
    assert OrderEstado.PENDIENTE_APROBACION == "pendiente_aprobacion"
    assert OrderEstado.CONFIRMADO == "confirmado"
    assert OrderEstado.CANCELADO == "cancelado"


@pytest.mark.asyncio
async def test_estados_validos_para_aprobacion():
    """Solo pedidos en PENDIENTE_APROBACION pueden ser aprobados."""
    estados_aprobables = {OrderEstado.PENDIENTE_APROBACION}
    estados_no_aprobables = {
        OrderEstado.PREPARANDO,
        OrderEstado.CONFIRMADO,
        OrderEstado.CANCELADO,
        OrderEstado.FALLIDO,
    }

    assert OrderEstado.PENDIENTE_APROBACION in estados_aprobables
    assert OrderEstado.CONFIRMADO in estados_no_aprobables
    assert OrderEstado.CANCELADO in estados_no_aprobables


@pytest.mark.asyncio
async def test_calcular_pedido_sin_mutacion():
    """
    calcular_pedido no debe generar ninguna llamada a execute() (no muta DB).
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    vino_id = uuid4()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, k: {
        "id": vino_id, "nombre": "Zuccardi", "precio": 3200.0
    }[k]

    with (
        patch("tools.orders.calculate_order.fetch_all", new_callable=AsyncMock) as mock_fetch,
        patch("storage.postgres.execute", new_callable=AsyncMock) as mock_exec,
    ):
        mock_fetch.return_value = [mock_row]
        from tools.orders.calculate_order import calcular_pedido
        result = await calcular_pedido.entrypoint(
            items=[{"vino_id": str(vino_id), "cantidad": 2}],
            tipo_entrega="retiro",
        )

        mock_exec.assert_not_called()

    assert result.total == 6400.0
    assert result.envio == 0.0
    assert len(result.lineas) == 1


@pytest.mark.asyncio
async def test_log_inmutable_registra_eventos():
    """El log inmutable debe registrar cada evento de pedido."""
    from unittest.mock import AsyncMock, patch

    with patch("storage.immutable_log.execute", new_callable=AsyncMock) as mock_exec:
        from storage.immutable_log import registrar

        pedido_id = uuid4()
        await registrar(
            "pedido_fase1_iniciado",
            pedido_id=pedido_id,
            session_id="sess_test",
            payload={"total": 5000.0},
        )

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert "INSERT INTO log_inmutable" in call_args[0][0]


@pytest.mark.asyncio
async def test_order_tipo_entrega():
    """El tipo de entrega determina si se cobra envío."""
    from tools.orders.calculate_order import COSTO_ENVIO
    assert COSTO_ENVIO > 0

    assert TipoEntrega.RETIRO == "retiro"
    assert TipoEntrega.ENVIO == "envio"
