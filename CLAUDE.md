# Agente Consultorio Médico — Contexto del Proyecto

## Qué es
Sistema multi-agente de IA para gestión de consultorio de medicina familiar.
Trabajo práctico final para el curso de Agentes de IA (Maestría en Ciencia de Datos, ITBA).
Objetivo doble: aprobar el TP con buena nota + tener proyecto portfolio + producto real a futuro.

## Arquitectura
- **Orquestador**: rutea entre agente paciente y agente médico según el rol del usuario
- **Agente paciente** (10 tools): turnos, registro, recetas, consultas, hábitos saludables
- **Agente médico**: agenda, aprobar/rechazar solicitudes, medicamentos (OpenFDA), PubMed, seguimiento crónicos
- **Human-in-the-loop**: todo lo que genera el agente paciente (recetas, respuestas) queda pendiente para aprobación del médico

## Decisión de arquitectura (importante)
El curso enseñó LangGraph "a mano" (Clase 1), RAG (Clase 2) y Deep Agents (Clase 3).
Para un asistente MÉDICO (seguridad crítica) prima el CONTROL, no la autonomía.
Por eso:
- **Backbone = LangGraph** (control total sobre ruteo, guardarrailes y HITL).
- **Skills** (requisito del profe) → carpeta `skills/` con playbooks modulares que
  el agente carga on-demand, implementados sobre LangGraph (no se migra a deepagents).
- **Memoria largo plazo** → SQLite (`historial_conversaciones`); opcional sumar el
  patrón `Store` de LangGraph para que se vea canónico.
- **Subagente estilo Deep Agents SOLO para PubMed** (búsqueda de evidencia): es la
  única tarea abierta/investigación donde la autonomía aporta. Ahí se luce deepagents.
- No se usa deepagents como framework general porque (a) resta control en un dominio
  médico y (b) pediría un modelo grande (la gemma-4-e4b local no lo aguanta → cuota).

## Stack técnico (todo open source / gratis)
- LLM PRIMARIO: LM Studio local (gemma-4-e4b), ilimitado. Fallback cloud opcional
  (Gemini free tier → Groq → HuggingFace) vía `llm.py`. Ver failover multi-proveedor.
- Embeddings: HuggingFace `sentence-transformers/all-mpnet-base-v2`
- Vector store: ChromaDB
- Base de datos: SQLite (6 tablas: pacientes, agenda_medico, turnos, solicitudes, historial_conversaciones)
- Info de medicamentos: OpenFDA (API FDA, gratis) — NO se guarda en la DB (sin vademecum que mantener)
- Orquestación: LangGraph + LangChain
- UI: Chainlit (al final)
- API externa: PubMed E-utilities (gratis)

## Requisitos del TP que hay que cubrir
1. **RAG** — Guías clínicas PDF (HTA, DM2, hábitos). La info de medicamentos NO va
   por RAG ni por DB local: se consulta en vivo con la tool `buscar_medicamento`
   (OpenFDA), así no hay vademecum que mantener a mano.
2. **Herramientas** — Las tools en `tools.py` (incluye APIs externas: PubMed + OpenFDA)
3. **Guardarrailes** — No diagnosticar, escalar urgencias, validar datos, confirmar acciones
4. **Evaluación** — Pipeline con casos de prueba funcionales, RAG y guardarrailes
5. **Múltiples agentes** (plus) — Orquestador + 2 subagentes
6. **Human-in-the-loop** (plus) — Médico aprueba recetas, valida respuestas
7. **Memoria** — Corto plazo (state LangGraph), largo plazo (SQLite), conversacional (historial_conversaciones)
8. **Skills** (pide el profe) — playbooks modulares en `skills/` cargados on-demand

## Estado actual
- ✅ Fase 1: DB + 22 tools (todas testeadas y pasando)
- ✅ Fase 2: Grafo LangGraph multi-agente (orquestador híbrido + paciente + médico),
  memoria corto plazo (MemorySaver), y `llm.py` con failover multi-proveedor.
  LLM PRIMARIO: LM Studio local (gemma-4-e4b), ilimitado. Cloud (Gemini→Groq→HF)
  como fallback opcional. LangSmith para tracing.
