"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 1: Base de datos y herramientas
=============================================================================
Este módulo contiene:
  1. Esquema SQLite (pacientes, agenda, turnos, medicamentos, recetas, solicitudes)
  2. Datos de ejemplo para testing
  3. Todas las tools decoradas con @tool para LangChain/LangGraph
  4. Separación clara: tools del PACIENTE vs tools del MÉDICO

Para usar en Google Colab:
  - Copiar este archivo en una celda o subirlo
  - Instalar dependencias: pip install langchain langchain-core langgraph langchain-google-genai
  - Configurar GEMINI_API_KEY en secrets de Colab
=============================================================================
"""

import sqlite3
import requests
from datetime import datetime, timedelta
from langchain.tools import tool

# =============================================================================
# 1. BASE DE DATOS — Esquema
# =============================================================================

def crear_base_de_datos(db_path: str = "consultorio.db") -> sqlite3.Connection:
    """
    Crea la base de datos SQLite con todas las tablas necesarias.
    Retorna la conexión (con check_same_thread=False para LangGraph).
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Para acceder a columnas por nombre
    cursor = conn.cursor()

    # --- PACIENTES ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            apellido TEXT NOT NULL,
            dni TEXT UNIQUE NOT NULL,
            fecha_nacimiento TEXT,
            telefono TEXT,
            email TEXT,
            obra_social TEXT,
            numero_afiliado TEXT,
            patologias TEXT,          -- Ej: "HTA,DM2,Obesidad" (separadas por coma)
            medicacion_actual TEXT,   -- Ej: "Metformina 850mg c/12hs, Enalapril 10mg c/24hs"
            fecha_ultima_consulta TEXT,
            activo INTEGER DEFAULT 1,
            fecha_registro TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # --- AGENDA DEL MÉDICO (horarios disponibles por día de semana) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agenda_medico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dia_semana INTEGER NOT NULL,   -- 0=Lunes, 1=Martes, ..., 4=Viernes
            hora_inicio TEXT NOT NULL,      -- Ej: "09:00"
            hora_fin TEXT NOT NULL,         -- Ej: "09:30" (turnos de 30 min)
            activo INTEGER DEFAULT 1
        )
    """)

    # --- TURNOS ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS turnos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,            -- "2025-07-15"
            hora TEXT NOT NULL,             -- "09:00"
            motivo TEXT,                    -- "Control DM2", "Seguimiento HTA", "Primera consulta"
            tipo TEXT DEFAULT 'seguimiento', -- "primera_vez", "seguimiento", "urgencia"
            estado TEXT DEFAULT 'confirmado', -- "confirmado", "cancelado", "completado"
            recordatorio_enviado INTEGER DEFAULT 0,
            notas TEXT,
            fecha_creacion TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id)
        )
    """)

    # --- MEDICAMENTOS (vademecum simplificado) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medicamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_generico TEXT NOT NULL,
            nombre_comercial TEXT,
            presentacion TEXT,             -- "Comprimidos 850mg", "Comprimidos 10mg"
            dosis_habitual TEXT,           -- "850mg cada 12 horas"
            dosis_maxima TEXT,             -- "2550mg/día"
            contraindicaciones TEXT,
            efectos_adversos TEXT,
            categoria TEXT                 -- "antidiabético", "antihipertensivo", "hipolipemiante"
        )
    """)

    # --- RECETAS / SOLICITUDES ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solicitudes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,            -- "receta", "formulario_prodiaba", "consulta_medica", "respuesta_borrador"
            estado TEXT DEFAULT 'pendiente', -- "pendiente", "aprobada", "rechazada", "completada"
            descripcion TEXT,              -- Detalle de lo que se solicita
            medicamento TEXT,              -- Para recetas: nombre del medicamento
            dosis TEXT,                    -- Para recetas: dosis solicitada
            cantidad TEXT,                 -- Para recetas: cantidad de envases
            respuesta_borrador TEXT,       -- Para consultas: respuesta generada por el agente
            respuesta_medico TEXT,         -- Respuesta/nota del médico
            fecha_creacion TEXT DEFAULT (datetime('now', 'localtime')),
            fecha_resolucion TEXT,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id)
        )
    """)

    # --- HISTORIAL DE CONVERSACIONES (memoria de largo plazo) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historial_conversaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            rol TEXT NOT NULL,              -- "paciente" o "medico" (quién inició la conversación)
            resumen TEXT NOT NULL,          -- Resumen generado por el LLM de la conversación
            temas TEXT,                     -- Temas tratados: "receta,efectos_adversos,turno"
            acciones_realizadas TEXT,       -- "Se sacó turno para 2025-07-20, Se solicitó receta de Metformina"
            pendientes TEXT,               -- "Paciente reportó náuseas con Metformina, evaluar en próx consulta"
            fecha TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id)
        )
    """)

    conn.commit()
    return conn


# =============================================================================
# 2. DATOS DE EJEMPLO
# =============================================================================

def cargar_datos_ejemplo(conn: sqlite3.Connection):
    """Carga datos de ejemplo para testear el sistema."""
    cursor = conn.cursor()

    # --- Pacientes ---
    pacientes = [
        ("María", "González", "30123456", "1975-03-15", "+5491155551234",
         "maria.gonzalez@email.com", "OSDE", "12345678",
         "HTA,DM2", "Metformina 850mg c/12hs, Enalapril 10mg c/24hs", "2025-04-10"),
        ("Carlos", "Rodríguez", "28987654", "1970-08-22", "+5491155555678",
         "carlos.rod@email.com", "Swiss Medical", "87654321",
         "HTA,Obesidad,Dislipemia", "Losartán 50mg c/24hs, Atorvastatina 20mg c/24hs", "2025-01-15"),
        ("Ana", "Martínez", "35456789", "1985-11-03", "+5491155559012",
         "ana.martinez@email.com", "OSDE", "11223344",
         "DM2", "Metformina 1000mg c/12hs", "2025-06-01"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO pacientes
        (nombre, apellido, dni, fecha_nacimiento, telefono, email,
         obra_social, numero_afiliado, patologias, medicacion_actual, fecha_ultima_consulta)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, pacientes)

    # --- Agenda del médico (Lunes a Viernes, turnos de 30 min, 9:00-13:00) ---
    for dia in range(5):  # 0=Lunes a 4=Viernes
        for hora in range(9, 13):
            for minuto in ["00", "30"]:
                hora_inicio = f"{hora:02d}:{minuto}"
                if minuto == "00":
                    hora_fin = f"{hora:02d}:30"
                else:
                    hora_fin = f"{hora+1:02d}:00"
                cursor.execute("""
                    INSERT OR IGNORE INTO agenda_medico (dia_semana, hora_inicio, hora_fin)
                    VALUES (?, ?, ?)
                """, (dia, hora_inicio, hora_fin))

    # --- Medicamentos (vademecum básico) ---
    medicamentos = [
        ("Metformina", "Glucophage", "Comprimidos 500mg / 850mg / 1000mg",
         "850mg cada 12 horas con las comidas", "2550mg/día",
         "Insuficiencia renal severa, acidosis metabólica, insuficiencia hepática",
         "Náuseas, diarrea, dolor abdominal, déficit vitamina B12",
         "antidiabético"),
        ("Enalapril", "Lotrial", "Comprimidos 5mg / 10mg / 20mg",
         "10mg cada 24 horas", "40mg/día",
         "Embarazo, angioedema previo, estenosis bilateral de arterias renales",
         "Tos seca, hipotensión, hiperpotasemia, mareos",
         "antihipertensivo"),
        ("Losartán", "Cozaar", "Comprimidos 25mg / 50mg / 100mg",
         "50mg cada 24 horas", "100mg/día",
         "Embarazo, hiperpotasemia severa",
         "Mareos, hipotensión, hiperpotasemia",
         "antihipertensivo"),
        ("Atorvastatina", "Lipitor", "Comprimidos 10mg / 20mg / 40mg / 80mg",
         "20mg cada 24 horas por la noche", "80mg/día",
         "Enfermedad hepática activa, embarazo, lactancia",
         "Mialgias, elevación de transaminasas, rabdomiólisis (raro)",
         "hipolipemiante"),
        ("Amlodipina", "Norvasc", "Comprimidos 5mg / 10mg",
         "5mg cada 24 horas", "10mg/día",
         "Estenosis aórtica severa, shock cardiogénico",
         "Edema de miembros inferiores, cefalea, rubor facial",
         "antihipertensivo"),
        ("Glimepirida", "Amaryl", "Comprimidos 1mg / 2mg / 4mg",
         "2mg cada 24 horas antes del desayuno", "8mg/día",
         "DM1, cetoacidosis diabética, insuficiencia hepática o renal severa",
         "Hipoglucemia, aumento de peso, náuseas",
         "antidiabético"),
        ("Hidroclorotiazida", "Diurix", "Comprimidos 25mg / 50mg",
         "25mg cada 24 horas por la mañana", "50mg/día",
         "Anuria, hipopotasemia, hiponatremia severa",
         "Hipopotasemia, hiponatremia, hiperuricemia, hiperglucemia",
         "diurético"),
        ("Insulina Glargina", "Lantus", "Solución inyectable 100 UI/ml",
         "Según indicación médica, generalmente 10 UI/día al inicio", "Según indicación médica",
         "Hipoglucemia, hipersensibilidad a insulina glargina",
         "Hipoglucemia, reacciones en sitio de inyección, lipodistrofia",
         "insulina"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO medicamentos
        (nombre_generico, nombre_comercial, presentacion, dosis_habitual,
         dosis_maxima, contraindicaciones, efectos_adversos, categoria)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, medicamentos)

    # --- Turnos de ejemplo ---
    # Un turno futuro para María
    cursor.execute("""
        INSERT OR IGNORE INTO turnos (paciente_id, fecha, hora, motivo, tipo, estado)
        VALUES (1, '2025-07-20', '09:30', 'Control DM2 y HTA', 'seguimiento', 'confirmado')
    """)

    # Una solicitud pendiente
    cursor.execute("""
        INSERT OR IGNORE INTO solicitudes
        (paciente_id, tipo, descripcion, medicamento, dosis, cantidad)
        VALUES (1, 'receta', 'Solicitud de receta mensual', 'Metformina 850mg', '1 comprimido cada 12 horas', '2 cajas')
    """)

    # --- Historial de conversaciones de ejemplo ---
    conversaciones = [
        (1, "paciente",
         "La paciente consultó sobre efectos adversos de Metformina. Refiere náuseas después de tomar la pastilla. Se le recomendó tomarla durante las comidas y no en ayunas.",
         "efectos_adversos,metformina",
         "Se brindó recomendación sobre toma de Metformina con comidas",
         "Evaluar si persisten náuseas en próxima consulta",
         "2025-06-15 10:30:00"),
        (1, "paciente",
         "La paciente solicitó receta de Metformina 850mg (2 cajas) y Enalapril 10mg (1 caja). Ambas quedaron pendientes de aprobación médica.",
         "receta,metformina,enalapril",
         "Se crearon solicitudes de receta #5 y #6",
         None,
         "2025-06-28 14:15:00"),
        (2, "paciente",
         "El paciente preguntó cada cuánto tiene que hacerse análisis de sangre. Se le indicó que por sus patologías (HTA, Obesidad, Dislipemia) debería hacerse un control cada 3-6 meses. No tiene turno agendado.",
         "controles,análisis,seguimiento",
         "Se recomendó sacar turno para control",
         "Paciente sin turno — hace más de 5 meses de última consulta",
         "2025-05-20 09:00:00"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO historial_conversaciones
        (paciente_id, rol, resumen, temas, acciones_realizadas, pendientes, fecha)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, conversaciones)

    conn.commit()
    print("✅ Datos de ejemplo cargados correctamente.")


# =============================================================================
# 3. CONEXIÓN GLOBAL (se usa en todas las tools)
# =============================================================================

# Inicializar la DB al importar el módulo
conn = crear_base_de_datos()
cargar_datos_ejemplo(conn)


# =============================================================================
# 4. TOOLS DEL AGENTE PACIENTE
# =============================================================================

@tool
def registrar_paciente(
    nombre: str,
    apellido: str,
    dni: str,
    fecha_nacimiento: str,
    telefono: str,
    email: str,
    obra_social: str,
    numero_afiliado: str,
    patologias: str = "",
    medicacion_actual: str = ""
) -> str:
    """
    Registra un paciente nuevo en el sistema (primera vez).
    Requiere todos los datos filiatorios y de obra social.

    Args:
        nombre: Nombre del paciente
        apellido: Apellido del paciente
        dni: DNI del paciente (único)
        fecha_nacimiento: Fecha de nacimiento en formato YYYY-MM-DD
        telefono: Teléfono con código de área
        email: Email del paciente
        obra_social: Nombre de la obra social
        numero_afiliado: Número de afiliado de la obra social
        patologias: Patologías separadas por coma (ej: "HTA,DM2")
        medicacion_actual: Medicación actual del paciente
    Returns:
        Mensaje confirmando el registro o indicando error
    """
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pacientes
            (nombre, apellido, dni, fecha_nacimiento, telefono, email,
             obra_social, numero_afiliado, patologias, medicacion_actual)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (nombre, apellido, dni, fecha_nacimiento, telefono, email,
              obra_social, numero_afiliado, patologias, medicacion_actual))
        conn.commit()
        return f"✅ Paciente {nombre} {apellido} (DNI: {dni}) registrado exitosamente con ID #{cursor.lastrowid}."
    except sqlite3.IntegrityError:
        return f"⚠️ Ya existe un paciente con DNI {dni} en el sistema."
    except Exception as e:
        return f"❌ Error al registrar paciente: {str(e)}"


@tool
def buscar_paciente(criterio: str) -> str:
    """
    Busca un paciente por nombre, apellido o DNI.
    Útil para identificar al paciente antes de otras operaciones.

    Args:
        criterio: Nombre, apellido o DNI del paciente a buscar
    Returns:
        Información del paciente encontrado o mensaje de error
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, nombre, apellido, dni, obra_social, patologias,
               medicacion_actual, fecha_ultima_consulta
        FROM pacientes
        WHERE activo = 1
          AND (nombre LIKE ? OR apellido LIKE ? OR dni LIKE ?)
    """, (f"%{criterio}%", f"%{criterio}%", f"%{criterio}%"))

    resultados = cursor.fetchall()
    if not resultados:
        return f"No se encontró ningún paciente con el criterio '{criterio}'."

    respuesta = []
    for p in resultados:
        respuesta.append(
            f"• ID #{p['id']}: {p['nombre']} {p['apellido']} | "
            f"DNI: {p['dni']} | OS: {p['obra_social']} | "
            f"Patologías: {p['patologias'] or 'Ninguna registrada'} | "
            f"Última consulta: {p['fecha_ultima_consulta'] or 'Sin registro'}"
        )
    return f"Pacientes encontrados ({len(resultados)}):\n" + "\n".join(respuesta)


@tool
def consultar_agenda(fecha: str) -> str:
    """
    Consulta los horarios disponibles del médico para una fecha específica.
    Muestra solo los turnos que NO están ocupados.

    Args:
        fecha: Fecha en formato YYYY-MM-DD
    Returns:
        Lista de horarios disponibles o mensaje si no hay
    """
    try:
        fecha_dt = datetime.strptime(fecha, "%Y-%m-%d")
        dia_semana = fecha_dt.weekday()  # 0=Lunes

        if dia_semana >= 5:
            return f"El médico no atiende los fines de semana. La fecha {fecha} es un {'sábado' if dia_semana == 5 else 'domingo'}."

        cursor = conn.cursor()

        # Horarios de agenda para ese día
        cursor.execute("""
            SELECT hora_inicio, hora_fin FROM agenda_medico
            WHERE dia_semana = ? AND activo = 1
            ORDER BY hora_inicio
        """, (dia_semana,))
        horarios_agenda = cursor.fetchall()

        # Turnos ya tomados en esa fecha
        cursor.execute("""
            SELECT hora FROM turnos
            WHERE fecha = ? AND estado = 'confirmado'
        """, (fecha,))
        horas_ocupadas = {row['hora'] for row in cursor.fetchall()}

        disponibles = []
        for h in horarios_agenda:
            if h['hora_inicio'] not in horas_ocupadas:
                disponibles.append(f"  {h['hora_inicio']} - {h['hora_fin']}")

        dia_nombre = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"][dia_semana]

        if not disponibles:
            return f"No hay turnos disponibles para el {dia_nombre} {fecha}. Todos los horarios están ocupados."

        return (
            f"Horarios disponibles para el {dia_nombre} {fecha} "
            f"({len(disponibles)} turnos libres):\n" + "\n".join(disponibles)
        )
    except ValueError:
        return "⚠️ Formato de fecha inválido. Usá YYYY-MM-DD (ejemplo: 2025-07-15)."


@tool
def sacar_turno(
    paciente_id: int,
    fecha: str,
    hora: str,
    motivo: str,
    tipo: str = "seguimiento"
) -> str:
    """
    Agenda un turno para un paciente en una fecha y hora específicas.
    Verifica que el horario esté disponible antes de agendar.

    Args:
        paciente_id: ID del paciente en el sistema
        fecha: Fecha del turno en formato YYYY-MM-DD
        hora: Hora del turno en formato HH:MM (ej: "09:30")
        motivo: Motivo de la consulta (ej: "Control DM2", "Chequeo anual")
        tipo: Tipo de consulta: "primera_vez", "seguimiento" o "urgencia"
    Returns:
        Confirmación del turno o mensaje de error
    """
    cursor = conn.cursor()

    # Verificar que el paciente existe
    cursor.execute("SELECT nombre, apellido FROM pacientes WHERE id = ? AND activo = 1", (paciente_id,))
    paciente = cursor.fetchone()
    if not paciente:
        return f"⚠️ No se encontró un paciente activo con ID #{paciente_id}."

    # Verificar que no haya otro turno en esa fecha/hora
    cursor.execute("""
        SELECT id FROM turnos
        WHERE fecha = ? AND hora = ? AND estado = 'confirmado'
    """, (fecha, hora))
    if cursor.fetchone():
        return f"⚠️ El horario {hora} del {fecha} ya está ocupado. Consultá la agenda para ver horarios disponibles."

    # Verificar que el horario esté dentro de la agenda
    try:
        fecha_dt = datetime.strptime(fecha, "%Y-%m-%d")
        dia_semana = fecha_dt.weekday()
    except ValueError:
        return "⚠️ Formato de fecha inválido. Usá YYYY-MM-DD."

    cursor.execute("""
        SELECT id FROM agenda_medico
        WHERE dia_semana = ? AND hora_inicio = ? AND activo = 1
    """, (dia_semana, hora))
    if not cursor.fetchone():
        return f"⚠️ El horario {hora} no está dentro de la agenda del médico para ese día."

    # Crear el turno
    cursor.execute("""
        INSERT INTO turnos (paciente_id, fecha, hora, motivo, tipo)
        VALUES (?, ?, ?, ?, ?)
    """, (paciente_id, fecha, hora, motivo, tipo))
    conn.commit()

    return (
        f"✅ Turno confirmado:\n"
        f"  Paciente: {paciente['nombre']} {paciente['apellido']}\n"
        f"  Fecha: {fecha} a las {hora}\n"
        f"  Motivo: {motivo}\n"
        f"  Tipo: {tipo}\n"
        f"  ID del turno: #{cursor.lastrowid}"
    )


@tool
def cancelar_turno(turno_id: int) -> str:
    """
    Cancela un turno existente del paciente.

    Args:
        turno_id: ID del turno a cancelar
    Returns:
        Confirmación de la cancelación o error
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.id, t.fecha, t.hora, t.estado, p.nombre, p.apellido
        FROM turnos t JOIN pacientes p ON t.paciente_id = p.id
        WHERE t.id = ?
    """, (turno_id,))
    turno = cursor.fetchone()

    if not turno:
        return f"⚠️ No se encontró un turno con ID #{turno_id}."
    if turno['estado'] == 'cancelado':
        return f"⚠️ El turno #{turno_id} ya estaba cancelado."
    if turno['estado'] == 'completado':
        return f"⚠️ El turno #{turno_id} ya fue completado y no se puede cancelar."

    cursor.execute("""
        UPDATE turnos SET estado = 'cancelado' WHERE id = ?
    """, (turno_id,))
    conn.commit()

    return (
        f"✅ Turno #{turno_id} cancelado:\n"
        f"  Paciente: {turno['nombre']} {turno['apellido']}\n"
        f"  Era para: {turno['fecha']} a las {turno['hora']}"
    )


@tool
def mis_turnos(paciente_id: int) -> str:
    """
    Muestra los turnos próximos (confirmados) de un paciente.

    Args:
        paciente_id: ID del paciente
    Returns:
        Lista de turnos futuros del paciente
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, fecha, hora, motivo, tipo, estado
        FROM turnos
        WHERE paciente_id = ? AND estado = 'confirmado'
        ORDER BY fecha, hora
    """, (paciente_id,))

    turnos = cursor.fetchall()
    if not turnos:
        return "No tenés turnos confirmados próximamente."

    respuesta = [f"Turnos confirmados ({len(turnos)}):"]
    for t in turnos:
        respuesta.append(
            f"  • Turno #{t['id']}: {t['fecha']} a las {t['hora']} — "
            f"{t['motivo']} ({t['tipo']})"
        )
    return "\n".join(respuesta)


@tool
def solicitar_receta(
    paciente_id: int,
    medicamento: str,
    dosis: str,
    cantidad: str
) -> str:
    """
    Permite al paciente solicitar una receta médica.
    La solicitud queda pendiente hasta que el médico la apruebe.

    Args:
        paciente_id: ID del paciente
        medicamento: Nombre del medicamento (ej: "Metformina 850mg")
        dosis: Posología indicada (ej: "1 comprimido cada 12 horas")
        cantidad: Cantidad de envases solicitados (ej: "2 cajas")
    Returns:
        Confirmación de la solicitud con su ID
    """
    cursor = conn.cursor()

    # Verificar paciente
    cursor.execute("SELECT nombre, apellido FROM pacientes WHERE id = ? AND activo = 1", (paciente_id,))
    paciente = cursor.fetchone()
    if not paciente:
        return f"⚠️ No se encontró un paciente activo con ID #{paciente_id}."

    # Buscar si el medicamento existe en el vademecum
    cursor.execute("""
        SELECT nombre_generico, dosis_habitual FROM medicamentos
        WHERE nombre_generico LIKE ? OR nombre_comercial LIKE ?
    """, (f"%{medicamento}%", f"%{medicamento}%"))
    med = cursor.fetchone()

    descripcion = f"Solicitud de receta: {medicamento}, {dosis}, {cantidad}"
    if med:
        descripcion += f" (Vademecum: dosis habitual = {med['dosis_habitual']})"

    cursor.execute("""
        INSERT INTO solicitudes (paciente_id, tipo, descripcion, medicamento, dosis, cantidad)
        VALUES (?, 'receta', ?, ?, ?, ?)
    """, (paciente_id, descripcion, medicamento, dosis, cantidad))
    conn.commit()

    return (
        f"✅ Solicitud de receta creada (ID #{cursor.lastrowid}):\n"
        f"  Paciente: {paciente['nombre']} {paciente['apellido']}\n"
        f"  Medicamento: {medicamento}\n"
        f"  Dosis: {dosis}\n"
        f"  Cantidad: {cantidad}\n"
        f"  Estado: PENDIENTE de aprobación médica."
    )


@tool
def enviar_consulta_medica(paciente_id: int, consulta: str) -> str:
    """
    Permite al paciente enviar una consulta menor al médico.
    El agente genera un borrador de respuesta que el médico debe aprobar.
    Ideal para dudas sobre medicación, efectos adversos, controles, etc.

    Args:
        paciente_id: ID del paciente
        consulta: Texto de la consulta del paciente
    Returns:
        Confirmación de que la consulta fue registrada
    """
    cursor = conn.cursor()

    cursor.execute("SELECT nombre, apellido FROM pacientes WHERE id = ? AND activo = 1", (paciente_id,))
    paciente = cursor.fetchone()
    if not paciente:
        return f"⚠️ No se encontró un paciente activo con ID #{paciente_id}."

    cursor.execute("""
        INSERT INTO solicitudes (paciente_id, tipo, descripcion)
        VALUES (?, 'consulta_medica', ?)
    """, (paciente_id, consulta))
    conn.commit()

    return (
        f"✅ Consulta registrada (ID #{cursor.lastrowid}):\n"
        f"  Paciente: {paciente['nombre']} {paciente['apellido']}\n"
        f"  Consulta: {consulta}\n"
        f"  Estado: PENDIENTE — el médico la revisará y responderá."
    )


# =============================================================================
# 5. TOOLS DEL AGENTE MÉDICO
# =============================================================================

@tool
def ver_turnos_del_dia(fecha: str = "") -> str:
    """
    Muestra los turnos confirmados para un día específico,
    con la información del paciente incluida.
    Si no se especifica fecha, muestra los de hoy.

    Args:
        fecha: Fecha en formato YYYY-MM-DD (vacío = hoy)
    Returns:
        Lista de turnos del día con datos del paciente
    """
    if not fecha:
        fecha = datetime.now().strftime("%Y-%m-%d")

    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.hora, t.motivo, t.tipo,
               p.nombre, p.apellido, p.dni, p.obra_social,
               p.patologias, p.medicacion_actual
        FROM turnos t
        JOIN pacientes p ON t.paciente_id = p.id
        WHERE t.fecha = ? AND t.estado = 'confirmado'
        ORDER BY t.hora
    """, (fecha,))

    turnos = cursor.fetchall()
    if not turnos:
        return f"No hay turnos confirmados para el {fecha}."

    respuesta = [f"Agenda del {fecha} ({len(turnos)} turnos):"]
    for t in turnos:
        respuesta.append(
            f"\n  🕐 {t['hora']} — Turno #{t['id']}\n"
            f"    Paciente: {t['nombre']} {t['apellido']} (DNI: {t['dni']})\n"
            f"    OS: {t['obra_social']} | Tipo: {t['tipo']}\n"
            f"    Motivo: {t['motivo']}\n"
            f"    Patologías: {t['patologias'] or 'Ninguna'}\n"
            f"    Medicación: {t['medicacion_actual'] or 'Ninguna'}"
        )
    return "\n".join(respuesta)


