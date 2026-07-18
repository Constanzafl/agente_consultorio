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

AUTO TEST
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


def enviar_email(destinatario: str, asunto: str, cuerpo: str, adjunto: str = "") -> str:
    """Envía un email vía Gmail. Devuelve un mensaje de estado (no lanza excepción).
    Si `adjunto` es la ruta a un archivo (ej. el PDF de la receta), lo adjunta."""
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

    if adjunto:
        try:
            import os as _os
            with open(adjunto, "rb") as f:
                datos = f.read()
            msg.add_attachment(datos, maintype="application", subtype="pdf",
                               filename=_os.path.basename(adjunto))
        except Exception as e:
            # Si falla el adjunto, mandamos igual el mail (sin el PDF).
            print(f"[email] No se pudo adjuntar {adjunto}: {e}")

    try:
        contexto = ssl.create_default_context()
        # timeout=15: si el servidor no responde, corta (no cuelga el agente).
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=contexto, timeout=15) as servidor:
            servidor.login(remitente, password)
            servidor.send_message(msg)
        return f"Email enviado a {destinatario}."
    except Exception as e:
        return f"Error al enviar el email: {e}"


def avisar_paciente(paciente_id: int, asunto: str, mensaje: str, adjunto: str = "") -> str:
    """Envía un email al paciente (a la casilla de su ficha). Función plana, reutilizable
    tanto por la tool como por las acciones automáticas (sacar/cancelar turno, aprobar receta).
    Si `adjunto` es una ruta a un archivo (ej. el PDF de la receta), lo adjunta.
    Devuelve un estado; nunca lanza excepción."""
    cursor = conn.cursor()
    cursor.execute("SELECT nombre, apellido, email FROM pacientes WHERE id = ? AND activo = 1", (paciente_id,))
    p = cursor.fetchone()
    if not p:
        return f"No se encontró un paciente activo con ID #{paciente_id}."
    if not p["email"]:
        return f"El paciente {p['nombre']} {p['apellido']} no tiene email registrado."
    cuerpo = f"Hola {p['nombre']},\n\n{mensaje}\n\n— Consultorio de Medicina Familiar"
    return enviar_email(p["email"], asunto, cuerpo, adjunto)


def avisar_consultorio(asunto: str, mensaje: str) -> str:
    """Envía un email a la casilla del CONSULTORIO (GMAIL_USER), que actúa como
    bandeja de avisos internos: entra una consulta o receta nueva y el consultorio
    se entera sin tener que abrir el chat. Función plana; nunca lanza excepción."""
    consultorio = os.getenv("GMAIL_USER", "").strip()
    if not consultorio:
        return "Email del consultorio no configurado (falta GMAIL_USER en .env)."
    cuerpo = f"{mensaje}\n\n— Aviso automático del sistema del consultorio"
    return enviar_email(consultorio, asunto, cuerpo)


@tool
def notificar_paciente(paciente_id: int, asunto: str, mensaje: str) -> str:
    """
    Envía un email al paciente, a la casilla que tiene registrada en su ficha.
    Útil para avisos manuales. Confirmá el contenido antes de enviarlo.

    Args:
        paciente_id: ID del paciente a notificar
        asunto: asunto del email
        mensaje: cuerpo del mensaje (texto claro y breve)
    Returns:
        Estado del envío.
    """
    return avisar_paciente(paciente_id, asunto, mensaje)


if __name__ == "__main__":
    # Prueba: se envía un mail a tu propia casilla (GMAIL_USER)
    destino = os.getenv("GMAIL_USER", "")
    print(enviar_email(destino, "Prueba del consultorio",
                       "Si ves este mail, las notificaciones por email funcionan."))
