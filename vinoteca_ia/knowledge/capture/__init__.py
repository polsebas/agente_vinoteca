"""Captura rápida de conocimiento del sumiller y onboarding de SKUs."""

from knowledge.capture.new_wine_onboarding import evaluar_nuevo_vino
from knowledge.capture.sommelier_interface import capture_nota_rapida, confirmar_captura

__all__ = ["capture_nota_rapida", "confirmar_captura", "evaluar_nuevo_vino"]