@tool
def ver_solicitudes_pendientes() -> str:
    """
    Muestra todas las solicitudes pendientes de aprobación:
    recetas, consultas médicas, formularios, etc.

    Returns:
        Lista de solicitudes pendientes con detalle
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.id, s.tipo, s.descripcion, s.medicamento, s.dosis,
               s.cantidad, s.respuesta_borrador, s.fecha_creacion,
               p.nombre, p.apellido
        FROM solicitudes s
        JOIN pacientes p ON s.paciente_id = p.id
        WHERE s.estado = 'pendiente'
        ORDER BY s.fecha_creacion
    """)

    solicitudes = cursor.fetchall()
    if not solicitudes:
        return "✅ No hay solicitudes pendientes."

    respuesta = [f"Solicitudes pendientes ({len(solicitudes)}):"]
    for s in solicitudes:
        detalle = f"\n  📋 Solicitud #{s['id']} ({s['tipo'].upper()})\n"
        detalle += f"    Paciente: {s['nombre']} {s['apellido']}\n"
        detalle += f"    Fecha: {s['fecha_creacion']}\n"
        detalle += f"    Descripción: {s['descripcion']}\n"
        if s['medicamento']:
            detalle += f"    Medicamento: {s['medicamento']} | Dosis: {s['dosis']} | Cant: {s['cantidad']}\n"
        if s['respuesta_borrador']:
            detalle += f"    Respuesta borrador: {s['respuesta_borrador']}\n"
        respuesta.append(detalle)

    return "\n".join(respuesta)


