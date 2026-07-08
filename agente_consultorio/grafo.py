"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 2: Grafo LangGraph multi-agente
=============================================================================
Arquitectura:

    START -> orquestador -> (agente_paciente | agente_medico) -> tools -> ... -> END

  - orquestador   : rutea por ROL. Si la UI pasa el rol lo usa directo;
                    si no, un LLM lo clasifica según el mensaje (híbrido).
  - agente_paciente: 10 tools (turnos, recetas, consultas, memoria).
  - agente_medico  : 12 tools (agenda, aprobar/rechazar, vademecum, PubMed).
  - Cada agente tiene su loop agente <-> ToolNode hasta que deja de pedir tools.

Memoria de CORTO plazo: MemorySaver (checkpointer) por thread_id.
Human-in-the-loop: el paciente solo CREA solicitudes (recetas/consultas) que
quedan 'pendientes'; el médico las aprueba/rechaza con sus tools.

LLM con failover multi-proveedor: ver llm.py (LM Studio local -> Gemini -> Groq -> HF).
=============================================================================
"""

from typing import Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

# Imports robustos: funciona corriendo el archivo directo o como paquete
try:
    from .db_y_tools import tools_paciente, tools_medico
    from .llm import crear_llm, proveedores_disponibles
except ImportError:
    from db_y_tools import tools_paciente, tools_medico
    from llm import crear_llm, proveedores_disponibles


# =============================================================================
# 1. ESTADO DEL GRAFO
# =============================================================================

class EstadoConsultorio(MessagesState):
    """Estado compartido. MessagesState ya aporta `messages` (con add_messages)."""
    rol: str                        # "paciente" | "medico" | ""
    paciente_id: Optional[int]      # id del paciente en contexto (si se conoce)


# =============================================================================
# 2. PROMPTS (guardarrailes base — los completos van en Fase 4)
# =============================================================================

PROMPT_ROUTER = (
    "Sos un clasificador de un consultorio médico. Según el mensaje, decidí si "
    "quien escribe es un PACIENTE (pide turnos, recetas, dudas sobre su medicación) "
    "o el MÉDICO (gestiona su agenda, aprueba recetas, consulta vademecum o evidencia). "
    "Respondé UNA sola palabra en minúscula: paciente o medico."
)

PROMPT_PACIENTE = (
    "Sos el asistente virtual de un consultorio de medicina familiar, atendiendo a un PACIENTE.\n"
    "Podés: gestionar turnos, registrar pacientes nuevos, solicitar recetas y enviar consultas al médico.\n\n"
    "REGLAS (guardarrailes):\n"
    "1. NO diagnostiques ni prescribas. Vos NO sos el médico.\n"
    "2. Las recetas y consultas SIEMPRE quedan PENDIENTES de aprobación del médico (nunca las das por aprobadas).\n"
    "3. Ante señales de URGENCIA (dolor de pecho, dificultad para respirar, pérdida de conocimiento, "
    "déficit neurológico, sangrado importante), NO uses tools: indicá llamar al 911 o ir a una guardia YA.\n"
    "4. Confirmá con el paciente antes de acciones que modifican datos (sacar/cancelar turno, solicitar receta).\n"
    "5. Validá los datos (fechas YYYY-MM-DD, horas HH:MM) antes de llamar una tool.\n"
    "6. Sé cálido, claro y breve."
)

PROMPT_MEDICO = (
    "Sos el asistente del MÉDICO en un consultorio de medicina familiar.\n"
    "Podés: mostrar la agenda del día, revisar y aprobar/rechazar solicitudes de pacientes, "
    "consultar el vademecum, buscar evidencia en PubMed y hacer seguimiento de crónicos.\n\n"
    "REGLAS:\n"
    "1. Presentá la información de forma precisa y accionable; el médico decide.\n"
    "2. Para aprobar/rechazar una solicitud, confirmá cuál (por ID) antes de ejecutar.\n"
    "3. Si te piden evidencia clínica, usá PubMed con términos en inglés.\n"
    "4. No inventes datos de vademecum: si la tool no lo encuentra, decilo."
)


# =============================================================================
# 3. NODOS
# =============================================================================

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


def _nodo_agente(state: EstadoConsultorio, llm_con_tools, system_prompt: str) -> dict:
    """Nodo genérico de agente: arma el prompt de sistema + contexto e invoca el LLM."""
    prompt = system_prompt
    if state.get("paciente_id"):
        prompt += (
            f"\n\nContexto: el paciente en conversación tiene paciente_id="
            f"{state['paciente_id']}. Usalo en las tools que lo requieran sin volver a preguntarlo."
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

    g.add_node("orquestador", lambda s: _orquestar(s, llm_router))
    g.add_node("agente_paciente", lambda s: _nodo_agente(s, llm_paciente, PROMPT_PACIENTE))
    g.add_node("agente_medico", lambda s: _nodo_agente(s, llm_medico, PROMPT_MEDICO))
    g.add_node("tools_paciente", ToolNode(tools_paciente))
    g.add_node("tools_medico", ToolNode(tools_medico))

    g.add_edge(START, "orquestador")
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

def chatear(app, texto: str, thread_id: str = "demo",
            rol: str = "", paciente_id: Optional[int] = None) -> str:
    """Manda un mensaje al grafo y devuelve la respuesta final en texto."""
    entrada: dict = {"messages": [HumanMessage(content=texto)]}
    if rol:
        entrada["rol"] = rol
    if paciente_id is not None:
        entrada["paciente_id"] = paciente_id
    config = {"configurable": {"thread_id": thread_id}}
    resultado = app.invoke(entrada, config)
    return resultado["messages"][-1].content


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
