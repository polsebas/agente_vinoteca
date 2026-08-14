"""Orquestador PRAO: Perceive → Reason → Act → Observe.

Stateless respecto al proceso: sesión, memoria y perfil viven en Postgres
o en el registro in-process del orquestador. Circuit breaker a 5 pasos,
stuck-state a 3 firmas idénticas, fallback sin filtrar stack traces.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agno.agent import Agent
from pydantic import BaseModel

from agents.events_agent import get_events_agent
from agents.inventory_agent import get_inventory_agent
from agents.orders_agent import get_orders_agent
from agents.router_agent import get_router_agent
from agents.sommelier_agent import get_sommelier_agent
from agents.support_agent import get_support_agent
from core.correlation import generate_correlation_id, set_current
from core.guardrails import (
    RESPUESTA_BLOQUEADA_JAILBREAK,
    check_input_guardrails,
    sanitize_output,
)
from core.llm_fallback import (
    heuristic_route,
    is_provider_failure,
    is_provider_failure_text,
    run_deterministic_specialist,
)
from core.memory.episodic_store import EpisodicStore
from core.memory.semantic_store import SemanticStore
from core.memory.working_memory import WorkingMemory
from core.stuck_state import StuckStateDetector
from observability.cost_tracker import extract_run_usage, get_cost_tracker
from observability.metrics import get_kpi_collector
from observability.tracer import LatencyTracer
from schemas.agent_io import (
    AgentResponse,
    EventsResponse,
    IntentClass,
    InventoryResponse,
    OrderResponse,
    RouterOutput,
    SessionRequest,
    SommelierResponse,
    SupportResponse,
)
from schemas.customer_profile import CustomerProfile
from schemas.order import CalculatedOrder
from schemas.session_state import Canal, EstadoPedidoPendiente, SessionState

MAX_STEPS = 5
MIN_CONFIANZA = 0.85
MAX_ERRORES_CONSECUTIVOS = 3

logger = logging.getLogger("vinoteca.orchestrator")

AGENTE_MAP: dict[IntentClass, str | None] = {
    IntentClass.RECOMENDACION_OCASION: "agente_sommelier",
    IntentClass.RECOMENDACION_REGALO: "agente_sommelier",
    IntentClass.MARIDAJE: "agente_sommelier",
    IntentClass.CONSULTA_STOCK_PRECIO: "agente_inventario",
    IntentClass.PEDIDO_DELIVERY: "agente_orders",
    IntentClass.EVENTO_DEGUSTACION: "agente_events",
    IntentClass.SOPORTE_RECLAMO: "agente_support",
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

RESPUESTA_STUCK = (
    "Me trabé un poco con esta consulta. "
    "¿Podés reformularla o contarme el vino/ocasión con un poco más de detalle?"
)


class VinotecaOrchestrator:
    """Punto central del bucle PRAO. Los agentes se construyen lazy."""

    def __init__(
        self,
        *,
        router: Agent | None = None,
        agents: dict[str, Agent] | None = None,
        semantic_store: SemanticStore | None = None,
        episodic_store: EpisodicStore | None = None,
    ) -> None:
        self._router = router
        self._agentes = agents
        self._semantic = semantic_store or SemanticStore()
        self._episodic = episodic_store or EpisodicStore()
        self._memories: dict[str, WorkingMemory] = {}
        self._states: dict[str, SessionState] = {}
        self._last_calculated: dict[str, CalculatedOrder] = {}
        self._active_tracer: LatencyTracer | None = None

    def _get_router(self) -> Agent:
        router = getattr(self, "_router", None)
        if router is None:
            self._router = get_router_agent()
            return self._router
        return router

    def _get_agentes(self) -> dict[str, Agent]:
        agentes = getattr(self, "_agentes", None)
        if agentes is None:
            self._agentes = {
                "agente_inventario": get_inventory_agent(),
                "agente_sommelier": get_sommelier_agent(),
                "agente_orders": get_orders_agent(),
                "agente_support": get_support_agent(),
                "agente_events": get_events_agent(),
            }
            return self._agentes
        return agentes

    def _memory(self, session_id: str) -> WorkingMemory:
        if session_id not in self._memories:
            self._memories[session_id] = WorkingMemory(session_id)
        return self._memories[session_id]

    async def process_turn(
        self,
        session_id: str,
        user_message: str,
        canal: str = "web",
        cliente_id: str | None = None,
    ) -> AgentResponse:
        """Turno completo: guardrail → contexto → ruteo → PRAO → memoria."""
        correlation_id = generate_correlation_id(session_id)
        set_current(correlation_id)
        tracer = LatencyTracer(session_id)
        self._active_tracer = tracer
        self._current_session_id = session_id

        with tracer.trace_span("guardrails"):
            is_safe, sanitized, block_reason = check_input_guardrails(user_message)
        if not is_safe:
            response = AgentResponse(
                session_id=session_id,
                correlation_id=correlation_id,
                respuesta=sanitize_output(block_reason or RESPUESTA_BLOQUEADA_JAILBREAK),
                agente="guardrail",
                intencion=IntentClass.DESCONOCIDO,
                finalizado=True,
            )
            _record_telemetry(tracer, response, order_created=False, escalated=False)
            self._active_tracer = None
            return response

        try:
            canal_enum = Canal(canal)
        except ValueError:
            canal_enum = Canal.WEB

        state = self._states.get(session_id) or SessionState(
            session_id=session_id,
            correlation_id=correlation_id,
            cliente_id=cliente_id,
            canal=canal_enum,
        )
        memory = self._memory(session_id)
        profile = await self._load_profile(cliente_id)
        request = SessionRequest(
            session_id=session_id,
            correlation_id=correlation_id,
            mensaje=sanitized,
            cliente_id=cliente_id,
        )

        with tracer.trace_span("llm_reasoning"):
            response = await self.procesar(request, state, memory=memory, profile=profile)

        memory.add_turn("user", sanitized)
        memory.add_turn("assistant", response.respuesta)
        state = state.con_turno("user", sanitized)
        state = state.con_turno("assistant", response.respuesta, agente=response.agente)
        if response.requiere_aprobacion:
            update: dict[str, Any] = {
                "pedido_pendiente_estado": EstadoPedidoPendiente.PREPARADO,
            }
            pending = getattr(self, "_last_calculated", {}).get(session_id)
            if pending is not None:
                update["pedido_en_preparacion"] = pending
            state = state.model_copy(update=update)
        self._states[session_id] = state

        try:
            await self._episodic.append_interaction(session_id, "user", sanitized, agente=None)
            await self._episodic.append_interaction(
                session_id, "assistant", response.respuesta, agente=response.agente
            )
        except Exception:
            pass

        sanitized_resp = response.model_copy(
            update={"respuesta": sanitize_output(response.respuesta)}
        )
        order_created = bool((sanitized_resp.metadata or {}).get("order_id")) or (
            "PED-" in sanitized_resp.respuesta and sanitized_resp.agente == "agente_orders"
        )
        escalated = (sanitized_resp.metadata or {}).get("escalado") == "true"
        _record_telemetry(
            tracer,
            sanitized_resp,
            order_created=order_created,
            escalated=escalated,
        )
        self._active_tracer = None
        return sanitized_resp

    async def procesar(
        self,
        request: SessionRequest,
        state: SessionState,
        memory: WorkingMemory | None = None,
        profile: CustomerProfile | None = None,
    ) -> AgentResponse:
        """
        1. Clasifica intención via Router.
        2. Deriva al agente especialista.
        3. Aplica circuit breaker y stuck state.
        4. Retorna AgentResponse estructurada.
        """
        detector = StuckStateDetector()
        pasos = 0

        pasos += 1
        router_output = await self._clasificar(request.mensaje)

        if (
            not router_output
            or router_output.accion_nula
            or router_output.confianza < MIN_CONFIANZA
        ):
            aclaracion = (
                router_output.pregunta_aclaracion
                if router_output and router_output.pregunta_aclaracion
                else RESPUESTA_ACLARACION
            )
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=aclaracion,
                agente="router",
                intencion=IntentClass.DESCONOCIDO,
                metadata={"pasos": str(pasos)},
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
                metadata={"pasos": str(pasos)},
                finalizado=True,
            )

        agentes = self._get_agentes()
        agente = agentes.get(agente_nombre)
        if not agente:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=RESPUESTA_FALLBACK,
                agente="orchestrator",
                intencion=router_output.intencion,
                metadata={"pasos": str(pasos)},
                finalizado=True,
            )

        mensaje = self._ensamblar_contexto(request, state, memory, profile)
        return await self._prao_especialista(
            request=request,
            state=state,
            agente=agente,
            agente_nombre=agente_nombre,
            intencion=router_output.intencion,
            mensaje=mensaje,
            detector=detector,
            pasos=pasos,
        )

    async def _prao_especialista(
        self,
        *,
        request: SessionRequest,
        state: SessionState,
        agente: Agent,
        agente_nombre: str,
        intencion: IntentClass,
        mensaje: str,
        detector: StuckStateDetector,
        pasos: int,
    ) -> AgentResponse:
        errores = 0
        prompt = mensaje

        while pasos < MAX_STEPS:
            pasos += 1
            try:
                tracer = getattr(self, "_active_tracer", None)
                if tracer is not None:
                    with tracer.trace_span("tool_execution"):
                        result = await agente.arun(prompt)
                else:
                    result = await agente.arun(prompt)
                _ingest_usage(request.session_id, result)
            except Exception as exc:
                if is_provider_failure(exc):
                    logger.warning("Especialista LLM no disponible (%s); fallback SQL/RAG", exc)
                    return await run_deterministic_specialist(
                        request,
                        state,
                        agente_nombre=agente_nombre,
                        intencion=intencion,
                        last_calculated=self._ensure_calc_cache(),
                    )
                errores += 1
                detector.registrar_error("agent_error")
                if detector.is_stuck or errores >= MAX_ERRORES_CONSECUTIVOS:
                    return self._fallback(
                        request, agente_nombre, intencion, pasos, stuck=detector.is_stuck
                    )
                continue

            for tool_name, args_repr in _tool_signatures(result):
                detector.registrar(tool_name, args_repr)
                if detector.is_stuck:
                    return self._fallback(request, agente_nombre, intencion, pasos, stuck=True)

            texto, extra, content = _extract_respuesta(result)
            if texto and is_provider_failure_text(texto):
                logger.warning("Especialista devolvió error de proveedor; fallback SQL/RAG")
                return await run_deterministic_specialist(
                    request,
                    state,
                    agente_nombre=agente_nombre,
                    intencion=intencion,
                    last_calculated=self._ensure_calc_cache(),
                )
            if isinstance(content, SupportResponse) and content.escalado_a_humano:
                extra["escalado"] = "true"
            if texto:
                requiere = extra.get("requiere_aprobacion") == "true"
                if requiere and isinstance(content, OrderResponse):
                    prepared = _pedido_preparacion(content, state)
                    if prepared.pedido_en_preparacion is not None:
                        cache = getattr(self, "_last_calculated", None)
                        if cache is None:
                            self._last_calculated = {}
                            cache = self._last_calculated
                        cache[request.session_id] = prepared.pedido_en_preparacion
                return AgentResponse(
                    session_id=request.session_id,
                    correlation_id=request.correlation_id,
                    respuesta=texto,
                    agente=agente_nombre,
                    intencion=intencion,
                    requiere_aprobacion=requiere,
                    finalizado=not requiere,
                    metadata={"pasos": str(pasos), **extra},
                )

            prompt = (
                "Continuá con el resultado de las tools y respondé al cliente "
                "en un mensaje claro, sin repetir la misma herramienta."
            )

        return self._fallback(request, agente_nombre, intencion, pasos, stuck=False)

    def _fallback(
        self,
        request: SessionRequest,
        agente_nombre: str,
        intencion: IntentClass,
        pasos: int,
        *,
        stuck: bool,
    ) -> AgentResponse:
        return AgentResponse(
            session_id=request.session_id,
            correlation_id=request.correlation_id,
            respuesta=RESPUESTA_STUCK if stuck else RESPUESTA_FALLBACK,
            agente=agente_nombre,
            intencion=intencion,
            metadata={
                "pasos": str(pasos),
                "circuit_breaker": "true",
                "stuck": "true" if stuck else "false",
            },
            finalizado=True,
        )

    async def _clasificar(self, mensaje: str) -> RouterOutput | None:
        try:
            result = await self._get_router().arun(mensaje)
            _ingest_usage(getattr(self, "_current_session_id", ""), result)
            content = getattr(result, "content", result)
            if isinstance(content, RouterOutput):
                return content
            if isinstance(content, str):
                data = json.loads(content)
                return RouterOutput(**data)
            if isinstance(content, dict):
                return RouterOutput(**content)
            return heuristic_route(mensaje)
        except Exception as exc:
            logger.warning("Router LLM no disponible (%s); usando heurística", exc)
            return heuristic_route(mensaje)

    def _ensure_calc_cache(self) -> dict[str, CalculatedOrder]:
        cache = getattr(self, "_last_calculated", None)
        if cache is None:
            self._last_calculated = {}
            return self._last_calculated
        return cache

    async def _manejar_pedido(
        self,
        request: SessionRequest,
        state: SessionState,
        router_output: RouterOutput,
    ) -> AgentResponse:
        """Compatibilidad: Fase 1 del 2PC vía el especialista de pedidos."""
        agentes = self._get_agentes()
        agente = agentes.get("agente_orders")
        if not agente:
            return AgentResponse(
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                respuesta=RESPUESTA_FALLBACK,
                agente="orchestrator",
                intencion=router_output.intencion,
                finalizado=True,
            )
        detector = StuckStateDetector()
        instruccion = (
            f"El cliente quiere hacer un pedido. Mensaje: '{request.mensaje}'. "
            f"Extraé los vinos y cantidades mencionados, verificá stock con "
            f"verificar_stock_exacto, calculá el total con calcular_orden, "
            f"y respondé con el resumen en formato legible. "
            f"Session ID: {request.session_id}"
        )
        return await self._prao_especialista(
            request=request,
            state=state,
            agente=agente,
            agente_nombre="agente_orders",
            intencion=router_output.intencion,
            mensaje=instruccion,
            detector=detector,
            pasos=1,
        )

    def _ensamblar_contexto(
        self,
        request: SessionRequest,
        state: SessionState,
        memory: WorkingMemory | None,
        profile: CustomerProfile | None,
    ) -> str:
        partes: list[str] = []
        if profile:
            cepas = ", ".join(c.value for c in profile.cepas_favoritas) or "N/A"
            partes.append(
                f"Perfil cliente: {profile.nombre or 'invitado'} "
                f"(segmento={profile.segmento.value}, perfil={profile.perfil_tipo.value}, "
                f"cepas={cepas})."
            )
        if memory and memory.summary:
            partes.append(f"Resumen de conversación: {memory.summary}")
        if memory:
            window = memory.get_context_window()
            for t in window:
                prefijo = "Cliente" if t.get("role") == "user" else "Asistente"
                partes.append(f"{prefijo}: {t.get('content', '')}")
        else:
            historial_str = self._formatear_historial(state)
            if historial_str:
                partes.append(historial_str)
        partes.append(f"Cliente: {request.mensaje}")
        return "\n".join(partes)

    def _formatear_historial(self, state: SessionState, n: int = 6) -> str:
        turnos = state.ultimos_turnos(n)
        if not turnos:
            return ""
        lineas = []
        for t in turnos:
            prefijo = "Cliente" if t.rol == "user" else "Asistente"
            lineas.append(f"{prefijo}: {t.contenido}")
        return "\n".join(lineas)

    async def _load_profile(self, cliente_id: str | None) -> CustomerProfile | None:
        if not cliente_id:
            return None
        try:
            return await self._semantic.get_profile(cliente_id)
        except Exception:
            return None


Orchestrator = VinotecaOrchestrator

_ORCH: VinotecaOrchestrator | None = None


def get_orchestrator() -> VinotecaOrchestrator:
    """Singleton perezoso para el gateway. Los tests parchean esta factory."""
    global _ORCH
    if _ORCH is None:
        _ORCH = VinotecaOrchestrator()
    return _ORCH


def reset_orchestrator() -> None:
    global _ORCH
    _ORCH = None


def _tool_signatures(result: Any) -> list[tuple[str, str]]:
    tools = getattr(result, "tools", None)
    if not isinstance(tools, (list, tuple)):
        return []
    sigs: list[tuple[str, str]] = []
    for tool in tools:
        name = getattr(tool, "tool_name", None) or getattr(tool, "name", None)
        args = getattr(tool, "tool_args", None) or getattr(tool, "arguments", None)
        if not name:
            continue
        if isinstance(args, str):
            args_repr = args
        else:
            args_repr = json.dumps(args or {}, sort_keys=True, default=str)
        sigs.append((str(name), args_repr))
    return sigs


def _extract_respuesta(result: Any) -> tuple[str, dict[str, str], Any]:
    content = getattr(result, "content", result)
    extra: dict[str, str] = {}
    if isinstance(content, OrderResponse):
        extra["requiere_aprobacion"] = "true" if content.requiere_aprobacion else "false"
        if content.order_id:
            extra["order_id"] = content.order_id
        return content.mensaje_cliente, extra, content
    if isinstance(content, SupportResponse):
        if content.escalado_a_humano:
            extra["escalado"] = "true"
        return content.mensaje_cliente, extra, content
    if isinstance(content, (SommelierResponse, InventoryResponse, EventsResponse)):
        return content.mensaje_cliente, extra, content
    if isinstance(content, BaseModel):
        data = content.model_dump()
        mensaje = data.get("mensaje_cliente") or data.get("respuesta")
        if isinstance(mensaje, str) and mensaje.strip():
            return mensaje, extra, content
        return "", extra, content
    if isinstance(content, str) and content.strip():
        return content, extra, content
    return "", extra, content


def _pedido_preparacion(content: OrderResponse, state: SessionState) -> SessionState:
    if not content.lineas or content.total_ars is None:
        return state
    try:
        pedido = CalculatedOrder(
            lineas=content.lineas,
            subtotal=content.total_ars,
            total=content.total_ars,
            requiere_confirmacion=content.requiere_aprobacion,
        )
    except Exception:
        return state
    return state.model_copy(
        update={
            "pedido_en_preparacion": pedido,
            "pedido_pendiente_estado": EstadoPedidoPendiente.PREPARADO,
        }
    )


def _ingest_usage(session_id: str, result: Any) -> None:
    if not session_id:
        return
    model, inp, out = extract_run_usage(result)
    if inp <= 0 and out <= 0:
        return
    get_cost_tracker().track_usage(session_id, model, inp, out)


def _record_telemetry(
    tracer: LatencyTracer,
    response: AgentResponse,
    *,
    order_created: bool,
    escalated: bool,
) -> None:
    summary = tracer.finish()
    meta = response.metadata or {}
    stuck = meta.get("stuck") == "true" or (
        meta.get("circuit_breaker") == "true" and "trabé" in response.respuesta.lower()
    )
    session_cost = get_cost_tracker().get_session_cost(response.session_id)
    tokens = int(session_cost["input_tokens"]) + int(session_cost["output_tokens"])
    get_kpi_collector().record_turn(
        response.session_id,
        intent=response.intencion,
        latency_ms=float(summary["total_ms"]),
        tokens=tokens,
        stuck=stuck,
        escalated=escalated or meta.get("escalado") == "true",
        order_created=order_created,
        resolved=response.finalizado and not escalated,
    )
