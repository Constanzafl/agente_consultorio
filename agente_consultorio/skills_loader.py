"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 5: Skills (playbooks modulares)
=============================================================================
Un "skill" es un instructivo (playbook) guardado en skills/*.md. El agente NO
carga todos los instructivos en el prompt: solo ve una LISTA (nombre + una línea
de descripción) y, cuando el tema aplica, carga el skill completo con la tool
`cargar_skill`. Es la idea de "progressive disclosure" de Deep Agents, pero
implementada sobre LangGraph.

Cada archivo skills/<nombre>.md:
  - el nombre del archivo (sin .md) es el id del skill
  - una línea "descripcion: ..." es el resumen que se muestra en el prompt
  - el resto son las instrucciones que sigue el agente al cargarlo
=============================================================================
"""

import pathlib
from langchain.tools import tool

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DIR_SKILLS = RAIZ / "skills"


def _descripcion(texto: str) -> str:
    """Saca la línea 'descripcion:' del archivo; si no está, usa el primer título."""
    for linea in texto.splitlines():
        if linea.lower().startswith("descripcion:"):
            return linea.split(":", 1)[1].strip()
    for linea in texto.splitlines():
        if linea.startswith("#"):
            return linea.lstrip("#").strip()
    return ""


def listar_skills() -> list[tuple[str, str]]:
    """Devuelve [(nombre, descripcion)] de todos los skills disponibles."""
    if not DIR_SKILLS.exists():
        return []
    skills = []
    for f in sorted(DIR_SKILLS.glob("*.md")):
        skills.append((f.stem, _descripcion(f.read_text(encoding="utf-8"))))
    return skills


def bloque_skills_para_prompt() -> str:
    """Arma el texto con la lista de skills para inyectar en el prompt del agente."""
    skills = listar_skills()
    if not skills:
        return ""
    lineas = [
        "SKILLS DISPONIBLES (playbooks). Si el tema coincide con uno, primero cargalo "
        "con la tool `cargar_skill(nombre)` y seguí sus pasos:"
    ]
    for nombre, desc in skills:
        lineas.append(f"  - {nombre}: {desc}")
    return "\n".join(lineas)


@tool
def cargar_skill(nombre: str) -> str:
    """
    Carga el playbook (skill) indicado y devuelve sus instrucciones detalladas para
    seguir en la conversación. Usar cuando el tema del paciente coincide con un skill
    de la lista de skills disponibles.

    Args:
        nombre: nombre del skill a cargar (ej: 'educacion_habitos').
    Returns:
        El contenido/instrucciones del skill, o un aviso si no existe.
    """
    archivo = DIR_SKILLS / f"{nombre}.md"
    if not archivo.exists():
        disponibles = ", ".join(n for n, _ in listar_skills()) or "ninguno"
        return f"No existe el skill '{nombre}'. Disponibles: {disponibles}."
    return archivo.read_text(encoding="utf-8")


if __name__ == "__main__":
    print("Skills disponibles:")
    for nombre, desc in listar_skills():
        print(f"  - {nombre}: {desc}")
    print("\n--- Contenido de 'educacion_habitos' ---")
    print(cargar_skill.invoke({"nombre": "educacion_habitos"}))
