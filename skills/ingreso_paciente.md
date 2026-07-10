# Ingreso y sacar turno
descripcion: Flujo para sacar un turno, distinguiendo si el paciente ya existe o es su primera vez (ingreso de datos). Cubre la elección de médico.

## Cuándo usar
Cuando el paciente quiere sacar un turno, o dice que es su primera vez en el centro.

## Cómo actuar (en orden)
1. **Identificá al paciente**: pedí el DNI y buscalo con `buscar_paciente`.
2. **Si NO está registrado (primera vez)**:
   - Avisá que primero hay que registrarlo y pedí los datos filiatorios: nombre, apellido,
     DNI, fecha de nacimiento (YYYY-MM-DD), teléfono, email, obra social, **PLAN** y número
     de afiliado.
   - Pedí también **patologías previas** y **medicación actual** (si tiene).
   - Confirmá los datos y registralo con `registrar_paciente`.
3. Preguntá el **motivo** de la consulta.
4. Preguntá **con qué médico** se quiere atender. Mostrá las opciones con `listar_medicos`.
5. Consultá los horarios libres con `consultar_agenda` (fecha + medico_id).
6. **Confirmá** fecha, hora, médico y motivo con el paciente ANTES de reservar.
7. Reservá con `sacar_turno`. Informá el turno confirmado (fecha, hora y médico).

## Recordá
- No inventes datos: si falta un dato para registrar o reservar, pedilo.
- El paciente elige el médico; si no sabe, mostrale la lista y sugerí según el motivo.
