"""Pipeline de conocimiento cualitativo (5 capas). Nunca indexa precio ni stock."""

from knowledge.capture.new_wine_onboarding import evaluar_nuevo_vino
from knowledge.capture.sommelier_interface import capture_nota_rapida
from knowledge.pipeline.conflict_resolver import resolve_conflicts
from knowledge.pipeline.enricher import enrich_ficha
from knowledge.pipeline.indexer import index_knowledge_fragment

__all__ = [
    "capture_nota_rapida",
    "enrich_ficha",
    "evaluar_nuevo_vino",
    "index_knowledge_fragment",
    "resolve_conflicts",
]
