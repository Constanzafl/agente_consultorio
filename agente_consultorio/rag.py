"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 3: RAG de guías clínicas
=============================================================================
Da al agente un "buscador" dentro de los PDF de guías clínicas (HTA, DM2,
hábitos saludables). Flujo clásico de RAG:

  1. Leer los PDF de data/guias_pdf/
  2. Partirlos en fragmentos (chunks) con solapamiento
  3. Vectorizarlos (embeddings HuggingFace) y guardarlos en ChromaDB (persistido)
  4. Ante una consulta, buscar los fragmentos más parecidos y devolverlos

El vademecum NO va por acá: es data estructurada (tool consultar_vademecum).
Esto es SOLO para texto no estructurado (guías).

IMPORTANTE: la primera vez descarga el modelo de embeddings (~438 MB).
Uso:
  1) Poné los PDF en data/guias_pdf/
  2) Reconstruí el índice:  python agente_consultorio/rag.py
  3) El agente usa la tool `consultar_guias`
=============================================================================
"""

import shutil
import pathlib
from langchain.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Rutas ancladas a la raíz del repo (funciona corras desde donde corras)
RAIZ = pathlib.Path(__file__).resolve().parent.parent
DIR_GUIAS = RAIZ / "data" / "guias_pdf"
DIR_CHROMA = RAIZ / "chroma_db"

MODELO_EMBED = "sentence-transformers/all-mpnet-base-v2"  # mismo que usó la clase
COLECCION = "guias_clinicas"

# Cache en memoria para no recargar el modelo ni la base en cada llamada
_embeddings = None
_vectorstore = None


def get_embeddings():
    """Carga (una sola vez) el modelo de embeddings."""
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=MODELO_EMBED)
    return _embeddings


def construir_indice(forzar: bool = False):
    """
    Lee los PDF de data/guias_pdf/, los parte en chunks y arma el índice Chroma.

    Args:
        forzar: si True, borra el índice previo y lo reconstruye de cero
                (evita fragmentos duplicados al reindexar).
    Returns:
        (vectorstore, cantidad_de_fragmentos) o (None, 0) si no hay PDFs.
    """
    pdfs = sorted(DIR_GUIAS.glob("*.pdf"))
    if not pdfs:
        return None, 0

    if forzar and DIR_CHROMA.exists():
        shutil.rmtree(DIR_CHROMA)

    # 1+2) cargar PDFs y partir en fragmentos
    loader = PyPDFDirectoryLoader(str(DIR_GUIAS))
    documentos = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    fragmentos = splitter.split_documents(documentos)

    # 3) vectorizar y persistir
    vs = Chroma.from_documents(
        fragmentos,
        embedding=get_embeddings(),
        collection_name=COLECCION,
        persist_directory=str(DIR_CHROMA),
    )
    return vs, len(fragmentos)


def get_vectorstore():
    """Devuelve el vectorstore: lo carga de disco si existe, o lo construye."""
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore

    if DIR_CHROMA.exists() and any(DIR_CHROMA.iterdir()):
        _vectorstore = Chroma(
            collection_name=COLECCION,
            embedding_function=get_embeddings(),
            persist_directory=str(DIR_CHROMA),
        )
    else:
        _vectorstore, _ = construir_indice()
    return _vectorstore


@tool
def consultar_guias(consulta: str) -> str:
    """
    Busca en las guías clínicas (HTA, DM2, hábitos saludables) información para
    responder dudas sobre manejo de enfermedades crónicas, prevención y hábitos.
    Usar para consultas de salud generales basadas en guías. NO usar para dosis
    exactas de medicamentos (para eso está consultar_vademecum).

    Args:
        consulta: la pregunta o tema a buscar en las guías.
    Returns:
        Fragmentos relevantes de las guías, con su fuente (archivo y página).
    """
    vs = get_vectorstore()
    if vs is None:
        return ("No hay guías clínicas cargadas todavía. Poné los PDF en "
                "data/guias_pdf/ y reconstruí el índice (python rag.py).")

    docs = vs.similarity_search(consulta, k=3)
    if not docs:
        return "No encontré nada relevante en las guías clínicas para esa consulta."

    partes = []
    for d in docs:
        fuente = pathlib.Path(d.metadata.get("source", "guía")).name
        pagina = d.metadata.get("page")
        ref = fuente + (f", pág. {pagina + 1}" if isinstance(pagina, int) else "")
        partes.append(f"[{ref}]\n{d.page_content.strip()}")
    return "\n\n---\n\n".join(partes)


if __name__ == "__main__":
    print(f"Buscando PDFs en: {DIR_GUIAS}")
    vs, n = construir_indice(forzar=True)
    if vs is None:
        print("\nNo hay PDFs en data/guias_pdf/.")
        print("Poné al menos un PDF de guía clínica en esa carpeta y volvé a correr esto.")
    else:
        print(f"Índice creado con {n} fragmentos.")
        print("\n--- Prueba de consulta ---")
        print(consultar_guias.invoke(
            {"consulta": "cómo bajar la presión arterial con cambios en el estilo de vida"}
        ))