@tool
def aprobar_solicitud(solicitud_id: int, nota_medico: str = "") -> str:
    """
    Aprueba una solicitud pendiente (receta, consulta, formulario).
    El médico puede agregar una nota o modificación.

    Args:
        solicitud_id: ID de la solicitud a aprobar
        nota_medico: Nota opcional del médico (correcciones, indicaciones adicionales)
    Returns:
        Confirmación de la aprobación
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.id, s.tipo, s.estado, s.paciente_id, p.nombre, p.apellido
        FROM solicitudes s JOIN pacientes p ON s.paciente_id = p.id
        WHERE s.id = ?
    """, (solicitud_id,))
    sol = cursor.fetchone()

    if not sol:
        return f"⚠️ No se encontró la solicitud #{solicitud_id}."
    if sol['estado'] != 'pendiente':
        return f"⚠️ La solicitud #{solicitud_id} ya fue {sol['estado']}."

    cursor.execute("""
        UPDATE solicitudes
        SET estado = 'aprobada',
            respuesta_medico = ?,
            fecha_resolucion = datetime('now', 'localtime')
        WHERE id = ?
    """, (nota_medico, solicitud_id))
    conn.commit()

    return (
        f"✅ Solicitud #{solicitud_id} APROBADA:\n"
        f"  Tipo: {sol['tipo']}\n"
        f"  Paciente: {sol['nombre']} {sol['apellido']}\n"
        f"  Nota del médico: {nota_medico or 'Sin observaciones'}"
    )


