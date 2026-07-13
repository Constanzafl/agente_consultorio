"""
=============================================================================
AGENTE CONSULTORIO MÉDICO — Fase 1: Base de datos (esquema + datos + conexión)
=============================================================================
Este módulo contiene:
  1. Esquema SQLite (6 tablas: pacientes, agenda_medico, turnos,
     solicitudes, historial_conversaciones)
  2. Datos de ejemplo (idempotentes) para testing
  3. La conexión global `conn` que usan todas las tools (ver tools.py)
=============================================================================
"""

import sys
import sqlite3
import pathlib
import threading

# Consola en UTF-8 (Windows) para no romper al imprimir caracteres especiales.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# La base vive SIEMPRE en la raíz del repo (un nivel arriba de este archivo),
# sin importar desde qué carpeta ejecutes. Evita crear varios consultorio.db.
DB_PATH_DEFAULT = str(pathlib.Path(__file__).resolve().parent.parent / "consultorio.db")

# =============================================================================
# 1. BASE DE DATOS — Esquema
# =============================================================================

def crear_base_de_datos(db_path: str = DB_PATH_DEFAULT) -> sqlite3.Connection:
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
            plan TEXT,                -- Plan dentro de la obra social (ej: "210", "Plata")
            numero_afiliado TEXT,
            patologias TEXT,          -- Ej: "HTA,DM2,Obesidad" (separadas por coma)
            medicacion_actual TEXT,   -- Ej: "Metformina 850mg c/12hs, Enalapril 10mg c/24hs"
            fecha_ultima_consulta TEXT,
            activo INTEGER DEFAULT 1,
            fecha_registro TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # --- MÉDICOS del centro ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            apellido TEXT NOT NULL,
            especialidad TEXT,
            activo INTEGER DEFAULT 1
        )
    """)

    # --- AGENDA (horarios disponibles por médico y día de semana) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agenda_medico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medico_id INTEGER NOT NULL,     -- de qué médico es este horario
            dia_semana INTEGER NOT NULL,    -- 0=Lunes, 1=Martes, ..., 4=Viernes
            hora_inicio TEXT NOT NULL,      -- Ej: "09:00"
            hora_fin TEXT NOT NULL,         -- Ej: "09:30" (turnos de 30 min)
            activo INTEGER DEFAULT 1,
            UNIQUE(medico_id, dia_semana, hora_inicio),  -- evita franjas duplicadas
            FOREIGN KEY (medico_id) REFERENCES medicos(id)
        )
    """)

    # --- TURNOS ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS turnos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            medico_id INTEGER NOT NULL,     -- con qué médico es el turno
            fecha TEXT NOT NULL,            -- "2025-07-15"
            hora TEXT NOT NULL,             -- "09:00"
            motivo TEXT,                    -- "Control DM2", "Seguimiento HTA", "Primera consulta"
            tipo TEXT DEFAULT 'seguimiento', -- "primera_vez", "seguimiento", "urgencia"
            estado TEXT DEFAULT 'confirmado', -- "confirmado", "cancelado", "completado"
            recordatorio_enviado INTEGER DEFAULT 0,
            notas TEXT,
            fecha_creacion TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id),
            FOREIGN KEY (medico_id) REFERENCES medicos(id)
        )
    """)

    # NOTA: la info de medicamentos NO se guarda en la DB. Se consulta en vivo con
    # la tool buscar_medicamento (OpenFDA). Así no hay vademecum que mantener a mano.

    # --- RECETAS / SOLICITUDES ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solicitudes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            medico_id INTEGER,             -- médico al que va dirigida la solicitud
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
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id),
            FOREIGN KEY (medico_id) REFERENCES medicos(id)
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
    """Carga datos de ejemplo para testear el sistema.
    Es idempotente: si la DB ya fue sembrada, no hace nada (evita duplicar
    turnos, solicitudes e historial en cada import del módulo)."""
    cursor = conn.cursor()

    # Guard: si ya hay pacientes cargados, asumimos que la DB está sembrada.
    cursor.execute("SELECT COUNT(*) FROM pacientes")
    if cursor.fetchone()[0] > 0:
        return

    # --- Pacientes (con PLAN además de obra social) ---
    pacientes = [
        ("María", "González", "30123456", "1975-03-15", "+5491155551234",
         "maria.gonzalez@email.com", "OSDE", "210", "12345678",
         "HTA,DM2", "Metformina 850mg c/12hs, Enalapril 10mg c/24hs", "2025-04-10"),
        ("Carlos", "Rodríguez", "28987654", "1970-08-22", "+5491155555678",
         "carlos.rod@email.com", "Swiss Medical", "SMG20", "87654321",
         "HTA,Obesidad,Dislipemia", "Losartán 50mg c/24hs, Atorvastatina 20mg c/24hs", "2025-01-15"),
        ("Ana", "Martínez", "35456789", "1985-11-03", "+5491155559012",
         "ana.martinez@email.com", "OSDE", "310", "11223344",
         "DM2", "Metformina 1000mg c/12hs", "2025-06-01"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO pacientes
        (nombre, apellido, dni, fecha_nacimiento, telefono, email,
         obra_social, plan, numero_afiliado, patologias, medicacion_actual, fecha_ultima_consulta)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, pacientes)

    # --- Médicos del centro ---
    medicos = [
        ("Juan", "Pérez", "Medicina Familiar"),
        ("Laura", "Gómez", "Cardiología"),
    ]
    cursor.executemany("""
        INSERT OR IGNORE INTO medicos (nombre, apellido, especialidad) VALUES (?, ?, ?)
    """, medicos)

    # --- Agenda de cada médico (Lunes a Viernes, turnos de 30 min, 9:00-13:00) ---
    cursor.execute("SELECT id FROM medicos")
    for (medico_id,) in cursor.fetchall():
        for dia in range(5):  # 0=Lunes a 4=Viernes
            for hora in range(9, 13):
                for minuto in ["00", "30"]:
                    hora_inicio = f"{hora:02d}:{minuto}"
                    hora_fin = f"{hora:02d}:30" if minuto == "00" else f"{hora+1:02d}:00"
                    cursor.execute("""
                        INSERT OR IGNORE INTO agenda_medico (medico_id, dia_semana, hora_inicio, hora_fin)
                        VALUES (?, ?, ?, ?)
                    """, (medico_id, dia, hora_inicio, hora_fin))

    # --- Turnos de ejemplo ---
    # Un turno futuro para María con el Dr. Pérez (medico_id=1)
    cursor.execute("""
        INSERT OR IGNORE INTO turnos (paciente_id, medico_id, fecha, hora, motivo, tipo, estado)
        VALUES (1, 1, '2025-07-20', '09:30', 'Control DM2 y HTA', 'seguimiento', 'confirmado')
    """)

    # Una solicitud pendiente (dirigida al Dr. Pérez, medico_id=1)
    cursor.execute("""
        INSERT OR IGNORE INTO solicitudes
        (paciente_id, medico_id, tipo, descripcion, medicamento, dosis, cantidad)
        VALUES (1, 1, 'receta', 'Solicitud de receta mensual', 'Metformina 850mg', '1 comprimido cada 12 horas', '2 cajas')
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
    print("Datos de ejemplo cargados correctamente.")


# =============================================================================
# 3. CONEXIÓN GLOBAL — una por hilo (thread-safe)
# =============================================================================
# SQLite NO permite usar la MISMA conexión desde varios hilos a la vez. Como
# LangGraph corre tools en paralelo (hilos) y Chainlit usa un worker thread,
# damos a CADA hilo su propia conexión al mismo archivo. Las tools siguen usando
# `conn` como siempre; el proxy resuelve la conexión del hilo por debajo.

_local = threading.local()


def _conexion_del_hilo() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH_DEFAULT, check_same_thread=False)
        c.row_factory = sqlite3.Row
        _local.conn = c
    return c


class _ConexionPorHilo:
    """Proxy que redirige todo (cursor, execute, commit...) a la conexión del hilo actual."""
    def __getattr__(self, nombre):
        return getattr(_conexion_del_hilo(), nombre)


# Inicializar la DB (esquema + datos) una sola vez, y exponer el proxy por hilo.
_bootstrap = crear_base_de_datos()
cargar_datos_ejemplo(_bootstrap)
_bootstrap.close()

conn = _ConexionPorHilo()


