# Agente Consultorio Médico — Contexto del Proyecto

## Qué es
Sistema multi-agente de IA para gestión de consultorio de medicina familiar.
Trabajo práctico final para el curso de Agentes de IA (Maestría en Ciencia de Datos, ITBA).
Objetivo doble: aprobar el TP con buena nota + tener proyecto portfolio + producto real a futuro.

## Arquitectura
- **Orquestador**: rutea entre agente paciente y agente médico según el rol del usuario
- **Agente paciente** (10 tools): turnos, registro, recetas, consultas, hábitos saludables
- **Agente médico** (12 tools): agenda, aprobar/rechazar solicitudes, vademecum, PubMed, seguimiento crónicos
- **Human-in-the-loop**: todo lo que genera el agente paciente (recetas, respuestas) queda pendiente para aprobación del médico

## Stack técnico (todo open source / gratis)
- LLM: Gemini (free tier) via `langchain-google-genai`
- Embeddings: HuggingFace `sentence-transformers/all-mpnet-base-v2`
- Vector store: ChromaDB
- Base de datos: SQLite (7 tablas: pacientes, agenda_medico, turnos, medicamentos, solicitudes, historial_conversaciones)
- Orquestación: LangGraph + LangChain
- UI: Chainlit (al final)
- API externa: PubMed E-utilities (gratis)

## Requisitos del TP que hay que cubrir
1. **RAG** — Guías clínicas PDF (HTA, DM2, hábitos). El vademecum NO va por RAG:
   queda como tool de SQLite (`consultar_vademecum`) porque es data estructurada
   (dosis exactas, contraindicaciones) donde RAG perdería precisión.
2. **Herramientas** — Las 22 tools en `db_y_tools.py`
3. **Guardarrailes** — No diagnosticar, escalar urgencias, validar datos, confirmar acciones
4. **Evaluación** — Pipeline con casos de prueba funcionales, RAG y guardarrailes
5. **Múltiples agentes** (plus) — Orquestador + 2 subagentes
6. **Human-in-the-loop** (plus) — Médico aprueba recetas, valida respuestas
7. **Memoria** — Corto plazo (state LangGraph), largo plazo (SQLite), conversacional (historial_conversaciones)

## Estado actual
- ✅ Fase 1: DB + 22 tools (todas testeadas y pasando)
- ✅ Fase 2: Grafo LangGraph multi-agente (orquestador híbrido + paciente + médico),
  memoria corto plazo (MemorySaver), y `llm.py` con failover multi-proveedor
  (Gemini→Groq→HF→LM Studio) + LangSmith. Falta probar con API key real.
- ⬜ Fase 3: RAG con guías clínicas
- ⬜ Fase 4: Guardarrailes
- ⬜ Fase 5: Tier 2 (Gmail recordatorios, sugerencias proactivas, PRODIABA PDF)
- ⬜ Fase 6: Evaluación
- ⬜ Fase 7: UI Chainlit + video

## Estructura del repo
```
agente_consultorio/
├── db_y_tools.py        # Fase 1 — DB schema + todas las tools
├── llm.py               # Fase 2 — Factory de LLM con failover multi-proveedor
├── grafo.py             # Fase 2 — LangGraph multi-agente
├── rag.py               # Fase 3 — RAG guías clínicas
├── guardarrailes.py     # Fase 4 — Guardarrailes
└── integraciones.py     # Fase 5 — Gmail, PRODIABA, etc.
tests/
└── test_evaluacion.py   # Fase 6 — Pipeline de evaluación
data/
└── guias_pdf/           # PDFs de guías clínicas para RAG
```

## Contexto médico
Pensado para un médico de familia que atiende pacientes con enfermedades crónicas:
HTA (hipertensión), DM2 (diabetes tipo 2), obesidad, dislipemia.
El vademecum incluye: Metformina, Enalapril, Losartán, Atorvastatina, Amlodipina, Glimepirida, Hidroclorotiazida, Insulina Glargina.

## Convenciones
- Todas las tools usan `@tool` de LangChain
- SQLite con `check_same_thread=False` para compatibilidad con LangGraph
- Búsqueda de medicamentos por nombre (LIKE) no por ID exacto
- Fechas en formato YYYY-MM-DD, horas en HH:MM
- Las tools devuelven strings de texto plano (sin emojis; rompen la consola cp1252 en Windows)
- En Windows, correr con `PYTHONUTF8=1` (los emojis rompen la consola cp1252)
- Entorno: venv con Python 3.12 en `.venv/` (torch/sentence-transformers no tiene
  wheels para 3.14). Deps core en `requirements.txt`, RAG en `requirements-rag.txt`
