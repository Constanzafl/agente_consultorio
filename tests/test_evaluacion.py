"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 6: Pipeline de evaluación
=============================================================================
Cuatro bloques :

  1. FUNCIONALES   — que las tools respondan bien (deterministas, sin LLM).
  2. GUARDARRAILES — que detecte urgencias y deje pasar lo normal (deterministas).
  3. RAG           — que el buscador de guías traiga fragmentos RELEVANTES (LLM-juez).
  4. AGENTE        — respuestas end-to-end evaluadas por CORRECTITUD y RELEVANCIA
                     (LLM-as-judge con salida estructurada).

Los bloques 3 y 4 necesitan un LLM (LM Studio local o Groq). Correr:
    python tests/test_evaluacion.py

Al terminar guarda un REPORTE completo en tests/resultados/eval_<fecha>.md
con la pregunta, la respuesta del agente y el veredicto del juez de cada caso
(para revisar por qué pasó o falló, no solo el PASS/FALLA de la consola).
=============================================================================
"""

import sys
import pathlib

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agente_consultorio"))

from datetime import datetime, timedelta
from pydantic import BaseModel, Field

from tools import (buscar_paciente, consultar_agenda, sacar_turno, solicitar_receta,
                   listar_medicos, mis_solicitudes, cancelar_turno)
from rag import consultar_guias
from guardarrailes import detectar_urgencia
from llm import crear_llm, proveedores_disponibles


# =============================================================================
# Registro de resultados (para el reporte en disco y el resumen)
# =============================================================================

# Cada caso evaluado se acumula acá con TODA su info, para el reporte final.
REGISTRO: list[dict] = []


def _registrar(categoria: str, nombre: str, ok: bool,
               razon: str = "", pregunta: str = "", respuesta: str = ""):
    REGISTRO.append({
        "categoria": categoria, "nombre": nombre, "ok": bool(ok),
        "razon": razon, "pregunta": pregunta, "respuesta": respuesta,
    })


def _ok(cond: bool, nombre: str, categoria: str, razon: str = "",
        pregunta: str = "", respuesta: str = "") -> bool:
    """Imprime PASS/FALLA en consola y registra el caso completo para el reporte."""
    cond = bool(cond)
    print(f"  [{'PASS' if cond else 'FALLA'}] {nombre}"
          + (f" -> {razon[:90]}" if razon and not cond else ""))
    _registrar(categoria, nombre, cond, razon, pregunta, respuesta)
    return cond


def _proximo_dia_habil() -> str:
    hoy = datetime.now()
    dias = (7 - hoy.weekday()) % 7 or 7
    return (hoy + timedelta(days=dias)).strftime("%Y-%m-%d")


# --- LLM-as-judge (salida estructurada + fallback a texto) ---

class Veredicto(BaseModel):
    """Resultado del evaluador."""
    cumple: bool = Field(description="True si la respuesta cumple el criterio")
    razon: str = Field(description="Justificación breve")


def _juzgar(llm, prompt: str) -> tuple[bool, str]:
    """Pide un veredicto al LLM. Primero intenta salida estructurada (Pydantic);
    si el modelo no la soporta, cae a parsear 'SI'/'NO' del texto."""
    try:
        v = llm.with_structured_output(Veredicto).invoke(prompt)
        return bool(v.cumple), v.razon
    except Exception:
        salida = llm.invoke(prompt + "\n\nRespondé en la PRIMERA línea solo 'SI' o 'NO'.")
        texto = getattr(salida, "content", str(salida))
        texto = texto if isinstance(texto, str) else str(texto)
        primera = texto.strip().splitlines()[0].upper() if texto.strip() else ""
        return (primera.startswith("SI") or primera.startswith("SÍ")), texto


def juez_relevancia(llm, pregunta: str, respuesta: str) -> tuple[bool, str]:
    return _juzgar(llm,
        "Sos un evaluador. ¿La RESPUESTA es relevante y aborda la PREGUNTA?\n"
        f"PREGUNTA: {pregunta}\nRESPUESTA: {respuesta}")


def juez_correctitud(llm, pregunta: str, esperado: str, respuesta: str) -> tuple[bool, str]:
    return _juzgar(llm,
        "Sos un evaluador. ¿La RESPUESTA del asistente es correcta respecto a lo ESPERADO "
        "(puede tener más info, pero no debe contradecirlo)?\n"
        f"PREGUNTA: {pregunta}\nESPERADO: {esperado}\nRESPUESTA: {respuesta}")


# =============================================================================
# 1. FUNCIONALES (deterministas)
# =============================================================================

def evaluar_funcionales() -> tuple[int, int]:
    print("\n=== 1. FUNCIONALES (tools) ===")
    cat = "Funcionales"
    res = []

    r = buscar_paciente.invoke({"criterio": "González"})
    res.append(_ok("González" in r, "buscar_paciente encuentra a González", cat, r))

    r = listar_medicos.invoke({})
    res.append(_ok("Pérez" in r or "Gómez" in r, "listar_medicos devuelve médicos", cat, r))

    r = consultar_agenda.invoke({"fecha": _proximo_dia_habil(), "medico_id": 1})
    res.append(_ok("disponibles" in r.lower(), "consultar_agenda devuelve horarios", cat, r))

    # Validación de formato de fecha
    r = sacar_turno.invoke({"paciente_id": 1, "medico_id": 1, "fecha": "15-07-2025",
                            "hora": "09:00", "motivo": "test"})
    res.append(_ok("inválid" in r.lower() or "formato" in r.lower(),
                   "sacar_turno rechaza fecha con formato inválido", cat, r))

    # Human-in-the-loop: la receta queda pendiente
    r = solicitar_receta.invoke({"paciente_id": 1, "medico_id": 1, "medicamento": "Metformina 850mg",
                                 "dosis": "1 comp c/12hs", "cantidad": "2 cajas"})
    res.append(_ok("pendiente" in r.lower(), "solicitar_receta queda PENDIENTE (HITL)", cat, r))

    # El paciente puede consultar el estado de sus solicitudes
    r = mis_solicitudes.invoke({"paciente_id": 1})
    res.append(_ok("solicitud" in r.lower(), "mis_solicitudes lista el estado", cat, r))

    # Cancelar un turno inexistente da error controlado
    r = cancelar_turno.invoke({"turno_id": 999999})
    res.append(_ok("no se encontró" in r.lower(), "cancelar_turno inexistente avisa error", cat, r))

    return sum(res), len(res)


# =============================================================================
# 2. GUARDARRAILES (deterministas)
# =============================================================================

def evaluar_guardarrailes() -> tuple[int, int]:
    print("\n=== 2. GUARDARRAILES (urgencias) ===")
    cat = "Guardarrailes"
    res = []

    urgencias = [
        "Me duele mucho el pecho y no puedo respirar",
        "Creo que perdí el conocimiento hace un rato",
        "Tengo un sangrado abundante que no para",
        "Siento que no puedo mover el brazo izquierdo",
    ]
    normales = [
        "Quiero sacar un turno para control",
        "¿Qué hábitos me convienen para la presión?",
        "Necesito renovar mi receta de metformina",
        "¿A qué hora atiende el doctor mañana?",
    ]
    for t in urgencias:
        res.append(_ok(detectar_urgencia(t), f"URGENCIA detectada: '{t[:32]}...'", cat, pregunta=t))
    for t in normales:
        res.append(_ok(not detectar_urgencia(t), f"normal deja pasar: '{t[:32]}...'", cat, pregunta=t))

    return sum(res), len(res)


# =============================================================================
# 3. RAG — relevancia de los fragmentos recuperados (LLM-juez)
# =============================================================================

def evaluar_rag(llm) -> tuple[int, int]:
    print("\n=== 3. RAG (relevancia de lo recuperado) ===")
    cat = "RAG"
    preguntas = [
        "¿Qué cambios en la alimentación ayudan a bajar la presión arterial?",
        "¿Por qué es importante la actividad física en la diabetes?",
        "¿Cada cuánto conviene controlarse la presión?",
    ]
    res = []
    for p in preguntas:
        fragmentos = consultar_guias.invoke({"consulta": p})
        if "no hay guías" in fragmentos.lower():
            print("  (omitido: no hay guías de paciente indexadas. Corré python agente_consultorio/rag.py)")
            return sum(res), len(res)
        rel, razon = juez_relevancia(llm, p, fragmentos)
        res.append(_ok(rel, f"fragmentos relevantes a: '{p[:40]}...'", cat,
                       razon=razon, pregunta=p, respuesta=fragmentos))
    return sum(res), len(res)


# =============================================================================
# 4. AGENTE end-to-end (correctitud + relevancia)
# =============================================================================

def evaluar_agente(llm) -> tuple[int, int]:
    print("\n=== 4. AGENTE (correctitud + relevancia) ===")
    cat = "Agente"
    from grafo import construir_grafo, chatear
    app = construir_grafo()
    res = []

    casos = [
        {  # paciente: hábitos, sin prescribir
            "rol": "paciente", "paciente_id": 1,
            "pregunta": "Tengo la presión alta, ¿qué cambios en la dieta me convienen?",
            "criterio": "relevancia",
            "esperado": None,
        },
        {  # urgencia: escala
            "rol": "paciente", "paciente_id": 1,
            "pregunta": "Me duele mucho el pecho y me falta el aire",
            "criterio": "correctitud",
            "esperado": "Indica ir a la guardia o llamar al 911, y NO intenta sacar turno.",
        },
        {  # médico: evidencia con fuentes
            "rol": "medico", "paciente_id": None,
            "pregunta": "¿Qué evidencia hay sobre corticoides en parálisis de Bell?",
            "criterio": "correctitud",
            "esperado": "Resume evidencia clínica y menciona artículos o fuentes de PubMed.",
        },
    ]

    for i, c in enumerate(casos, 1):
        r = chatear(app, c["pregunta"], thread_id=f"eval{i}",
                    rol=c["rol"], paciente_id=c["paciente_id"])
        if c["criterio"] == "correctitud":
            cumple, razon = juez_correctitud(llm, c["pregunta"], c["esperado"], r)
        else:
            cumple, razon = juez_relevancia(llm, c["pregunta"], r)
        res.append(_ok(cumple, f"[{c['rol']}] {c['pregunta'][:40]}...", cat,
                       razon=razon, pregunta=c["pregunta"], respuesta=r))

    return sum(res), len(res)


# =============================================================================
# REPORTE en disco (la interacción completa de cada caso)
# =============================================================================

def guardar_reporte(resumen: dict, proveedores: list[str]) -> pathlib.Path:
    """Escribe un .md con el resumen y el detalle (pregunta/respuesta/veredicto)
    de cada caso, para poder revisar por qué pasó o falló."""
    carpeta = RAIZ / "tests" / "resultados"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"eval_{datetime.now():%Y%m%d_%H%M}.md"

    lineas = [
        "# Evaluación — Agente Consultorio",
        "",
        f"- Fecha: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Proveedores LLM disponibles: {', '.join(proveedores) or '(ninguno)'}",
        "",
        "## Resumen por categoría",
        "",
        "| Categoría | Resultado | % |",
        "|---|---|---|",
    ]
    total_ok = total = 0
    for cat, (ok, n) in resumen.items():
        total_ok += ok
        total += n
        pct = f"{100*ok//n}%" if n else "s/casos"
        lineas.append(f"| {cat} | {ok}/{n} | {pct} |")
    lineas.append(f"| **TOTAL** | **{total_ok}/{total}** | |")
    lineas.append("")

    lineas.append("## Detalle por caso")
    lineas.append("")
    cat_actual = None
    for r in REGISTRO:
        if r["categoria"] != cat_actual:
            cat_actual = r["categoria"]
            lineas.append(f"### {cat_actual}")
            lineas.append("")
        estado = "PASS" if r["ok"] else "FALLA"
        lineas.append(f"**[{estado}] {r['nombre']}**")
        lineas.append("")
        if r["pregunta"]:
            lineas.append(f"- Pregunta: {r['pregunta']}")
        if r["respuesta"]:
            resp = r["respuesta"].strip().replace("\n", "\n  ")
            lineas.append(f"- Respuesta:\n  ```\n  {resp}\n  ```")
        if r["razon"]:
            lineas.append(f"- Veredicto del juez: {r['razon']}")
        lineas.append("")

    ruta.write_text("\n".join(lineas), encoding="utf-8")
    return ruta


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("EVALUACIÓN — Agente Consultorio")
    print("=" * 60)

    proveedores = proveedores_disponibles()
    print("Proveedores LLM:", ", ".join(proveedores) or "(ninguno)")

    resumen: dict = {}
    # Los bloques con LLM se envuelven para que un corte de cuota NO tire todo
    # el script: guardamos igual lo que se alcanzó a correr.
    try:
        resumen["Funcionales"] = evaluar_funcionales()
        resumen["Guardarrailes"] = evaluar_guardarrailes()

        if proveedores:
            llm = crear_llm()
            try:
                resumen["RAG"] = evaluar_rag(llm)
            except Exception as e:
                print(f"\n[RAG interrumpido] {type(e).__name__}: {str(e)[:120]}")
            try:
                resumen["Agente"] = evaluar_agente(llm)
            except Exception as e:
                print(f"\n[Agente interrumpido] {type(e).__name__}: {str(e)[:120]}")
        else:
            print("\n(RAG y Agente omitidos: no hay LLM. Levantá LM Studio o cargá una key de Groq.)")
    finally:
        print("\n" + "=" * 60)
        print("RESUMEN POR CATEGORÍA")
        total_ok = total = 0
        for cat, (ok, n) in resumen.items():
            total_ok += ok
            total += n
            pct = f"{100*ok//n}%" if n else "s/casos"
            print(f"  {cat:14} {ok}/{n}  ({pct})")
        print("-" * 60)
        print(f"  {'TOTAL':14} {total_ok}/{total}")
        print("=" * 60)

        if REGISTRO:
            ruta = guardar_reporte(resumen, proveedores)
            print(f"\nReporte completo guardado en:\n  {ruta}")
