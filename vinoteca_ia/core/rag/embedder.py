"""
Generación de embeddings usando la API de OpenAI (text-embedding-3-small).
"""

from __future__ import annotations

import os

import httpx

_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
_DIM = int(os.environ.get("EMBEDDING_DIM", "1536"))


async def generar_embedding(texto: str) -> list[float]:
    """Genera el embedding de un fragmento de texto."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY no configurada.")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": texto, "model": _MODEL},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


async def generar_embeddings_batch(textos: list[str]) -> list[list[float]]:
    """Genera embeddings para una lista de textos en una sola llamada API."""
    if not textos:
        return []

    api_key = os.environ.get("OPENAI_API_KEY", "")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": textos, "model": _MODEL},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]
