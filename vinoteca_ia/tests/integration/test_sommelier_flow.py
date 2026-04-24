"""
Tests de integración: orquestador → sommelier y reglas de stock en SQL tools.

Evitan LLM real mockeando `arun` del agente y `_clasificar` del orquestador.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.orchestrator import Orchestrator
from schemas.agent_io import (
    AgenteDestino,
    IntentClass,
    RouterOutput,
    SessionRequest,
)
from schemas.session_state import SessionState
from schemas.tool_responses import ResultadoTool, StockResponse


@pytest.mark.asyncio
async def test_orquestador_deriva_a_sommelier_y_propaga_respuesta():
    """El router marca maridaje; el orquestador llama al sommelier y devuelve su salida."""
    # Sin `Orchestrator.__init__`: evita construir Agentes Agno (versión / kwargs del entorno).
    orch = object.__new__(Orchestrator)
    mock_arun = AsyncMock(
        return_value=MagicMock(
            content="Para el asado te recomiendo un Malbec de Valle de Uco; tenemos stock."
        )
    )
    sommelier = MagicMock()
    sommelier.arun = mock_arun
    orch._agentes = {
        "agente_inventario": MagicMock(),
        "agente_sommelier": sommelier,
        "agente_orders": MagicMock(),
        "agente_support": MagicMock(),
    }

    router_out = RouterOutput(
        intencion=IntentClass.MARIDAJE,
        confianza=0.92,
        agente_destino=AgenteDestino.SOMMELIER,
        razonamiento="test: consulta de maridaje",
    )

    with patch.object(orch, "_clasificar", new_callable=AsyncMock, return_value=router_out):
        req = SessionRequest(
            session_id="sess_int_1",
            correlation_id="corr_int_1",
            mensaje="¿Qué vino me recomendás para un asado de cordero?",
        )
        state = SessionState(session_id=req.session_id, correlation_id=req.correlation_id)
        state = state.con_turno("user", req.mensaje)

        resp = await orch.procesar(req, state)

    assert resp.agente == "agente_sommelier"
    assert resp.intencion == IntentClass.MARIDAJE
    assert resp.finalizado is True
    assert "Malbec" in resp.respuesta or "asado" in resp.respuesta.lower()
    mock_arun.assert_awaited_once()


@pytest.mark.asyncio
async def test_consultar_stock_cero_no_disponible():
    """La tool SQL marca `disponible=False` cuando la fila tiene cantidad 0."""
    vino_id = uuid.uuid4()
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, k: {
        "id": vino_id,
        "nombre": "Vino Agotado",
        "cantidad": 0,
        "ubicacion": "deposito_principal",
    }[k]

    with patch("tools.catalog.consult_stock.fetch_all", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = [mock_row]
        from tools.catalog.consult_stock import consultar_stock

        result = await consultar_stock.entrypoint(vino_ids=[str(vino_id)])

    assert isinstance(result, StockResponse)
    assert result.resultado == ResultadoTool.OK
    assert result.todos_disponibles is False
    assert len(result.items) == 1
    assert result.items[0].disponible is False
    assert result.items[0].cantidad == 0