@tool
def rechazar_solicitud(solicitud_id: int, motivo: str) -> str:
    """
    Rechaza una solicitud pendiente con un motivo.

    Args:
        solicitud_id: ID de la solicitud a rechazar
        motivo: Motivo del rechazo (obligatorio)
    Returns:
        Confirmación del rechazo
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.id, s.tipo, s.estado, p.nombre, p.apellido
        FROM solicitudes s JOIN pacientes p ON s.paciente_id = p.id
        WHERE s.id = ?
    """, (solicitud_id,))
    sol = cursor.fetchone()

    if not sol:
        return f"⚠️ No se encontró la solicitud #{solicitud_id}."
    if sol['estado'] != 'pendiente':
        return f"⚠️ La solicitud #{solicitud_id} ya fue {sol['estado']}."

    cursor.execute("""
        UPDATE solicitudes
        SET estado = 'rechazada',
            respuesta_medico = ?,
            fecha_resolucion = datetime('now', 'localtime')
        WHERE id = ?
    """, (motivo, solicitud_id))
    conn.commit()

    return (
        f"❌ Solicitud #{solicitud_id} RECHAZADA:\n"
        f"  Tipo: {sol['tipo']}\n"
        f"  Paciente: {sol['nombre']} {sol['apellido']}\n"
        f"  Motivo: {motivo}"
    )


