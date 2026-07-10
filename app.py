"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 7: UI con Chainlit
=============================================================================
Interfaz de chat web que envuelve el grafo multi-agente.

Cómo correr (con LM Studio prendido):
    chainlit run app.py
Se abre en el navegador (http://localhost:8000). Al entrar elegís el perfil:
Paciente, o uno de los médicos del centro (así el agente sabe qué médico sos).
=============================================================================
"""

import sys
import uuid
import pathlib

# Importar el paquete del proyecto
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "agente_consultorio"))

import chainlit as cl
from grafo import construir_grafo, chatear
from db import conn

# El grafo se arma una sola vez y se comparte (cada sesión usa su propio thread_id)
APP = None


def _medicos():
    """Lee los médicos activos de la base."""
    return conn.execute(
        "SELECT id, nombre, apellido, especialidad FROM medicos WHERE activo = 1 ORDER BY id"
    ).fetchall()


def _perfil_medico(m) -> str:
    """Nombre del perfil (chat profile) para un médico."""
    return f"Dr/a. {m['nombre']} {m['apellido']}"


@cl.set_chat_profiles
async def chat_profiles():
    """Perfiles: Paciente + uno por cada médico del centro (leídos de la base)."""
    perfiles = [
        cl.ChatProfile(
            name="Paciente",
            markdown_description="Soy un **paciente**: turnos, recetas, dudas de salud y hábitos.",
        )
    ]
    for m in _medicos():
        perfiles.append(cl.ChatProfile(
            name=_perfil_medico(m),
            markdown_description=f"Soy **{_perfil_medico(m)}** — {m['especialidad'] or 'Clínica'}.",
        ))
    return perfiles


@cl.on_chat_start
async def on_chat_start():
    global APP
    if APP is None:
        APP = construir_grafo()

    perfil = cl.user_session.get("chat_profile") or "Paciente"

    if perfil == "Paciente":
        rol, paciente_id, medico_id = "paciente", 1, None  # demo: paciente id=1
    else:
        rol, paciente_id, medico_id = "medico", None, None
        for m in _medicos():
            if perfil == _perfil_medico(m):
                medico_id = m["id"]
                break

    cl.user_session.set("rol", rol)
    cl.user_session.set("paciente_id", paciente_id)
    cl.user_session.set("medico_id", medico_id)
    cl.user_session.set("thread_id", str(uuid.uuid4()))

    saludo = (
        "Hola, soy el asistente del consultorio de medicina familiar. "
        f"Estás ingresando como **{perfil}**.\n\n¿En qué te puedo ayudar?"
    )
    await cl.Message(content=saludo).send()


@cl.on_message
async def on_message(message: cl.Message):
    respuesta = await cl.make_async(chatear)(
        APP, message.content,
        thread_id=cl.user_session.get("thread_id"),
        rol=cl.user_session.get("rol"),
        paciente_id=cl.user_session.get("paciente_id"),
        medico_id=cl.user_session.get("medico_id"),
    )
    await cl.Message(content=respuesta).send()
