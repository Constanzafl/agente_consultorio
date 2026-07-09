"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 4: Guardarrailes (barreras de seguridad)
=============================================================================
El guardarrail más importante en un asistente médico: DETECTAR URGENCIAS.
Si el paciente describe una emergencia, el agente NO debe seguir el flujo
normal (turnos, recetas, guías) — debe FRENAR y escalar (911 / guardia).

Se hace por PALABRAS CLAVE (determinístico), no con el LLM: para una urgencia
queremos una regla segura y predecible, no que el modelo "decida" si es grave.

Otros guardarrailes (no diagnosticar, confirmar acciones, validar datos) viven
en los prompts de los agentes y en las validaciones de las tools.
=============================================================================
"""

import re
import unicodedata

# Señales de urgencia médica (en minúscula, sin acento). Cubrimos varias formas
# de decir lo mismo. Es una red de seguridad amplia a propósito.
SENiALES_URGENCIA = [
    "dolor de pecho", "dolor en el pecho", "opresion en el pecho", "puntada en el pecho",
    "duele el pecho", "me duele el pecho", "duele mucho el pecho", "me aprieta el pecho",
    "no puedo respirar", "dificultad para respirar", "me falta el aire", "falta de aire",
    "me ahogo", "me estoy ahogando",
    "desmayo", "me desmaye", "perdi el conocimiento", "perdida de conocimiento",
    "convulsion", "convulsiones", "ataque",
    "infarto", "acv", "derrame", "isquemia",
    "no siento el brazo", "no siento la pierna", "no puedo mover", "parte de la cara",
    "hemorragia", "sangrado abundante", "sangro mucho", "vomito con sangre",
    "me quiero morir", "me quiero matar", "suicid",
    "dolor muy fuerte", "dolor insoportable",
    "vision borrosa de repente", "no veo",
]

MENSAJE_URGENCIA = (
    "Esto puede ser una URGENCIA MÉDICA y no puedo ayudarte con eso por chat.\n\n"
    "Por favor, buscá atención inmediata AHORA:\n"
    "  - Llamá al 911 (o a tu servicio de emergencias local), o\n"
    "  - Andá a la guardia más cercana.\n\n"
    "Si estás con otra persona, pedile ayuda. No esperes."
)


def _normalizar(texto: str) -> str:
    """Pasa a minúscula y saca acentos, para comparar sin importar cómo se escriba."""
    texto = texto.lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


def detectar_urgencia(texto: str) -> bool:
    """
    True si el texto contiene señales de una posible urgencia médica.

    Args:
        texto: mensaje del paciente.
    Returns:
        True si hay que escalar (urgencia), False si no.
    """
    if not texto:
        return False
    t = _normalizar(texto)
    return any(re.search(r"\b" + re.escape(s) + r"\b", t) for s in SENiALES_URGENCIA)


if __name__ == "__main__":
    pruebas = [
        "Me duele mucho el pecho y no puedo respirar",   # urgencia
        "Quiero sacar un turno para control",            # normal
        "¿Qué hábitos me ayudan con la presión?",        # normal
        "Perdí el conocimiento hoy a la mañana",         # urgencia
    ]
    for p in pruebas:
        print(f"[{'URGENCIA' if detectar_urgencia(p) else 'normal  '}] {p}")