@tool
def cancelar_dia_completo(fecha: str, motivo: str) -> str:
    """
    Cancela todos los turnos confirmados de un día entero.
    Uso exclusivo del médico cuando no puede atender (enfermedad, 
    congreso, urgencia personal, etc.). Devuelve la lista de 
    pacientes afectados para que se les pueda notificar.

    Args:
        fecha: Fecha a cancelar en formato YYYY-MM-DD
        motivo: Motivo de la cancelación del día
    Returns:
        Lista de turnos cancelados con datos de los pacientes afectados
    """
    cursor = conn.cursor()

    # Buscar turnos confirmados de ese día
    cursor.execute("""
        SELECT t.id, t.hora, t.motivo,
               p.nombre, p.apellido, p.telefono, p.email
        FROM turnos t
        JOIN pacientes p ON t.paciente_id = p.id
        WHERE t.fecha = ? AND t.estado = 'confirmado'
        ORDER BY t.hora
    """, (fecha,))

    turnos = cursor.fetchall()
    if not turnos:
        return f"No hay turnos confirmados para el {fecha}. No se canceló nada."

    # Cancelar todos
    cursor.execute("""
        UPDATE turnos
        SET estado = 'cancelado', notas = ?
        WHERE fecha = ? AND estado = 'confirmado'
    """, (f"Cancelado por médico: {motivo}", fecha))
    conn.commit()

    respuesta = [
        f"⚠️ Se cancelaron {len(turnos)} turnos del {fecha}.\n"
        f"  Motivo: {motivo}\n"
        f"\n  Pacientes a notificar:"
    ]
    for t in turnos:
        respuesta.append(
            f"    • {t['hora']} — {t['nombre']} {t['apellido']}\n"
            f"      Tel: {t['telefono']} | Email: {t['email']}\n"
            f"      Turno #{t['id']} (era: {t['motivo']})"
        )

    return "\n".join(respuesta)


