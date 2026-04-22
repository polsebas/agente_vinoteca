"""Entrypoint legado: la app real vive en `api.main`.

Se mantiene por compatibilidad con comandos previos (`uvicorn playground:app`).
El runtime productivo ahora combina FastAPI + AgentOS en un solo proceso vía
`core.agent_os_factory.build_agent_os`, por lo que reexportamos `app` desde
`api.main` y evitamos montar un segundo AgentOS con un lifespan paralelo.

Uso recomendado:

    uvicorn api.main:app --reload
"""

from __future__ import annotations

from api.main import app

__all__ = ["app"]
