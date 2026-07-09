"""
=============================================================================
Script para PROBAR el agente completo a mano (jugar y entender).
=============================================================================
Cómo usar:
  1. Levantá LM Studio (Developer -> Start Server, con gemma-4-e4b cargado).
  2. Corré:   python agente_consultorio/probar_agente.py
  3. Cambiá 'pregunta', 'rol' o 'paciente_id' abajo y volvé a correr para probar cosas.
=============================================================================
"""

# Import robusto (funciona corriendo el archivo directo o como paquete)
try:
    from grafo import construir_grafo, chatear
    from llm import proveedores_disponibles
except ImportError:
    from .grafo import construir_grafo, chatear
    from .llm import proveedores_disponibles

print("Proveedores de LLM disponibles:", proveedores_disponibles())
app = construir_grafo()

# ---------------------------------------------------------------------------
# CAMBIÁ ESTO PARA PROBAR DISTINTAS COSAS:
# ---------------------------------------------------------------------------
pregunta = "Cual es la dosis recomendada de metformina para un paciente con diabetes tipo 2?"
rol = "medico"      # "paciente" o "medico"
paciente_id = 1       # 1=María González (HTA+DM2), 2=Carlos, 3=Ana
# ---------------------------------------------------------------------------

print(f"\n[{rol}] pregunta: {pregunta}\n")
print("Respuesta del agente:")
print(chatear(app, pregunta, rol=rol, paciente_id=paciente_id))