@tool
def consultar_vademecum(medicamento: str) -> str:
    """
    Consulta información de un medicamento en el vademecum:
    dosis habitual, dosis máxima, contraindicaciones y efectos adversos.

    Args:
        medicamento: Nombre genérico o comercial del medicamento
    Returns:
        Información completa del medicamento
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM medicamentos
        WHERE nombre_generico LIKE ? OR nombre_comercial LIKE ?
    """, (f"%{medicamento}%", f"%{medicamento}%"))

    resultados = cursor.fetchall()
    if not resultados:
        return f"No se encontró '{medicamento}' en el vademecum. Verificá el nombre."

    respuesta = []
    for m in resultados:
        respuesta.append(
            f"💊 {m['nombre_generico']} ({m['nombre_comercial']})\n"
            f"  Presentación: {m['presentacion']}\n"
            f"  Dosis habitual: {m['dosis_habitual']}\n"
            f"  Dosis máxima: {m['dosis_maxima']}\n"
            f"  Categoría: {m['categoria']}\n"
            f"  Contraindicaciones: {m['contraindicaciones']}\n"
            f"  Efectos adversos: {m['efectos_adversos']}"
        )
    return "\n\n".join(respuesta)


@tool
def info_paciente(paciente_id: int) -> str:
    """
    Muestra la información completa de un paciente.
    Uso exclusivo del médico para consultar historial.

    Args:
        paciente_id: ID del paciente
    Returns:
        Ficha completa del paciente
    """
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pacientes WHERE id = ? AND activo = 1", (paciente_id,))
    p = cursor.fetchone()

    if not p:
        return f"⚠️ No se encontró un paciente activo con ID #{paciente_id}."

    return (
        f"📋 Ficha del paciente #{p['id']}:\n"
        f"  Nombre: {p['nombre']} {p['apellido']}\n"
        f"  DNI: {p['dni']}\n"
        f"  Fecha de nacimiento: {p['fecha_nacimiento']}\n"
        f"  Teléfono: {p['telefono']}\n"
        f"  Email: {p['email']}\n"
        f"  Obra Social: {p['obra_social']} (Afiliado: {p['numero_afiliado']})\n"
        f"  Patologías: {p['patologias'] or 'Ninguna registrada'}\n"
        f"  Medicación actual: {p['medicacion_actual'] or 'Ninguna registrada'}\n"
        f"  Última consulta: {p['fecha_ultima_consulta'] or 'Sin registro'}\n"
        f"  Registrado desde: {p['fecha_registro']}"
    )


