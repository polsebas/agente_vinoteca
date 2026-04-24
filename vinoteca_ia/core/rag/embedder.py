"""
Generación de embeddings local con BETO en Hugging Face.

Modelo default: dccuchile/bert-base-spanish-wwm-uncased
Estrategia: mean pooling ponderado por attention mask + normalización L2.
"""

from __future__ import annotations

import asyncio
import os
import threading

import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

_MODEL_NAME = os.environ.get(
    "HF_EMBEDDING_MODEL",
    "dccuchile/bert-base-spanish-wwm-uncased",
)
_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
_MAX_LENGTH = int(os.environ.get("EMBEDDING_MAX_LENGTH", "512"))
_DEVICE_PREF = os.environ.get("EMBEDDING_DEVICE", "auto").lower()

_MODEL_LOCK = threading.Lock()
_TOKENIZER = None
_MODEL = None
_DEVICE = None


def _resolve_device() -> str:
    if _DEVICE_PREF in {"cpu", "cuda"}:
        return _DEVICE_PREF
    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_model():
    global _TOKENIZER, _MODEL, _DEVICE
    if _TOKENIZER is not None and _MODEL is not None and _DEVICE is not None:
        return _TOKENIZER, _MODEL, _DEVICE

    with _MODEL_LOCK:
        if _TOKENIZER is None or _MODEL is None or _DEVICE is None:
            _TOKENIZER = AutoTokenizer.from_pretrained(_MODEL_NAME)
            _MODEL = AutoModel.from_pretrained(_MODEL_NAME)
            _DEVICE = torch.device(_resolve_device())
            _MODEL.to(_DEVICE)
            _MODEL.eval()
    return _TOKENIZER, _MODEL, _DEVICE


def _encode_sync(textos: list[str]) -> list[list[float]]:
    tokenizer, model, device = _load_model()
    entradas = tokenizer(
        [t if t.strip() else " " for t in textos],
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=_MAX_LENGTH,
    )
    entradas = {k: v.to(device) for k, v in entradas.items()}

    with torch.inference_mode():
        salida = model(**entradas)
        hidden = salida.last_hidden_state  # [batch, seq, hidden]
        mask = entradas["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
        sum_hidden = torch.sum(hidden * mask, dim=1)
        sum_mask = torch.clamp(mask.sum(dim=1), min=1e-9)
        emb = sum_hidden / sum_mask
        emb = F.normalize(emb, p=2, dim=1)

    if emb.shape[1] != _DIM:
        raise ValueError(
            f"Dimensión inesperada para embeddings: {emb.shape[1]} (esperada {_DIM})"
        )
    return emb.cpu().tolist()


async def generar_embedding(texto: str) -> list[float]:
    """Genera el embedding de un fragmento de texto."""
    embeddings = await generar_embeddings_batch([texto])
    return embeddings[0]


async def generar_embeddings_batch(textos: list[str]) -> list[list[float]]:
    """Genera embeddings para una lista de textos con inferencia local."""
    if not textos:
        return []
    return await asyncio.to_thread(_encode_sync, textos)
