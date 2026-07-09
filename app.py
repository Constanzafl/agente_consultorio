"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 7: UI con Chainlit
=============================================================================
Interfaz de chat web que envuelve el grafo multi-agente.

Cómo correr (con LM Studio prendido):
    chainlit run app.py
Se abre en el navegador (http://localhost:8000). Al entrar, elegís el perfil
(Paciente o Médico) y chateás.
=============================================================================
"""

import sys
import uuid
import pathlib

# Importar el paquete del proyecto
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "agente_consultorio"))

import chainlit as cl
from grafo import construir_grafo, chatear

# El grafo se arma una sola vez y se comparte (cada sesión usa su propio thread_id)
APP = None


@cl.set_chat_profiles
async def chat_profiles():
    """Perfiles para elegir el rol al iniciar el chat."""
    return [
        cl.ChatProfile(
            name="Paciente",
            markdown_description="Soy un **paciente**: turnos, recetas, dudas de salud y hábitos.",
        ),
        cl.ChatProfile(
            name="Médico",
            markdown_description="Soy el **médico**: agenda, aprobar recetas, vademecum, evidencia (PubMed).",
        ),
    ]


@cl.on_chat_start
async def on_chat_start():
    global APP
    if APP is None:
        APP = construir_grafo()

    perfil = cl.user_session.get("chat_profile") or "Paciente"
    rol = "medico" if str(perfil).lower().startswith("m") else "paciente"

    cl.user_session.set("rol", rol)
    cl.user_session.set("thread_id", str(uuid.uuid4()))
    # Demo: si es paciente, usamos a María González (id=1). En real, se identificaría.
    cl.user_session.set("paciente_id", 1 if rol == "paciente" else None)

    saludo = (
        "Hola, soy el asistente del consultorio de medicina familiar. "
        f"Estás ingresando como **{perfil}**.\n\n"
        "¿En qué te puedo ayudar?"
    )
    await cl.Message(content=saludo).send()


@cl.on_message
async def on_message(message: cl.Message):
    rol = cl.user_session.get("rol")
    thread_id = cl.user_session.get("thread_id")
    paciente_id = cl.user_session.get("paciente_id")

    # chatear() es sincrónico; lo corremos sin bloquear la UI
    respuesta = await cl.make_async(chatear)(
        APP, message.content, thread_id=thread_id, rol=rol, paciente_id=paciente_id
    )
    await cl.Message(content=respuesta).send()
