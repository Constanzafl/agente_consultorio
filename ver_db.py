"""
Muestra el estado actual de la base (consultorio.db).
Sirve para VER que las acciones del agente (sacar turno, pedir receta, aprobar)
 . Correr:  python ver_db.py
"""

import sys
import sqlite3
import pathlib

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = pathlib.Path(__file__).resolve().parent / "consultorio.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row


def mostrar(titulo: str, query: str, campos: list[str]):
    print(f"\n=== {titulo} ===")
    filas = conn.execute(query).fetchall()
    if not filas:
        print("  (vacío)")
        return
    for r in filas:
        print("  " + " | ".join(f"{c}={r[c]}" for c in campos))


if __name__ == "__main__":
    print(f"Base: {DB}")
    mostrar("PACIENTES", "SELECT * FROM pacientes ORDER BY id",
            ["id","dni","email", "nombre", "apellido", "patologias"])
    mostrar("TURNOS", "SELECT * FROM turnos ORDER BY fecha, hora",
            ["id", "paciente_id", "fecha", "hora", "motivo", "estado"])
    mostrar("SOLICITUDES", "SELECT * FROM solicitudes ORDER BY id",
            ["id", "paciente_id", "tipo", "medicamento", "estado"])
