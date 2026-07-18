"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Generación del PDF de la receta (DEMOSTRACIÓN)
=============================================================================
Cuando el médico APRUEBA una solicitud de receta, se arma un PDF con el layout
de una receta electrónica (paciente, médico, matrícula, Rp/, firma y sello).

IMPORTANTE: es un DOCUMENTO DE DEMOSTRACIÓN, sin validez legal. Todos los datos
del médico (nombre, matrícula) son FICTICIOS, como los médicos de ejemplo.
En un producto real, en este punto se emitiría la receta a través de una
plataforma autorizada (ej. RCTA / API QBI2), que aporta la firma electrónica
válida y el registro oficial.
=============================================================================
"""

import pathlib
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

try:
    from .db import conn
except ImportError:
    from db import conn

# Los PDFs generados van a la raíz del repo, en recetas_generadas/
RAIZ = pathlib.Path(__file__).resolve().parent.parent
DIR_RECETAS = RAIZ / "recetas_generadas"


def _matricula_ficticia(medico_id: int) -> str:
    """Matrícula INVENTADA y estable por médico (no es real). Solo para la demo."""
    return f"MN {100000 + int(medico_id) * 111}"


def _fmt_fecha(valor: str) -> str:
    """Pasa 'YYYY-MM-DD HH:MM:SS' (o similar) a 'dd/mm/YYYY'. Tolera vacío."""
    if not valor:
        return datetime.now().strftime("%d/%m/%Y")
    try:
        return datetime.strptime(valor.split(" ")[0], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return valor


def generar_receta_pdf(solicitud_id: int, diagnostico: str = "") -> str | None:
    """
    Genera el PDF de la receta aprobada y lo guarda en recetas_generadas/.
    Devuelve la ruta del archivo, o None si la solicitud no existe o no es receta.

    Args:
        solicitud_id: ID de la solicitud de receta.
        diagnostico: diagnóstico indicado por el médico. Si viene vacío, se usan
                     las patologías de la ficha del paciente como referencia.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.tipo, s.medicamento, s.dosis, s.cantidad, s.respuesta_medico,
               s.fecha_resolucion,
               p.nombre AS p_nombre, p.apellido AS p_apellido, p.dni,
               p.obra_social, p.plan, p.numero_afiliado, p.fecha_nacimiento,
               p.patologias,
               m.id AS med_id, m.nombre AS m_nombre, m.apellido AS m_apellido,
               m.especialidad
        FROM solicitudes s
        JOIN pacientes p ON s.paciente_id = p.id
        LEFT JOIN medicos m ON s.medico_id = m.id
        WHERE s.id = ?
    """, (solicitud_id,))
    r = cursor.fetchone()
    if not r or r["tipo"] != "receta":
        return None

    diag = (diagnostico or r["patologias"] or "No especificado").strip()

    DIR_RECETAS.mkdir(parents=True, exist_ok=True)
    ruta = DIR_RECETAS / f"receta_{solicitud_id}.pdf"

    c = canvas.Canvas(str(ruta), pagesize=A4)
    ancho, alto = A4
    izq, der = 20 * mm, ancho - 20 * mm
    y = alto - 22 * mm

    medico = f"Dr/a. {r['m_nombre']} {r['m_apellido']}" if r["m_nombre"] else "Dr/a. (sin asignar)"
    matricula = _matricula_ficticia(r["med_id"]) if r["med_id"] else "MN 000000"
    fecha = _fmt_fecha(r["fecha_resolucion"])

    # --- Encabezado ---
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(ancho / 2, y, "RECETA ELECTRÓNICA")
    y -= 6 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.setFillGray(0.4)
    c.drawCentredString(ancho / 2, y, "DOCUMENTO DE DEMOSTRACIÓN — SIN VALIDEZ LEGAL")
    c.setFillGray(0)

    c.setFont("Helvetica", 8)
    c.drawRightString(der, alto - 22 * mm, f"Folio: RD-DEMO-{solicitud_id:06d}")

    # --- Datos del médico ---
    y -= 12 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(izq, y, medico)
    c.setFont("Helvetica", 9)
    c.drawRightString(der, y, f"Fecha: {fecha}")
    y -= 5 * mm
    c.drawString(izq, y, f"{r['especialidad'] or 'Medicina Familiar'}   |   Matrícula: {matricula}")

    # --- Línea divisoria ---
    y -= 5 * mm
    c.setLineWidth(0.6)
    c.line(izq, y, der, y)

    # --- Datos del paciente ---
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(izq, y, f"Paciente: {r['p_nombre']} {r['p_apellido']}")
    c.setFont("Helvetica", 9)
    y -= 5 * mm
    c.drawString(izq, y, f"DNI: {r['dni'] or '-'}")
    if r["fecha_nacimiento"]:
        c.drawRightString(der, y, f"F. Nacimiento: {_fmt_fecha(r['fecha_nacimiento'])}")
    y -= 5 * mm
    os_txt = r["obra_social"] or "-"
    if r["plan"]:
        os_txt += f"  |  Plan: {r['plan']}"
    if r["numero_afiliado"]:
        os_txt += f"  |  N° Afiliado: {r['numero_afiliado']}"
    c.drawString(izq, y, os_txt)

    y -= 5 * mm
    c.line(izq, y, der, y)

    # --- Rp/ (la prescripción) ---
    y -= 11 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawString(izq, y, "Rp/")
    y -= 8 * mm
    c.setFont("Helvetica", 11)
    c.drawString(izq + 6 * mm, y, r["medicamento"] or "-")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    c.drawString(izq + 6 * mm, y, f"Cantidad: {r['cantidad'] or '-'}")
    y -= 5 * mm
    c.drawString(izq + 6 * mm, y, f"Indicación: {r['dosis'] or '-'}")
    # Diagnóstico (lo indica el médico; si no, se usa la patología de la ficha).
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(izq + 6 * mm, y, "Diagnóstico:")
    c.setFont("Helvetica", 10)
    c.drawString(izq + 30 * mm, y, diag)
    if r["respuesta_medico"]:
        y -= 6 * mm
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(izq + 6 * mm, y, f"Nota del médico: {r['respuesta_medico']}")

    # --- Firma y sello (abajo a la derecha) ---
    y_firma = 45 * mm
    c.setLineWidth(0.6)
    c.line(der - 65 * mm, y_firma, der, y_firma)
    c.setFont("Helvetica", 9)
    c.drawRightString(der, y_firma - 5 * mm, medico)
    c.drawRightString(der, y_firma - 10 * mm, matricula)
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(der, y_firma - 15 * mm, "FIRMA Y SELLO")

    # --- Pie de página / disclaimer ---
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillGray(0.4)
    c.drawString(izq, 22 * mm,
                 "Documento generado con fines de demostración académica. Sin validez legal.")
    c.drawString(izq, 18 * mm,
                 "En un entorno real, la receta se emitiría a través de una plataforma autorizada")
    c.drawString(izq, 14 * mm,
                 "(ej. RCTA / API QBI2), que aporta la firma electrónica válida y el registro oficial.")
    c.setFillGray(0)

    c.showPage()
    c.save()
    return str(ruta)


if __name__ == "__main__":
    # Prueba rápida: genera el PDF de la solicitud de receta de ejemplo (#1).
    ruta = generar_receta_pdf(1)
    print(f"PDF generado en: {ruta}" if ruta else "La solicitud #1 no es una receta (o no existe).")
