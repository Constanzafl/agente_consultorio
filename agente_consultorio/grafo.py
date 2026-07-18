"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 2: Grafo LangGraph multi-agente
=============================================================================
Arquitectura:

    START -> guardarrail -> orquestador -> (agente_paciente | agente_medico) -> tools -> ... -> END
                    └── si URGENCIA -> END (escala, no sigue el flujo)

  - guardarrail   : primer filtro. Detecta urgencias médicas y escala (911/guardia).
  - orquestador   : rutea por ROL. Si la UI pasa el rol lo usa directo;
                    si no, un LLM lo clasifica según el mensaje (híbrido).
  - agente_paciente: 10 tools (turnos, recetas, consultas, memoria).
  - agente_medico  : tools de agenda, aprobar/rechazar, medicamentos (OpenFDA), PubMed.
  - Cada agente tiene su loop agente <-> ToolNode hasta que deja de pedir tools.

Memoria de CORTO plazo: MemorySaver (checkpointer) por thread_id.
Human-in-the-loop: el paciente solo CREA solicitudes (recetas/consultas) que
quedan 'pendientes'; el médico las aprueba/rechaza con sus tools.

LLM con failover multi-proveedor: ver llm.py (LM Studio local -> Gemini -> Groq -> HF).
=============================================================================
"""

import sys
from typing import Optional
from datetime import datetime

# Consola en UTF-8 (Windows) para no romper al imprimir caracteres especiales.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

# Imports robustos: funciona corriendo el archivo directo o como paquete
try:
    from .tools import tools_paciente, tools_medico
    from .llm import crear_llm, proveedores_disponibles
    from .rag import consultar_guias, consultar_guias_medico
    from .guardarrailes import detectar_urgencia, MENSAJE_URGENCIA
    from .skills_loader import cargar_skill, bloque_skills_para_prompt
    from .integraciones import notificar_paciente
except ImportError:
    from tools import tools_paciente, tools_medico
    from llm import crear_llm, proveedores_disponibles
    from rag import consultar_guias, consultar_guias_medico
    from guardarrailes import detectar_urgencia, MENSAJE_URGENCIA
    from skills_loader import cargar_skill, bloque_skills_para_prompt
    from integraciones import notificar_paciente

# Cada agente usa SU RAG de guías (paciente=educación, médico=clínicas) + skills.
tools_paciente = tools_paciente + [consultar_guias, cargar_skill]
# El médico puede además notificar a los pacientes por email.
tools_medico = tools_medico + [consultar_guias_medico, cargar_skill, notificar_paciente]


# =============================================================================
# 1. ESTADO DEL GRAFO
# =============================================================================

class EstadoConsultorio(MessagesState):
    """Estado compartido. MessagesState ya aporta `messages` (con add_messages)."""
    rol: str                        # "paciente" | "medico" | ""
    paciente_id: Optional[int]      # id del paciente en contexto (si se conoce)
    medico_id: Optional[int]        # id del médico logueado (si el rol es medico)
    urgencia: bool                  # True si el guardarrail detectó una urgencia


# =============================================================================
# 2. PROMPTS (guardarrailes base — los completos van en Fase 4)
# =============================================================================

PROMPT_ROUTER = (
    "Sos un clasificador de un consultorio médico. Según el mensaje, decidí si "
    "quien escribe es un PACIENTE (pide turnos, recetas, dudas sobre su medicación) "
    "o el MÉDICO (gestiona su agenda, aprueba recetas, consulta medicamentos o evidencia). "
    "Respondé UNA sola palabra en minúscula: paciente o medico."
)

PROMPT_PACIENTE = (
    "Sos el asistente virtual de un consultorio de medicina familiar, atendiendo a un PACIENTE.\n"
    "Podés: gestionar turnos, registrar pacientes nuevos, solicitar recetas y enviar consultas al médico.\n"
    "Para dudas sobre hábitos saludables o el manejo de enfermedades crónicas (HTA, DM2, etc.), "
    "usá la tool `consultar_guias` (busca en guías clínicas) y respondé SOLO con lo que traiga.\n\n"
    "REGLAS (guardarrailes):\n"
    "1. IDENTIFICÁ al paciente antes de cualquier acción que sea SOBRE él (ver sus turnos, "
    "pedir receta, enviar consulta): pedile el DNI y buscalo con `buscar_paciente` para obtener "
    "su ID. NUNCA asumas quién es ni inventes un paciente. Si no está registrado, ofrecé "
    "registrarlo. UNA VEZ que ya lo identificaste (ya tenés su ID de una búsqueda), NO lo "
    "vuelvas a buscar: seguí directamente con lo que pidió. (Para dudas generales de salud "
    "o hábitos no hace falta identificarlo.)\n"
    "2. Para BUSCAR información (consultar_guias, cargar_skill, ver turnos) "
    "llamá la tool DIRECTAMENTE, sin pedir permiso ni anunciar que la vas a usar. No preguntes "
    "'¿te parece bien?': simplemente usala y respondé con el resultado.\n"
    "3. NO diagnostiques ni prescribas. Vos NO sos el médico.\n"
    "4. Las recetas y consultas van dirigidas a UN médico específico: preguntá a cuál "
    "(mostralos con `listar_medicos`, o usá el médico de su último turno). SIEMPRE quedan "
    "PENDIENTES de aprobación (nunca las das por aprobadas).\n"
    "5. Ante señales de URGENCIA (dolor de pecho, dificultad para respirar, pérdida de conocimiento, "
    "déficit neurológico, sangrado importante), NO uses tools: indicá llamar al 911 o ir a una guardia YA.\n"
    "6. Pedí confirmación SOLO antes de acciones que MODIFICAN datos (sacar/cancelar turno, solicitar receta).\n"
    "7. Validá los datos (fechas YYYY-MM-DD, horas HH:MM) antes de llamar una tool que escribe.\n"
    "8. Para SACAR UN TURNO, seguí estos pasos EN ORDEN, uno por vez:\n"
    "   a) Pedí el DNI y buscá al paciente con `buscar_paciente`.\n"
    "   b) Si NO existe: registralo con `registrar_paciente` (pedí sus datos).\n"
    "   c) Si SÍ existe (ya lo encontraste): saludalo por su nombre y SEGUÍ, sin volver a buscarlo.\n"
    "   d) Preguntá el MOTIVO de la consulta.\n"
    "   e) Mostrá los médicos con `listar_medicos` y pedile que elija uno.\n"
    "   f) Mostrá los horarios con `consultar_agenda` y que elija fecha y hora.\n"
    "   g) Confirmá todo y reservá con `sacar_turno`.\n"
    "9. NO ofrezcas ni sugieras acciones que el paciente no pidió (no propongas sacar recetas "
    "ni hacer consultas: eso le genera trabajo innecesario al médico). Al terminar, cerrá con "
    "un simple '¿Necesitás algo más?' SIN dar ejemplos.\n"
    "10. Sé cálido, claro y breve. No uses emojis."
)

PROMPT_MEDICO = (
    "Sos el asistente del MÉDICO en un consultorio de medicina familiar. El USUARIO ES el "
    "médico (un profesional de la salud): respondé en lenguaje TÉCNICO, como apoyo a la "
    "decisión clínica. NUNCA le digas 'consulte a su médico' ni le hables como si fuera un "
    "paciente — él ES el médico. Podés dar opciones de tratamiento y de elección de fármacos "
    "basadas en guías/evidencia (la decisión final es del profesional).\n"
    "Podés: mostrar la agenda del día, revisar y aprobar/rechazar solicitudes de pacientes, "
    "consultar medicamentos (OpenFDA), guías clínicas y evidencia en PubMed, seguimiento de crónicos.\n\n"
    "REGLAS:\n"
    "0. Al INICIO de la conversación (primer saludo), ofrecele revisar las solicitudes "
    "pendientes: llamá `ver_solicitudes_pendientes` con su medico_id y contale qué recetas y "
    "consultas tiene sin resolver. Así no tiene que preguntarlo él.\n"
    "1. Para BUSCAR información (medicamentos, guías, PubMed, agenda, historial) llamá la tool "
    "DIRECTAMENTE, sin pedir permiso ni anunciarlo. Presentá el resultado de forma precisa.\n"
    "2. Para RECETAS pendientes: usá `aprobar_solicitud` o `rechazar_solicitud` (confirmá el ID "
    "antes de ejecutar). Al aprobar una receta, preguntá el DIAGNÓSTICO y pasalo en `diagnostico` "
    "(si el médico no lo indica, se usan las patologías de la ficha). Se genera el PDF de la receta "
    "y se le manda a la paciente. Para CONSULTAS de pacientes: usá `responder_consulta` con la "
    "respuesta del médico (NO aprobar/rechazar). En ambos casos el paciente recibe un email.\n"
    "3. Si te piden evidencia clínica, usá `buscar_pubmed` con términos en inglés. Después, "
    "escribí un RESUMEN EN ESPAÑOL (3-5 oraciones) de lo que dicen los abstracts, y recién "
    "al final listá los artículos como fuentes (título + link). No traduzcas literal: sintetizá.\n"
    "4. Para info de un medicamento usá `buscar_medicamento` (OpenFDA; el nombre en inglés) "
    "y resumí en español las indicaciones, dosis, advertencias y efectos adversos.\n"
    "5. Para decisiones clínicas basadas en guías (tratamiento, elección de fármacos, manejo "
    "de comorbilidades), usá `consultar_guias_medico` (guías profesionales). Si no hay guías "
    "cargadas o no alcanzan, complementá con `buscar_pubmed`.\n"
    "6. No inventes datos: si una tool no encuentra algo, decilo.\n"
    "7. No uses emojis."
)


# =============================================================================
# 3. NODOS
# =============================================================================

def _guardarrail_entrada(state: EstadoConsultorio) -> dict:
    """PRIMER filtro, SOLO para pacientes: si el mensaje describe una urgencia, escala y corta.
    Para el MÉDICO no aplica: puede hablar de síntomas en términos clínicos (o buscar 'chest pain'
    en PubMed) sin que se dispare la escalada al 911."""
    if state.get("rol") == "medico":
        return {"urgencia": False}
    ultimo_humano = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )
    if detectar_urgencia(str(ultimo_humano)):
        # Devuelve el mensaje de escalada y marca urgencia (el router corta acá)
        return {"messages": [AIMessage(content=MENSAJE_URGENCIA)], "urgencia": True}
    return {"urgencia": False}


def _ruta_guardarrail(state: EstadoConsultorio) -> str:
    """Si hubo urgencia, va directo a END (no pasa por los agentes)."""
    return END if state.get("urgencia") else "orquestador"


def _orquestar(state: EstadoConsultorio, llm_router) -> dict:
    """Ruteo híbrido: usa el rol si vino de la UI; si no, lo clasifica el LLM."""
    rol = (state.get("rol") or "").strip().lower()
    if rol in ("paciente", "medico"):
        return {"rol": rol}

    ultimo_humano = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )
    resp = llm_router.invoke([
        SystemMessage(content=PROMPT_ROUTER),
        HumanMessage(content=str(ultimo_humano)),
    ])
    texto = getattr(resp, "content", str(resp)).strip().lower()
    return {"rol": "medico" if "medico" in texto else "paciente"}


_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _nodo_agente(state: EstadoConsultorio, llm_con_tools, system_prompt: str) -> dict:
    """Nodo genérico de agente: arma el prompt de sistema + contexto e invoca el LLM."""
    prompt = system_prompt
    # El LLM no sabe qué día es: se lo decimos para que resuelva 'hoy', 'mañana', etc.
    hoy = datetime.now()
    prompt += (
        f"\n\nFECHA DE HOY: {hoy.strftime('%Y-%m-%d')} ({_DIAS[hoy.weekday()]}). "
        "Usá esta fecha para interpretar 'hoy', 'mañana', 'la semana que viene', etc. "
        "Calculá la fecha exacta (YYYY-MM-DD) antes de llamar cualquier tool de agenda/turnos."
    )
    bloque_skills = bloque_skills_para_prompt()
    if bloque_skills:
        prompt += "\n\n" + bloque_skills
    if state.get("paciente_id"):
        prompt += (
            f"\n\nContexto: el paciente en conversación tiene paciente_id="
            f"{state['paciente_id']}. Usalo en las tools que lo requieran sin volver a preguntarlo."
        )
    if state.get("medico_id"):
        prompt += (
            f"\n\nContexto: SOS el médico con medico_id={state['medico_id']}. "
            "Para los turnos de UN día usá ver_turnos_del_dia; para 'esta semana' / varios "
            "días usá ver_agenda_semana (UNA sola llamada, no consultes día por día). "
            "Para 'mis solicitudes/recetas pendientes' usá ver_solicitudes_pendientes. "
            "Pasales SIEMPRE tu medico_id. No vuelvas a preguntar qué médico sos."
        )
    mensajes = [SystemMessage(content=prompt)] + state["messages"]
    respuesta = llm_con_tools.invoke(mensajes)
    return {"messages": [respuesta]}


def _ruta_rol(state: EstadoConsultorio) -> str:
    return "agente_medico" if state.get("rol") == "medico" else "agente_paciente"


def _ruta_tools(state: EstadoConsultorio, nodo_tools: str) -> str:
    """Si el último mensaje del agente pide tools, va al ToolNode; si no, termina."""
    ultimo = state["messages"][-1]
    if getattr(ultimo, "tool_calls", None):
        return nodo_tools
    return END


# =============================================================================
# 4. CONSTRUCCIÓN DEL GRAFO
# =============================================================================

def construir_grafo(checkpointer=None):
    """
    Construye y compila el grafo multi-agente.

    Args:
        checkpointer: checkpointer de LangGraph (memoria corto plazo).
                      Por defecto MemorySaver en memoria.
    Returns:
        Grafo compilado (invocable con .invoke / .stream).
    """
    llm_paciente = crear_llm(tools=tools_paciente)
    llm_medico = crear_llm(tools=tools_medico)
    llm_router = crear_llm()  # sin tools, solo clasifica

    g = StateGraph(EstadoConsultorio)

    g.add_node("guardarrail", _guardarrail_entrada)
    g.add_node("orquestador", lambda s: _orquestar(s, llm_router))
    g.add_node("agente_paciente", lambda s: _nodo_agente(s, llm_paciente, PROMPT_PACIENTE))
    g.add_node("agente_medico", lambda s: _nodo_agente(s, llm_medico, PROMPT_MEDICO))
    g.add_node("tools_paciente", ToolNode(tools_paciente))
    g.add_node("tools_medico", ToolNode(tools_medico))

    # Todo entra primero por el guardarrail; si hay urgencia, corta en END.
    g.add_edge(START, "guardarrail")
    g.add_conditional_edges(
        "guardarrail", _ruta_guardarrail,
        {"orquestador": "orquestador", END: END},
    )
    g.add_conditional_edges(
        "orquestador", _ruta_rol,
        {"agente_paciente": "agente_paciente", "agente_medico": "agente_medico"},
    )
    g.add_conditional_edges(
        "agente_paciente", lambda s: _ruta_tools(s, "tools_paciente"),
        {"tools_paciente": "tools_paciente", END: END},
    )
    g.add_conditional_edges(
        "agente_medico", lambda s: _ruta_tools(s, "tools_medico"),
        {"tools_medico": "tools_medico", END: END},
    )
    g.add_edge("tools_paciente", "agente_paciente")
    g.add_edge("tools_medico", "agente_medico")

    return g.compile(checkpointer=checkpointer or MemorySaver())


# =============================================================================
# 5. HELPER DE CHAT (para testear rápido en consola)
# =============================================================================

def _extraer_texto(msg) -> str:
    """Saca el texto de un mensaje del LLM, tolerando content vacío o en formato de
    lista de bloques (algunos modelos de 'razonamiento' devuelven listas o vacío)."""
    contenido = getattr(msg, "content", "")
    if isinstance(contenido, list):
        partes = []
        for b in contenido:
            if isinstance(b, dict):
                partes.append(b.get("text") or b.get("content") or "")
            else:
                partes.append(str(b))
        contenido = "".join(partes)
    contenido = (contenido or "").strip()
    if not contenido:
        return ("(El modelo no devolvió una respuesta legible. Probá reformular la "
                "pregunta. Si pasa seguido, cambiá el modelo en LM Studio por uno "
                "'Instruct' sin modo de razonamiento.)")
    return contenido


def chatear(app, texto: str, thread_id: str = "demo",
            rol: str = "", paciente_id: Optional[int] = None,
            medico_id: Optional[int] = None) -> str:
    """Manda un mensaje al grafo y devuelve la respuesta final en texto."""
    entrada: dict = {"messages": [HumanMessage(content=texto)]}
    if rol:
        entrada["rol"] = rol
    if paciente_id is not None:
        entrada["paciente_id"] = paciente_id
    if medico_id is not None:
        entrada["medico_id"] = medico_id
    config = {"configurable": {"thread_id": thread_id}}
    resultado = app.invoke(entrada, config)
    return _extraer_texto(resultado["messages"][-1])


# =============================================================================
# 6. TEST RÁPIDO
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("GRAFO MULTI-AGENTE — Agente Consultorio")
    print("Proveedores LLM:", proveedores_disponibles())
    print("=" * 60)

    app = construir_grafo()

    print("\n--- PACIENTE: buscar turno (rol explícito) ---")
    print(chatear(app, "Hola, soy María González. ¿Qué turnos hay el próximo lunes?",
                  thread_id="t1", rol="paciente", paciente_id=1))

    print("\n--- MÉDICO: solicitudes pendientes (rol explícito) ---")
    print(chatear(app, "¿Qué solicitudes tengo pendientes de aprobar?",
                  thread_id="t2", rol="medico"))

    print("\n--- ORQUESTADOR: sin rol, que clasifique solo ---")
    print(chatear(app, "Necesito la dosis máxima de metformina y evidencia sobre su uso en insuficiencia renal",
                  thread_id="t3"))

    print("\n" + "=" * 60)
    print("Test del grafo ejecutado.")
    print("=" * 60)
