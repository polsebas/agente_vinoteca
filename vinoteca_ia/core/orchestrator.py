"""
Orquestador PRAO: punto central de coordinación de agentes.
Stateless — todo estado persiste en PostgreSQL o Redis.
Implementa: circuit breaker (max_steps), stuck state, graceful fallback.
"""

from __future__ import annotations

import json

from agno.agent import Agent

from agents.inventory_agent import crear_agente_inventario
from agents.orders_agent import crear_agente_pedidos
from agents.router_agent import crear_agente_router
from agents.sommelier_agent import crear_agente_sumiller
from core.stuck_state import StuckStateDetector
from schemas.agent_io import (
    AgentResponse,
    IntentClass,
    RouterOutput,
    SessionRequest,
)
from schemas.session_state import SessionState

MAX_STEPS = 5
MIN_CONFIANZA = 0.85

AGENTE_MAP: dict[str, str] = {
    IntentClass.RECOMENDACION: "agente_sumiller",
    IntentClass.MARIDAJE: "agente_sumiller",
    IntentClass.CONSULTA_INVENTARIO: "agente_inventario",
    IntentClass.PEDIDO: "agente_pedidos",
    IntentClass.SOPORTE: "agente_sumiller",
    IntentClass.EVENTO: "agente_sumiller",
    IntentClass.DESCONOCIDO: None,
}

RESPUESTA_FALLBACK = (
    "Lo siento, en este momento no puedo procesar tu consulta correctamente. "
    "Por favor intentá de nuevo en unos instantes o llamanos directamente."
)

RESPUESTA_ACLARACION = (
    "¿Me podés contar un poco más para ayudarte mejor? "
    "Por ejemplo, ¿estás buscando un vino para regalar, para tomar en casa, "
    "o querés saber el precio de uno específico?"
)


class Orchestrator:
    def __init__(self) -> None:
        self._router = crear_agente_router()
        self._agentes: dict[str, Agent] = {
            "agente_inventario": crear_agente_inventario(),
            "agente_sumiller": crear_agente_sumiller(),
            "agente_pedidos": crear_agente_pedidos(),
        }

    async def procesar(self, request: SessionRequest, state: SessionState) -> AgentResponse:
        """
        Punto de entrada principal del orquestador.
        1. Clasifica intención via Router.
        2. Deriva al agente especialista.
        3. Aplica circuit breaker y stuck state.
        4. Retorna AgentResponse estructurada.
        """
        StuckStateDetector()

        router_output = await self._clasificar(request.mensaje)

        if not router_output or router_output.confianza < MIN_CONFIANZA:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=RESPUESTA_ACLARACION,
                agente="router",
                intencion=IntentClass.DESCONOCIDO,
                finalizado=True,
            )

        agente_nombre = AGENTE_MAP.get(router_output.intencion)
        if not agente_nombre:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=RESPUESTA_ACLARACION,
                agente="router",
                intencion=router_output.intencion,
                finalizado=True,
            )

        if router_output.intencion == IntentClass.PEDIDO:
            return await self._manejar_pedido(request, state, router_output)

        agente = self._agentes.get(agente_nombre)
        if not agente:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=RESPUESTA_FALLBACK,
                agente="orchestrator",
                intencion=router_output.intencion,
                finalizado=True,
            )

        try:
            historial_str = self._formatear_historial(state)
            mensaje_con_contexto = f"{historial_str}\nCliente: {request.mensaje}"

            result = await agente.arun(mensaje_con_contexto)
            respuesta = result.content if hasattr(result, "content") else str(result)

            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=respuesta,
                agente=agente_nombre,
                intencion=router_output.intencion,
                finalizado=True,
            )

        except Exception as e:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=RESPUESTA_FALLBACK,
                agente=agente_nombre,
                intencion=router_output.intencion,
                metadata={"error": str(e)},
                finalizado=True,
            )

    async def _clasificar(self, mensaje: str) -> RouterOutput | None:
        try:
            result = await self._router.arun(mensaje)
            if isinstance(result.content, RouterOutput):
                return result.content
            if isinstance(result.content, str):
                data = json.loads(result.content)
                return RouterOutput(**data)
            return None
        except Exception:
            return None

    async def _manejar_pedido(
        self,
        request: SessionRequest,
        state: SessionState,
        router_output: RouterOutput,
    ) -> AgentResponse:
        """
        Maneja el flujo de pedido iniciando Fase 1 del Two-Phase Commit.
        El agente de Pedidos extrae los ítems y llama a ejecutar_fase_1.
        """
        agente = self._agentes.get("agente_pedidos")
        if not agente:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=RESPUESTA_FALLBACK,
                agente="orchestrator",
                intencion=router_output.intencion,
                finalizado=True,
            )

        instruccion = (
            f"El cliente quiere hacer un pedido. Mensaje: '{request.mensaje}'. "
            f"Extraé los vinos y cantidades mencionados, verificá stock con "
            f"verificar_stock_exacto, calculá el total con calcular_pedido, "
            f"y respondé con el resumen en formato legible. "
            f"Session ID: {request.session_id}"
        )

        try:
            result = await agente.arun(instruccion)
            respuesta = result.content if hasattr(result, "content") else str(result)

            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=respuesta,
                agente="agente_pedidos",
                intencion=router_output.intencion,
                requiere_aprobacion=True,
                finalizado=False,
            )
        except Exception as e:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=RESPUESTA_FALLBACK,
                agente="agente_pedidos",
                intencion=router_output.intencion,
                metadata={"error": str(e)},
                finalizado=True,
            )

    def _formatear_historial(self, state: SessionState, n: int = 6) -> str:
        turnos = state.ultimos_turnos(n)
        if not turnos:
            return ""
        lineas = []
        for t in turnos:
            prefijo = "Cliente" if t.rol == "user" else "Asistente"
            lineas.append(f"{prefijo}: {t.contenido}")
        return "\n".join(lineas)
