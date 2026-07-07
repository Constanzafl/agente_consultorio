"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Factory de LLM con FAILOVER de proveedores
=============================================================================
Problema: el free tier de Gemini se agota rápido. Solución: una cadena de
proveedores con failover automático usando `.with_fallbacks()` de LangChain.
Cuando un proveedor tira error (rate limit, cuota agotada, caída), el grafo
usa el siguiente que esté configurado, sin cambiar una línea del grafo.

Orden por defecto:  gemini -> groq -> huggingface -> lmstudio
  - gemini      : free tier, primario (cuota baja)
  - groq        : free tier, muy rápido, límites más generosos
  - huggingface : inference API gratis (tool-calling best-effort)
  - lmstudio    : modelo LOCAL sin límite de cuota (última red de seguridad)

Se incluye un proveedor SOLO si su clave/config está presente. Con tener una
sola alcanza para arrancar.

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

# Orden de failover configurable por env
ORDEN_DEFAULT = ["gemini", "groq", "huggingface", "lmstudio"]

# Modelos por defecto (se pueden pisar por env)
MODELOS_DEFAULT = {
    "gemini": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
    "huggingface": "meta-llama/Llama-3.3-70B-Instruct",
    "lmstudio": "local-model",
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


# --- Constructores por proveedor (importan perezoso para no exigir todas las libs) ---

def _build_gemini(temperature: float):
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", MODELOS_DEFAULT["gemini"]),
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=temperature,
    )


def _build_groq(temperature: float):
    from langchain_groq import ChatGroq
    return ChatGroq(
        model=os.getenv("GROQ_MODEL", MODELOS_DEFAULT["groq"]),
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=temperature,
    )


def _build_huggingface(temperature: float):
    from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
    endpoint = HuggingFaceEndpoint(
        repo_id=os.getenv("HUGGINGFACE_MODEL", MODELOS_DEFAULT["huggingface"]),
        huggingfacehub_api_token=os.getenv("HUGGINGFACEHUB_API_TOKEN"),
        task="text-generation",
        temperature=max(temperature, 0.01),  # HF no acepta 0 exacto
    )
    return ChatHuggingFace(llm=endpoint)


def _build_lmstudio(temperature: float):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.getenv("LMSTUDIO_MODEL", MODELOS_DEFAULT["lmstudio"]),
        base_url=os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
        api_key="lm-studio",  # LM Studio ignora la key
        temperature=temperature,
    )


_BUILDERS = {
    "gemini": _build_gemini,
    "groq": _build_groq,
    "huggingface": _build_huggingface,
    "lmstudio": _build_lmstudio,
}


def _disponible(proveedor: str) -> bool:
    """True si el proveedor tiene su config lista para usarse."""
    if proveedor == "gemini":
        return _seteada(os.getenv("GEMINI_API_KEY"))
    if proveedor == "groq":
        return _seteada(os.getenv("GROQ_API_KEY"))
    if proveedor == "huggingface":
        return _seteada(os.getenv("HUGGINGFACEHUB_API_TOKEN"))
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
    Devuelve un LLM (Runnable) con failover entre todos los proveedores
    configurados. Si se pasan `tools`, quedan ligadas a cada proveedor.

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
            "No hay ningún proveedor de LLM configurado. Cargá al menos una "
            "clave en .env (GEMINI_API_KEY, GROQ_API_KEY, HUGGINGFACEHUB_API_TOKEN) "
            "o levantá LM Studio en local."
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
