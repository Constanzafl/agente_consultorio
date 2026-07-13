"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 5: Integraciones externas (email)
=============================================================================
Notificaciones por email (acción "hacia afuera" del sistema): recordatorios,
avisos de cancelación, receta aprobada/rechazada, etc.

Se envía desde una casilla Gmail que actúa como "el consultorio", usando una
CONTRASEÑA DE APLICACIÓN (no la clave real). Configurar en .env:
    GMAIL_USER=tu_casilla@gmail.com
    GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   (16 caracteres de Google)

Los mails LLEGAN a la casilla del destinatario (ej: el email del paciente
guardado en su ficha). No usa ninguna "línea"/teléfono, solo la casilla.
=============================================================================
"""

import os
import ssl
import smtplib
from email.message import EmailMessage

from langchain.tools import tool
from dotenv import load_dotenv

try:
    from .db import conn
except ImportError:
    from db import conn

load_dotenv()


def enviar_email(destinatario: str, asunto: str, cuerpo: str) -> str:
    """Envía un email vía Gmail. Devuelve un mensaje de estado (no lanza excepción)."""
    remitente = os.getenv("GMAIL_USER", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not remitente or not password:
        return ("Email NO configurado: falta GMAIL_USER / GMAIL_APP_PASSWORD en .env "
                "(generá una contraseña de aplicación de Gmail).")
    if not destinatario:
        return "No hay dirección de email de destino."

    msg = EmailMessage()
    msg["From"] = remitente
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg.set_content(cuerpo)

    try:
        contexto = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=contexto) as servidor:
            servidor.login(remitente, password)
            servidor.send_message(msg)
        return f"Email enviado a {destinatario}."
    except Exception as e:
        return f"Error al enviar el email: {e}"


@tool
def notificar_paciente(paciente_id: int, asunto: str, mensaje: str) -> str:
    """
    Envía un email al paciente, a la casilla que tiene registrada en su ficha.
    Útil para avisos: recordatorio de turno, cancelación, receta aprobada/rechazada.
    Confirmá el contenido con quien lo pide ANTES de enviarlo.

    Args:
        paciente_id: ID del paciente a notificar
        asunto: asunto del email
        mensaje: cuerpo del mensaje (texto claro y breve)
    Returns:
        Estado del envío.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT nombre, apellido, email FROM pacientes WHERE id = ? AND activo = 1", (paciente_id,))
    p = cursor.fetchone()
    if not p:
        return f"No se encontró un paciente activo con ID #{paciente_id}."
    if not p["email"]:
        return f"El paciente {p['nombre']} {p['apellido']} no tiene email registrado."

    cuerpo = f"Hola {p['nombre']},\n\n{mensaje}\n\n— Consultorio de Medicina Familiar"
    return enviar_email(p["email"], asunto, cuerpo)


if __name__ == "__main__":
    # Prueba: se envía un mail a tu propia casilla (GMAIL_USER)
    destino = os.getenv("GMAIL_USER", "")
    print(enviar_email(destino, "Prueba del consultorio",
                       "Si ves este mail, las notificaciones por email funcionan."))
