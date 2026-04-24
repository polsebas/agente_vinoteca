"""Factoría única de AgentOS para el runtime productivo.

Concentra en un solo lugar la composición de agentes, el Team router y los
flags de runtime (CORS, tracing, RBAC futuro). El entrypoint FastAPI
(`api.main`) la consume para obtener la app combinada vía `get_app()`.

Diseño:
- La lógica de negocio (tools, prompts, modelos, DB Agno) vive en los
  módulos existentes de `agents/` y `tools/`. Esta factoría solo monta la
  capa de runtime.
- `AGENT_FACTORIES` solo incluye agentes **no miembros** del team router
  (`router`, `auditor`). Sommelier/Orders/Support ya se registran como
  miembros al incluir el team en `TEAM_FACTORIES`, así evitamos construir
  instancias duplicadas y entradas repetidas en el dashboard.
- RBAC queda preparado pero desactivado por default: setear
  `AGENTOS_AUTHORIZATION=true` + `JWT_VERIFICATION_KEY`.
- Las rutas que AgentOS expone (`/agents/*`, `/teams/*`, `/approvals/*`,
  etc.) no son públicas: un middleware las restringe a loopback, mientras
  que `AGENTOS_PUBLIC_PATHS` (default `"/health,/chat"`) define qué se
  expone al exterior.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.team import Team
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from agents.auditor_agent import crear_agente_auditor
from agents.router_agent import crear_agente_router
from agents.router_team import crear_router_team
from storage.postgres import get_agno_db

AGENT_FACTORIES: list[Callable[[], Agent]] = [
    crear_agente_router,
    crear_agente_auditor,
]

TEAM_FACTORIES: list[Callable[[], Team]] = [
    crear_router_team,
]

_DEFAULT_PUBLIC_PATHS = ("/health", "/chat", "/webhook")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1].strip()
    return s.lower() in {"1", "true", "yes", "on"}


def _public_paths() -> tuple[str, ...]:
    raw = os.environ.get("AGENTOS_PUBLIC_PATHS")
    if not raw:
        return _DEFAULT_PUBLIC_PATHS
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or _DEFAULT_PUBLIC_PATHS


class InternalPathsGuard(BaseHTTPMiddleware):
    """Restringe todo el tráfico a loopback excepto los paths públicos.

    Objetivo: AgentOS expone rutas (`/agents/*`, `/teams/*`, `/approvals/*`,
    `/databases/*/migrate`, etc.) que operan sobre agentes y DB sin los
    tokens del dominio. En esta etapa esas rutas no deben ser alcanzables
    desde internet; solo se llega por loopback (ej. via un admin UI local
    o port-forward). Lo único público son los paths declarados
    explícitamente (por default `/health` y `/chat`).

    Para enlazar la UI hospedada en os.agno.com contra una API en URL
    pública o LAN, el navegador no aparece como loopback: usá
    `AGENTOS_RELAX_LOOPBACK_GUARD=true` solo en dev y preferiblemente con
    `OS_SECURITY_KEY` (Bearer) para que AgentOS no quede abierto.

    Responde 404 al bloquear para no filtrar la existencia del endpoint.
    """

    def __init__(
        self,
        app: ASGIApp,
        public_paths: tuple[str, ...],
        *,
        loopback_hosts: frozenset[str] = _LOOPBACK_HOSTS,
        relax_loopback_guard: bool = False,
    ) -> None:
        super().__init__(app)
        self._public = tuple(public_paths)
        self._loopback = loopback_hosts
        self._relax_loopback_guard = relax_loopback_guard

    def _is_public(self, path: str) -> bool:
        for prefix in self._public:
            if path == prefix or path.startswith(prefix + "/"):
                return True
        return False

    def _is_loopback(self, request: Request) -> bool:
        client = request.client
        if client is None:
            return False
        return client.host in self._loopback

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            self._is_public(path)
            or self._is_loopback(request)
            or self._relax_loopback_guard
        ):
            return await call_next(request)
        return JSONResponse(status_code=404, content={"detail": "Not Found"})


def add_internal_paths_guard(
    app: FastAPI,
    public_paths: tuple[str, ...] | None = None,
    *,
    relax_loopback_guard: bool | None = None,
) -> None:
    """Monta `InternalPathsGuard` en el FastAPI recibido."""
    if relax_loopback_guard is None:
        relax_loopback_guard = _env_bool("AGENTOS_RELAX_LOOPBACK_GUARD", default=False)
    app.add_middleware(
        InternalPathsGuard,
        public_paths=public_paths or _public_paths(),
        relax_loopback_guard=relax_loopback_guard,
    )


def _authorization_settings() -> tuple[bool, AuthorizationConfig | None]:
    """Preparado para RBAC.

    Cuando `AGENTOS_AUTHORIZATION=true`, exige `JWT_VERIFICATION_KEY` para
    no dejar el flag activo con una config vacía que podría terminar en
    "auth aprobando todo" según la implementación upstream. Mientras
    `AGENTOS_AUTHORIZATION=false`, el comportamiento no cambia.
    """
    enabled = _env_bool("AGENTOS_AUTHORIZATION", default=False)
    if not enabled:
        return False, None

    verification_key = os.environ.get("JWT_VERIFICATION_KEY")
    if not verification_key:
        raise RuntimeError(
            "AGENTOS_AUTHORIZATION=true requiere JWT_VERIFICATION_KEY "
            "con la clave pública para verificar los tokens."
        )
    algorithm = os.environ.get("JWT_ALGORITHM", "RS256")
    config = AuthorizationConfig(
        verification_keys=[verification_key],
        algorithm=algorithm,
    )
    return True, config


def build_agent_os(*, base_app: FastAPI) -> AgentOS:
    """Arma el AgentOS combinando la app FastAPI existente con los agentes.

    Aplica dos defensas por configuración:
    - `on_route_conflict="preserve_base_app"`: los routers de dominio ganan
      si AgentOS intenta registrar el mismo path.
    - `InternalPathsGuard` sobre `base_app`: AgentOS solo responde a
      loopback, mientras que los paths en `AGENTOS_PUBLIC_PATHS` (default
      `/health`, `/chat`, `/webhook`) quedan expuestos.
    """
    authorization, authorization_config = _authorization_settings()

    add_internal_paths_guard(base_app)

    return AgentOS(
        name="Vinoteca IA",
        description=(
            "Sistema multi-agente para vinoteca (Sommelier + Orders + "
            "Support + Router)."
        ),
        version="1.0.0",
        db=get_agno_db(),
        agents=[factory() for factory in AGENT_FACTORIES],
        teams=[factory() for factory in TEAM_FACTORIES],
        base_app=base_app,
        # No uses ["*"]: Agno hace merge en update_cors_middleware y elimina "*",
        # quedando allow_origins vacío → el browser en os.agno.com falla por CORS.
        # None delega en AgnoAPISettings (incluye https://os.agno.com, etc.).
        cors_allowed_origins=None,
        on_route_conflict="preserve_base_app",
        tracing=_env_bool("AGENTOS_TRACING", default=False),
        telemetry=_env_bool("AGENTOS_TELEMETRY", default=False),
        authorization=authorization,
        authorization_config=authorization_config,
    )
