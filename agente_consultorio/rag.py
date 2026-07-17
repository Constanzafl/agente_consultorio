"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 3: RAG de guías clínicas (por audiencia)
=============================================================================
Dos "buscadores" separados según a quién van dirigidas las guías:

  data/guias_pdf/paciente/  -> guías de EDUCACIÓN AL PACIENTE (hábitos, manejo
                               básico). Las usa el AGENTE PACIENTE (tool consultar_guias).
  data/guias_pdf/medico/    -> guías clínicas PROFESIONALES (tratamiento, elección
                               de fármacos, algoritmos). Las usa el AGENTE MÉDICO
                               (tool consultar_guias_medico).

Cada carpeta se indexa en su propia colección de ChromaDB. La info de medicamentos
NO va por acá (eso es OpenFDA, tool buscar_medicamento).


=============================================================================
"""

import sys
import shutil
import pathlib

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from langchain.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Rutas ancladas a la raíz del repo (funciona corras desde donde corras)
RAIZ = pathlib.Path(__file__).resolve().parent.parent
DIR_GUIAS = RAIZ / "data" / "guias_pdf"
DIR_CHROMA = RAIZ / "chroma_db"

# Una carpeta y una colección por audiencia
DIRS = {
    "paciente": DIR_GUIAS / "paciente",
    "medico": DIR_GUIAS / "medico",
}
COLECCIONES = {
    "paciente": "guias_paciente",
    "medico": "guias_medico",
}

MODELO_EMBED = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Cache en memoria
_embeddings = None
_vectorstores = {}


def get_embeddings():
    """Carga (una sola vez) el modelo de embeddings."""
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=MODELO_EMBED)
    return _embeddings


def construir_indice(forzar: bool = False) -> dict:
    """
    Reconstruye el índice de AMBAS audiencias (paciente y médico).

    Args:
        forzar: si True, borra el índice previo y lo reconstruye de cero.
    Returns:
        dict {audiencia: cantidad_de_fragmentos}.
    """
    if forzar and DIR_CHROMA.exists():
        shutil.rmtree(DIR_CHROMA)

    conteos = {}
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    for audiencia, dir_pdfs in DIRS.items():
        pdfs = sorted(dir_pdfs.glob("*.pdf")) if dir_pdfs.exists() else []
        if not pdfs:
            conteos[audiencia] = 0
            continue
        documentos = PyPDFDirectoryLoader(str(dir_pdfs)).load()
        fragmentos = splitter.split_documents(documentos)
        Chroma.from_documents(
            fragmentos,
            embedding=get_embeddings(),
            collection_name=COLECCIONES[audiencia],
            persist_directory=str(DIR_CHROMA),
        )
        conteos[audiencia] = len(fragmentos)

    # Dejamos anotado con qué modelo se construyó (para detectar cambios de modelo)
    DIR_CHROMA.mkdir(parents=True, exist_ok=True)
    (DIR_CHROMA / ".modelo_embed").write_text(MODELO_EMBED, encoding="utf-8")
    return conteos


def get_vectorstore(audiencia: str):
    """Devuelve el vectorstore de esa audiencia. Si el índice no existe o se armó
    con OTRO modelo de embeddings, reconstruye todo primero."""
    if audiencia in _vectorstores:
        return _vectorstores[audiencia]

    marcador = DIR_CHROMA / ".modelo_embed"
    modelo_previo = marcador.read_text(encoding="utf-8").strip() if marcador.exists() else None
    if not (DIR_CHROMA.exists() and modelo_previo == MODELO_EMBED):
        construir_indice(forzar=True)

    _vectorstores[audiencia] = Chroma(
        collection_name=COLECCIONES[audiencia],
        embedding_function=get_embeddings(),
        persist_directory=str(DIR_CHROMA),
    )
    return _vectorstores[audiencia]


def _buscar(audiencia: str, consulta: str) -> str:
    """Busca en las guías de una audiencia y formatea los fragmentos con su fuente."""
    dir_pdfs = DIRS[audiencia]
    if not (dir_pdfs.exists() and any(dir_pdfs.glob("*.pdf"))):
        return (f"No hay guías de tipo '{audiencia}' cargadas todavía. "
                f"Poné PDFs en data/guias_pdf/{audiencia}/ y reconstruí (python agente_consultorio/rag.py).")

    # MMR (Maximal Marginal Relevance): en vez de traer los k más parecidos
    # (que suelen ser casi idénticos y del mismo PDF), busca fetch_k candidatos y
    # elige k que sean relevantes PERO diversos entre sí. Así no copa un solo PDF
    # y aparecen las guías específicas del tema (ej: la de HTA para "dieta y presión").
    vs = get_vectorstore(audiencia)
    try:
        docs = vs.max_marginal_relevance_search(consulta, k=4, fetch_k=15, lambda_mult=0.5)
    except Exception:
        docs = vs.similarity_search(consulta, k=4)  # fallback si el backend no soporta MMR
    if not docs:
        return "No encontré nada relevante en las guías para esa consulta."

    partes = []
    for d in docs:
        fuente = pathlib.Path(d.metadata.get("source", "guía")).name
        pagina = d.metadata.get("page")
        ref = fuente + (f", pág. {pagina + 1}" if isinstance(pagina, int) else "")
        partes.append(f"[{ref}]\n{d.page_content.strip()}")
    return "\n\n---\n\n".join(partes)


@tool
def consultar_guias(consulta: str) -> str:
    """
    Busca en las guías de EDUCACIÓN AL PACIENTE (hábitos saludables, alimentación,
    manejo básico de HTA y DM2). Para uso del agente PACIENTE, en lenguaje simple.
    NO usar para dosis de medicamentos (eso es buscar_medicamento).

    Args:
        consulta: la pregunta o tema a buscar.
    Returns:
        Fragmentos relevantes con su fuente (archivo y página).
    """
    return _buscar("paciente", consulta)


@tool
def consultar_guias_medico(consulta: str) -> str:
    """
    Busca en las guías clínicas PROFESIONALES para el médico (tratamiento, elección
    de fármacos, algoritmos, manejo de comorbilidades). Para uso del agente MÉDICO,
    en lenguaje técnico. Usar para decisiones clínicas basadas en guías.

    Args:
        consulta: la pregunta clínica a buscar.
    Returns:
        Fragmentos relevantes con su fuente (archivo y página).
    """
    return _buscar("medico", consulta)


if __name__ == "__main__":
    print(f"Guías paciente en: {DIRS['paciente']}")
    print(f"Guías médico en:   {DIRS['medico']}")
    conteos = construir_indice(forzar=True)
    print(f"\nFragmentos indexados: {conteos}")

    if conteos.get("paciente"):
        print("\n--- Prueba PACIENTE: 'cómo bajar la presión con hábitos' ---")
        print(consultar_guias.invoke({"consulta": "cómo bajar la presión arterial con hábitos"})[:400])
    if conteos.get("medico"):
        print("\n--- Prueba MÉDICO: 'antihipertensivo en insuficiencia renal' ---")
        print(consultar_guias_medico.invoke({"consulta": "antihipertensivo de elección en insuficiencia renal"})[:400])
