# Protocolo para solicitud de receta
descripcion: Cómo tomar correctamente una solicitud de receta del paciente y dejarla pendiente de aprobación médica.

## Cuándo usar
Cuando el paciente quiere pedir una receta (renovación de medicación crónica o similar).

## Cómo actuar
1. Confirmá QUÉ medicamento necesita. Si el paciente no está seguro del nombre o la
   dosis, ofrecé revisar su medicación actual (mirá sus datos con su paciente_id).
2. Pedí y confirmá los 3 datos: medicamento, dosis y cantidad de envases.
3. Preguntá a QUÉ médico va dirigida la receta (mostrá las opciones con `listar_medicos`,
   o usá el médico de su último turno).
4. Antes de crear la solicitud, repetí los datos + el médico y pedí confirmación explícita.
5. Recién ahí usá la tool `solicitar_receta` (con el medico_id). La solicitud queda PENDIENTE.
5. Dejá MUY claro que la receta NO está aprobada todavía: el médico la tiene que revisar
   y aprobar. Nunca digas que ya puede retirarla.
6. Si el medicamento pedido no coincide con la medicación registrada del paciente,
   marcalo con cuidado y sugerí que lo consulte con el médico.