@tool
def pacientes_sin_control() -> str:
    """
    Lista pacientes con enfermedades crónicas que no tienen consulta
    reciente ni turno agendado. Útil para el médico para seguimiento
    proactivo y para el agente paciente para sugerir controles.

    Returns:
        Lista de pacientes que necesitan control con días sin consulta
    """
    cursor = conn.cursor()
    hoy = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT p.id, p.nombre, p.apellido, p.patologias,
               p.fecha_ultima_consulta, p.telefono, p.email
        FROM pacientes p
        WHERE p.activo = 1
          AND p.patologias IS NOT NULL
          AND p.patologias != ''
          AND p.id NOT IN (
              SELECT DISTINCT paciente_id FROM turnos
              WHERE estado = 'confirmado' AND fecha >= ?
          )
        ORDER BY p.fecha_ultima_consulta ASC
    """, (hoy,))

    pacientes = cursor.fetchall()
    if not pacientes:
        return "✅ Todos los pacientes crónicos tienen turnos agendados o consulta reciente."

    respuesta = [f"⚠️ Pacientes crónicos sin turno agendado ({len(pacientes)}):"]
    for p in pacientes:
        dias = "N/A"
        if p['fecha_ultima_consulta']:
            try:
                ultima = datetime.strptime(p['fecha_ultima_consulta'], "%Y-%m-%d")
                dias = (datetime.now() - ultima).days
            except ValueError:
                pass
        respuesta.append(
            f"\n  • {p['nombre']} {p['apellido']} (ID #{p['id']})\n"
            f"    Patologías: {p['patologias']}\n"
            f"    Última consulta: {p['fecha_ultima_consulta'] or 'Nunca'} ({dias} días)\n"
            f"    Contacto: {p['email']} / {p['telefono']}"
        )
    return "\n".join(respuesta)


@tool
def buscar_pubmed(query: str, max_resultados: int = 3) -> str:
    """
    Busca artículos científicos en PubMed.
    Usar cuando el médico pregunta por evidencia, estudios o literatura médica.
    La query debe estar en inglés para mejores resultados.

    Args:
        query: Términos de búsqueda en inglés (ej: "metformin renal impairment dosage")
        max_resultados: Cantidad máxima de artículos a devolver (por defecto 3)
    Returns:
        Lista de artículos con título, autores, revista, fecha y link
    """
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    try:
        # Paso 1: Buscar IDs de artículos
        search_url = f"{base_url}/esearch.fcgi"
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_resultados,
            "retmode": "json",
            "sort": "relevance",
        }
        search_resp = requests.get(search_url, params=search_params, timeout=10)
        search_resp.raise_for_status()
        ids = search_resp.json()["esearchresult"]["idlist"]

        if not ids:
            return f"No se encontraron artículos para: '{query}'"

        # Paso 2: Obtener resúmenes de los artículos encontrados
        summary_url = f"{base_url}/esummary.fcgi"
        summary_params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
        }
        summary_resp = requests.get(summary_url, params=summary_params, timeout=10)
        summary_resp.raise_for_status()
        results = summary_resp.json()["result"]

        # Paso 3: Formatear resultados
        articulos = []
        for uid in ids:
            if uid in results:
                art = results[uid]
                titulo = art.get("title", "Sin título")
                autores = art.get("authors", [])
                autor_str = autores[0]["name"] + " et al." if autores else "Autor desconocido"
                fecha = art.get("pubdate", "Fecha desconocida")
                revista = art.get("fulljournalname", art.get("source", ""))

                articulos.append(
                    f"- {titulo}\n"
                    f"  Autores: {autor_str} | Revista: {revista} | Fecha: {fecha}\n"
                    f"  Link: https://pubmed.ncbi.nlm.nih.gov/{uid}/"
                )

        return f"Se encontraron {len(articulos)} artículos:\n\n" + "\n\n".join(articulos)

    except requests.RequestException as e:
        return f"Error al consultar PubMed: {str(e)}"


# =============================================================================
# 6. TOOLS DE MEMORIA (compartidas entre ambos agentes)
# =============================================================================

@tool
def recuperar_historial_paciente(paciente_id: int, limite: int = 5) -> str:
    """
    Recupera el historial de conversaciones previas con un paciente.
    Permite al agente recordar interacciones pasadas para dar continuidad
    y contexto personalizado. Se usa al inicio de cada conversación.

    Args:
        paciente_id: ID del paciente
        limite: Cantidad máxima de conversaciones a recuperar (por defecto 5)
    Returns:
        Resumen de las últimas conversaciones con el paciente
    """
    cursor = conn.cursor()

    # Datos básicos del paciente
    cursor.execute("SELECT nombre, apellido FROM pacientes WHERE id = ? AND activo = 1", (paciente_id,))
    paciente = cursor.fetchone()
    if not paciente:
        return f"⚠️ No se encontró un paciente activo con ID #{paciente_id}."

    # Historial de conversaciones
    cursor.execute("""
        SELECT resumen, temas, acciones_realizadas, pendientes, fecha
        FROM historial_conversaciones
        WHERE paciente_id = ?
        ORDER BY fecha DESC
        LIMIT ?
    """, (paciente_id, limite))

    historial = cursor.fetchall()
    if not historial:
        return f"No hay conversaciones previas registradas con {paciente['nombre']} {paciente['apellido']}. Es la primera interacción."

    respuesta = [
        f"Historial de conversaciones con {paciente['nombre']} {paciente['apellido']} "
        f"(últimas {len(historial)}):"
    ]

    for h in historial:
        entrada = f"\n  📅 {h['fecha']}\n"
        entrada += f"    Resumen: {h['resumen']}\n"
        entrada += f"    Temas: {h['temas']}\n"
        if h['acciones_realizadas']:
            entrada += f"    Acciones: {h['acciones_realizadas']}\n"
        if h['pendientes']:
            entrada += f"    ⚠️ Pendientes: {h['pendientes']}"
        respuesta.append(entrada)

    return "\n".join(respuesta)


@tool
def guardar_resumen_conversacion(
    paciente_id: int,
    rol: str,
    resumen: str,
    temas: str,
    acciones_realizadas: str = "",
    pendientes: str = ""
) -> str:
    """
    Guarda un resumen de la conversación actual para memoria futura.
    Se debe llamar al finalizar cada conversación con un paciente.
    El resumen lo genera el propio LLM a partir del historial de mensajes.

    Args:
        paciente_id: ID del paciente
        rol: Quién inició la conversación ("paciente" o "medico")
        resumen: Resumen breve de la conversación (2-3 oraciones)
        temas: Temas tratados separados por coma (ej: "receta,turno,efectos_adversos")
        acciones_realizadas: Acciones concretas que se hicieron durante la conversación
        pendientes: Temas que quedaron pendientes para la próxima interacción
    Returns:
        Confirmación de que el resumen fue guardado
    """
    cursor = conn.cursor()

    cursor.execute("SELECT nombre, apellido FROM pacientes WHERE id = ? AND activo = 1", (paciente_id,))
    paciente = cursor.fetchone()
    if not paciente:
        return f"⚠️ No se encontró un paciente activo con ID #{paciente_id}."

    cursor.execute("""
        INSERT INTO historial_conversaciones
        (paciente_id, rol, resumen, temas, acciones_realizadas, pendientes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (paciente_id, rol, resumen, temas, acciones_realizadas, pendientes))
    conn.commit()

    return (
        f"✅ Resumen de conversación guardado (ID #{cursor.lastrowid}):\n"
        f"  Paciente: {paciente['nombre']} {paciente['apellido']}\n"
        f"  Temas: {temas}\n"
        f"  Pendientes: {pendientes or 'Ninguno'}"
    )