- ✅ Fase 3: RAG con guías clínicas por AUDIENCIA (`rag.py`). Dos carpetas y dos
  colecciones: `data/guias_pdf/paciente/` (educación → tool `consultar_guias`, agente
  paciente) y `data/guias_pdf/medico/` (clínicas profesionales → tool
  `consultar_guias_medico`, agente médico). Embeddings HF multilingüe → ChromaDB.
  Reindexar: `python agente_consultorio/rag.py`
- ✅ Fase 4: Guardarrailes (`guardarrailes.py`). Detector de URGENCIAS por palabras
  clave, integrado como primer nodo del grafo (`guardarrail`): si detecta urgencia,
  escala (911/guardia) y corta el flujo sin llamar a los agentes. Resto de
  guardarrailes (no diagnosticar, confirmar, validar) en prompts y tools.
- 🟡 Fase 5 (en curso):
  - ✅ Skills: carpeta `skills/*.md` (playbooks) + `skills_loader.py` (tool
    `cargar_skill` + lista inyectada en prompts). Progressive disclosure sobre LangGraph.
  - ⬜ Subagente PubMed estilo Deep Agents (búsqueda de evidencia)
  - ⬜ Tier 2 (Gmail recordatorios, sugerencias proactivas, PRODIABA PDF)
- ✅ Fase 6: Evaluación (`tests/test_evaluacion.py`). 3 bloques: funcionales (tools),
  guardarrailes (urgencias) — deterministas — y LLM-as-judge (estilo Clase 2) que
  evalúa respuestas del agente. Correr: `python tests/test_evaluacion.py`
- 🟡 Fase 7: UI Chainlit (`app.py`) lista — chat web con perfiles Paciente/Médico
  que envuelve el grafo. Correr: `chainlit run app.py`. Falta: grabar el video.

## Estructura del repo
```
agente_consultorio/
├── db.py                # Fase 1 — DB schema + datos + conexión `conn`
├── tools.py             # Fase 1 — las 22 tools (@tool), usan `conn` de db.py
├── llm.py               # Fase 2 — Factory de LLM con failover multi-proveedor
├── grafo.py             # Fase 2 — LangGraph multi-agente
├── rag.py               # Fase 3 — RAG guías clínicas
├── guardarrailes.py     # Fase 4 — Guardarrailes
├── skills_loader.py     # Fase 5 — carga de skills on-demand
└── integraciones.py     # Fase 5 — Gmail, PRODIABA, subagente PubMed
skills/                  # Fase 5 — playbooks modulares (.md) que el agente carga
tests/
└── test_evaluacion.py   # Fase 6 — Pipeline de evaluación
data/
└── guias_pdf/           # PDFs de guías clínicas para RAG
```

## Contexto médico
Pensado para un médico de familia que atiende pacientes con enfermedades crónicas:
HTA (hipertensión), DM2 (diabetes tipo 2), obesidad, dislipemia.
Drogas típicas: Metformina, Enalapril, Losartán, Atorvastatina, Amlodipina, Glimepirida,
Hidroclorotiazida, Insulina Glargina. La info se consulta en OpenFDA (`buscar_medicamento`, nombre en inglés).

## Convenciones
- Todas las tools usan `@tool` de LangChain
- SQLite con `check_same_thread=False` para compatibilidad con LangGraph
- Info de medicamentos vía OpenFDA (`buscar_medicamento`), con el nombre de la droga en inglés
- Fechas en formato YYYY-MM-DD, horas en HH:MM
- Las tools devuelven strings de texto plano (sin emojis; rompen la consola cp1252 en Windows)
- En Windows, correr con `PYTHONUTF8=1` (los emojis rompen la consola cp1252)
- Entorno: venv con Python 3.12 en `.venv/` (torch/sentence-transformers no tiene
  wheels para 3.14). Todas las deps en un solo `requirements.txt`
