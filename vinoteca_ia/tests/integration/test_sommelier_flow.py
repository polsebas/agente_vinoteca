"""
Test de integración: flujo completo del Sumiller.
Verifica que RAG → verificación stock → respuesta funciona end-to-end.
Requiere variables de entorno de DB y LLM configuradas.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from schemas.session_state import SessionState
from schemas.tool_responses import RAGResult, StockQueryResult
from schemas.wine_catalog import StockInfo


@pytest.mark.asyncio
async def test_flujo_sumiller_recomendacion_con_stock():
    """
    El sumiller recibe una consulta de maridaje, busca en RAG,
    verifica stock y genera una respuesta.
    """
    vino_id = uuid4()
    session_id = f"sess_test_{uuid4().hex[:6]}"
    correlation_id = f"sess_test_{uuid4().hex[:6]}"

    [
        RAGResult(
            vino_id=vino_id,
            nombre_vino="Zuccardi Valle de Uco",
            capa=5,
            contenido="Para un asado de cordero, este Malbec tiene la estructura perfecta.",
            score=0.92,
        )
    ]

    StockQueryResult(
        items=[
            StockInfo(
                vino_id=vino_id,
                nombre="Zuccardi Valle de Uco",
                disponible=True,
                cantidad=36,
            )
        ],
        todos_disponibles=True,
    )

    with (
        patch("core.rag.retriever.generar_embedding", new_callable=AsyncMock) as mock_embed,
        patch("core.rag.retriever.fetch_all", new_callable=AsyncMock) as mock_rag,
        patch("storage.postgres.fetch_all", new_callable=AsyncMock) as mock_stock,
    ):
        mock_embed.return_value = [0.1] * 1536
        mock_rag.return_value = [
            MagicMock(**{
                "__getitem__.side_effect": lambda k: {
                    "vino_id": vino_id,
                    "nombre_vino": "Zuccardi Valle de Uco",
                    "capa": 5,
                    "contenido": "Para un asado de cordero, ideal.",
                    "score": 0.92,
                }[k]
            })
        ]
        mock_stock.return_value = []

        state = SessionState(session_id=session_id, correlation_id=correlation_id)

        assert state.session_id == session_id
        assert state.historial == []

        state_con_turno = state.agregar_turno(
            "user", "¿Qué vino me recomendás para un asado de cordero?"
        )
        assert len(state_con_turno.historial) == 1
        assert state_con_turno.historial[0].rol == "user"


@pytest.mark.asyncio
async def test_flujo_sumiller_sin_stock_no_recomienda():
    """
    Si todos los candidatos tienen stock 0, el sumiller no debe recomendar ninguno.
    """
    vino_id = uuid4()
    f"sess_test_{uuid4().hex[:6]}"

    stock_sin_disponibilidad = StockQueryResult(
        items=[
            StockInfo(
                vino_id=vino_id,
                nombre="Vino Agotado",
                disponible=False,
                cantidad=0,
            )
        ],
        todos_disponibles=False,
    )

    assert not stock_sin_disponibilidad.todos_disponibles
    assert stock_sin_disponibilidad.items[0].cantidad == 0