# =============================================================================
# 7. LISTAS DE TOOLS POR AGENTE (para usar en LangGraph)
# =============================================================================

tools_paciente = [
    registrar_paciente,
    buscar_paciente,
    consultar_agenda,
    sacar_turno,
    cancelar_turno,
    mis_turnos,
    solicitar_receta,
    enviar_consulta_medica,
    recuperar_historial_paciente,  # Memoria: leer historial al inicio
    guardar_resumen_conversacion,  # Memoria: guardar resumen al final
]

tools_medico = [
    ver_turnos_del_dia,
    ver_solicitudes_pendientes,
    aprobar_solicitud,
    rechazar_solicitud,
    cancelar_dia_completo,          # Cancelar todos los turnos de un día
    consultar_vademecum,
    buscar_pubmed,                  # Búsqueda de literatura médica
    info_paciente,
    buscar_paciente,
    pacientes_sin_control,
    recuperar_historial_paciente,  # Memoria: ver interacciones previas del paciente
    guardar_resumen_conversacion,  # Memoria: registrar lo que se hizo
]

# =============================================================================
# 8. TEST RÁPIDO
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("TEST DE TOOLS — Agente Consultorio")
    print("=" * 60)

    print("\n--- Test: buscar_paciente ---")
    print(buscar_paciente.invoke({"criterio": "González"}))

    print("\n--- Test: consultar_agenda ---")
    hoy = datetime.now()
    dias_hasta_lunes = (7 - hoy.weekday()) % 7
    if dias_hasta_lunes == 0:
        dias_hasta_lunes = 7
    proximo_lunes = (hoy + timedelta(days=dias_hasta_lunes)).strftime("%Y-%m-%d")
    print(consultar_agenda.invoke({"fecha": proximo_lunes}))

    print("\n--- Test: mis_turnos ---")
    print(mis_turnos.invoke({"paciente_id": 1}))

    print("\n--- Test: consultar_vademecum ---")
    print(consultar_vademecum.invoke({"medicamento": "metformina"}))

    print("\n--- Test: ver_solicitudes_pendientes ---")
    print(ver_solicitudes_pendientes.invoke({}))

    print("\n--- Test: pacientes_sin_control ---")
    print(pacientes_sin_control.invoke({}))

    print("\n--- Test: recuperar_historial_paciente (MEMORIA) ---")
    print(recuperar_historial_paciente.invoke({"paciente_id": 1}))

    print("\n--- Test: guardar_resumen_conversacion (MEMORIA) ---")
    print(guardar_resumen_conversacion.invoke({
        "paciente_id": 1,
        "rol": "paciente",
        "resumen": "La paciente consultó sobre horarios disponibles y sacó turno para control de DM2 el próximo lunes a las 10:00.",
        "temas": "turno,control_dm2",
        "acciones_realizadas": "Se agendó turno para control DM2",
        "pendientes": "Traer últimos análisis de laboratorio al turno"
    }))

    print("\n--- Test: recuperar_historial_paciente después de guardar ---")
    print(recuperar_historial_paciente.invoke({"paciente_id": 1}))

    print("\n" + "=" * 60)
    print("✅ Todos los tests ejecutados.")
    print("=" * 60)
