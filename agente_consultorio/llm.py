"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Factory de LLM con FAILOVER de proveedores
=============================================================================
Proveedor PRIMARIO: LM Studio local (modelo Instruct con tool-calling),
ilimitado y sin cuota. Groq queda como failover cloud usando `.with_fallbacks()`
de LangChain: si LM Studio no está levantado (o falla), y hay clave de Groq
cargada, el grafo usa Groq sin cambiar una línea.

Orden por defecto:  lmstudio -> groq
  - lmstudio : modelo LOCAL sin límite de cuota (PRIMARIO, ideal para tools)
  - groq     : free tier, muy rápido (fallback cloud)

Se incluye un proveedor SOLO si su config está lista (LM Studio: si el server
local está escuchando; Groq: si hay GROQ_API_KEY). Con uno solo alcanza.

Uso:
    from llm import crear_llm
    llm = crear_llm()                 # para clasificar / texto
    llm_tools = crear_llm(tools=mis_tools)   # con tools ligadas + failover
=============================================================================
"""

import os
import socket
from dotenv import load_dotenv

load_dotenv()


def _config_langsmith():
    """Evita el spam de errores 401 de LangSmith cuando TRACING=true sin API key.
    Si falta la key, apaga el tracing; cuando la cargues, se prende solo."""
    quiere = os.getenv("LANGSMITH_TRACING", "").strip().lower() == "true"
    tiene_key = bool(os.getenv("LANGSMITH_API_KEY", "").strip())
    if quiere and not tiene_key:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
    elif quiere and tiene_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"  # compatibilidad libs viejas


_config_langsmith()

# Orden de failover configurable por env (LM Studio local como primario)
ORDEN_DEFAULT = ["anthropic", "lmstudio", "groq"]

# Modelos por defecto (se pueden pisar por env). Para lmstudio "" = auto-detectar
# el modelo que esté cargado en el server.
MODELOS_DEFAULT = {
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-haiku-4-5",  # barato y muy bueno con tools (subí a sonnet si hace falta)
    "lmstudio": "",  # vacío => se detecta el modelo cargado en LM Studio
}


def _seteada(valor: str | None) -> bool:
    """True si la variable tiene un valor real (no vacío ni placeholder)."""
    if not valor:
        return False
    v = valor.strip().lower()
    return v != "" and not v.startswith("tu_clave") and not v.startswith("tu_")


def _lmstudio_activo(base_url: str) -> bool:
    """Chequea si el server local de LM Studio está escuchando (sin colgar)."""
    try:
        host = base_url.split("//", 1)[-1].split("/", 1)[0]
        nombre, _, puerto = host.partition(":")
        with socket.create_connection((nombre, int(puerto or 80)), timeout=0.5):
            return True
    except OSError:
        return False


def _lmstudio_modelo(base_url: str) -> str:
    """Devuelve el id del modelo cargado en LM Studio (consultando /models).
    Si no puede detectarlo, usa 'local-model' (LM Studio enruta al que tenga cargado)."""
    forzado = os.getenv("LMSTUDIO_MODEL", "").strip()
    if forzado:
        return forzado
    try:
        import requests
        r = requests.get(f"{base_url.rstrip('/')}/models", timeout=1.5)
        return r.json()["data"][0]["id"]
    except Exception:
        return "local-model"


# --- Constructores por proveedor (importan perezoso para no exigir todas las libs) ---

def _build_groq(temperature: float):
    from langchain_groq import ChatGroq
    return ChatGroq(
        model=os.getenv("GROQ_MODEL", MODELOS_DEFAULT["groq"]),
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=temperature,
    )


def _build_anthropic(temperature: float):
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=os.getenv("ANTHROPIC_MODEL", MODELOS_DEFAULT["anthropic"]),
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=temperature,
    )


def _build_lmstudio(temperature: float):
    from langchain_openai import ChatOpenAI
    base_url = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    return ChatOpenAI(
        model=_lmstudio_modelo(base_url),  # auto-detecta el modelo cargado
        base_url=base_url,
        api_key="lm-studio",  # LM Studio ignora la key
        temperature=temperature,
    )


_BUILDERS = {
    "groq": _build_groq,
    "anthropic": _build_anthropic,
    "lmstudio": _build_lmstudio,
}


def _disponible(proveedor: str) -> bool:
    """True si el proveedor tiene su config lista para usarse."""
    if proveedor == "groq":
        return _seteada(os.getenv("GROQ_API_KEY"))
    if proveedor == "anthropic":
        return _seteada(os.getenv("ANTHROPIC_API_KEY"))
    if proveedor == "lmstudio":
        return _lmstudio_activo(os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"))
    return False


def proveedores_disponibles() -> list[str]:
    """Lista, en orden de failover, los proveedores configurados y usables."""
    orden = os.getenv("LLM_PROVIDER_ORDER")
    orden = [p.strip() for p in orden.split(",")] if orden else ORDEN_DEFAULT
    return [p for p in orden if p in _BUILDERS and _disponible(p)]


def crear_llm(tools: list | None = None, temperature: float = 0.0):
    """
    Devuelve un LLM (Runnable) con failover entre los proveedores configurados.
    Si se pasan `tools`, quedan ligadas a cada proveedor.

    Args:
        tools: lista de tools LangChain a ligar (opcional).
        temperature: temperatura de muestreo (0 = determinístico).
    Returns:
        Runnable de chat. Si hay más de un proveedor, es un
        RunnableWithFallbacks que va cayendo al siguiente ante errores.
    Raises:
        RuntimeError si no hay ningún proveedor configurado.
    """
    activos = proveedores_disponibles()
    if not activos:
        raise RuntimeError(
            "No hay ningún proveedor de LLM disponible. Levantá LM Studio "
            "(Developer -> Start Server, con un modelo Instruct cargado) o "
            "cargá GROQ_API_KEY en .env."
        )

    modelos = []
    for nombre in activos:
        modelo = _BUILDERS[nombre](temperature)
        if tools:
            modelo = modelo.bind_tools(tools)
        modelos.append(modelo)

    primario, *resto = modelos
    return primario.with_fallbacks(resto) if resto else primario


if __name__ == "__main__":
    print("Proveedores disponibles (en orden de failover):", proveedores_disponibles())
    try:
        llm = crear_llm()
        resp = llm.invoke("Respondé solo con la palabra: OK")
        print("Respuesta:", getattr(resp, "content", resp))
    except Exception as e:
        print("Error:", e)
