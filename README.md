# Agente Consultorio Médico

Sistema multi-agente de IA para gestión de consultorio de medicina familiar, desarrollado como trabajo práctico para el curso de Agentes de IA (ITBA).

## Descripción

El sistema conecta dos agentes especializados a través de un orquestador central:

- **Agente Paciente**: gestión de turnos, solicitud de recetas, consultas sobre hábitos saludables (RAG), ingreso de pacientes nuevos
- **Agente Médico**: agenda diaria con info del paciente, aprobación/rechazo de solicitudes (human-in-the-loop), consulta de vademecum, seguimiento de pacientes crónicos

Pensado para un médico de familia que atiende pacientes con enfermedades crónicas (HTA, DM2, obesidad, dislipemia).

## Tecnologías

| Componente | Tecnología |
|---|---|
| LLM | LM studio Gemma |
| Framework de agentes | LangGraph + LangChain |
| Embeddings | HuggingFace (`sentence-transformers/all-mpnet-base-v2`) |
| Vector store | ChromaDB |
| Base de datos | SQLite |
| UI | Chainlit (planned) |

Todo open source y gratuito.

## Estructura del proyecto

```
agente-consultorio/
├── agente_consultorio/
│   ├── __init__.py
│   ├── db_y_tools.py        # Fase 1: DB + tools
│   ├── grafo.py              # Fase 2: LangGraph multi-agente
│   ├── rag.py                # Fase 3: RAG guías clínicas + vademecum
│   ├── guardarrailes.py      # Fase 4: Guardarrailes
│   └── integraciones.py      # Fase 5: Gmail, PRODIABA, etc.
├── tests/
│   ├── __init__.py
│   └── test_evaluacion.py    # Fase 6: Pipeline de evaluación
├── data/
│   └── guias_pdf/            # PDFs de guías clínicas para RAG
├── docs/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup

```bash
git clone https://github.com/tu-usuario/agente-consultorio.git
cd agente-consultorio
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
cp .env.example .env
# Editar .env con tu GEMINI_API_KEY
```

## Requisitos del TP cubiertos

- [x] **RAG** — Guías clínicas (HTA, DM2, hábitos saludables) + vademecum
- [x] **Herramientas** — Tools de gestión de turnos, recetas, agenda, vademecum
- [x] **Guardarrailes** — No diagnosticar, escalar urgencias, validar datos, confirmar acciones
- [x] **Evaluación** — Pipeline con casos de prueba funcionales, RAG y guardarrailes
- [x] **Múltiples agentes** (plus) — Orquestador + agente paciente + agente médico
- [x] **Human-in-the-loop** (plus) — Médico aprueba recetas, valida respuestas, firma formularios

## Autor

María Constanza Florio — Maestría en Ciencia de Datos
