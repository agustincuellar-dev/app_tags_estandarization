# Estrategia para aislar y numerar I/O físico
## Fuente: `exports/reconstruccion_catalogo_isa.csv`

## Estado medido del CSV

El archivo contiene **1.006 filas**:

- 78 `ENTRADA_PROCESO_DESCUBIERTA`.
- 101 `SALIDA_CONTROL_DESCUBIERTA`.
- 25 señales históricas de proceso ya vinculadas a topología: 22 transmisores y 3 válvulas.
- 495 instrumentos históricos localizados en L5X pero todavía sin lazo demostrado.
- 135 controladores reales.
- 58 parámetros internos de PID correctamente excluidos como instrumentos.

Los 179 extremos nuevos son identidades únicas. Forman 112 grupos topológicos: 62 tienen entrada y salida, 31 solo entrada y 19 solo salida. Solo 73 grupos tienen área y variable completas; únicamente 2 grupos de extremos quedaron íntegramente en confianza ALTA. En 96 de las 101 salidas todavía falta demostrar la función ISA final.

El CSV fue generado antes de liberar `200_PT_004`; su fila `CONSERVAR_SIN_CAMBIOS` debe considerarse obsoleta. Antes de producir propuestas finales deberá regenerarse la reconciliación en modo read-only contra la base actual de 11 tags.

Una regeneración de verificación hacia un archivo temporal confirmó que el total permanece en 1.006 filas: los protegidos bajan de 12 a 11 y `VALIDAR_INSTRUMENTO_SIN_LAZO` sube de 495 a 496. Ambas bases conservaron exactamente sus hashes durante esa ejecución.

## Límite actual del código integrado

La actualización amplía de forma importante la detección de controladores AOI dentro de FBD usando definiciones y dirección de pines. Sin embargo, `parsear_topologia_l5x()` todavía construye el grafo ejecutable únicamente desde `FBDContent/Sheet`: Ladder y Structured Text no están incorporados aún al trazado de datos. Por eso los 1.006 registros son una base de reconciliación mejorada, pero no una demostración completa de todos los vínculos físicos. La estrategia siguiente incluye explícitamente esas dos representaciones antes de autorizar numeración masiva.

La revisión independiente detectó además tres bloqueos para usar el CSV como fuente automática de numeración:

**Veredicto:** la capa de acceso es read-only y no migra ni purga, pero la integración operativa automática queda **NO APROBADA** hasta resolver la preservación de incertidumbre.

1. `Encontrado_L5X` se calcula actualmente por subcadena (`raw in file_text`), no por identidad XML/token exacto.
2. La confianza puede subir a MEDIA por tener una sola PV aunque existan ciclos, múltiples escritores o un actuador dudoso.
3. Filas relacionadas con lazos problemáticos todavía pueden recibir `AGREGAR_CON_LAZO` o `RENUMERAR_CON_LAZO`.
4. Una combinación MEDIA + BAJA se resume actualmente como MEDIA; debe conservarse el peor nivel, BAJA.
5. Un tag local puede proteger un grupo mediante su nombre sin scope; debe exigirse `Program:<scope>.<tag>` o un alias scoped inequívoco.
6. La detección dinámica todavía filtra AOI por nombres CONTROL/CTRL/PID/PIDE y pines PV/MV/CVEU/CV/OUT; una salida `OUT` no demuestra por sí sola un mando de proceso.

Por lo tanto, esas acciones se interpretarán solamente como candidatos de revisión hasta implementar confianza individual por vínculo. No deben importarse ni numerarse automáticamente.

## Principio rector

Separar dos decisiones que antes estaban mezcladas:

1. **¿La identidad es un I/O físico?**
2. **¿A qué lazo pertenece y qué número comparte?**

Una identidad puede quedar confirmada como entrada o salida aunque el PID intermedio sea ambiguo. Esa clasificación no autoriza por sí sola a asignarle un número independiente.

## Pipeline propuesto

### 1. Construir un índice de identidades por PLC y scope

Clave estable:

```text
PLC + Program + Routine + Scope + operando base + AliasFor/dirección I/O
```

Indexar declaraciones y referencias en:

- FBD: `IRef`, `ORef`, `Wire`, bloques y llamadas AOI.
- Ladder: operandos leídos/escritos por instrucción y por renglón.
- Structured Text: lecturas, asignaciones y llamadas.
- AOI: instancia ejecutada más dirección declarada de cada pin.
- Alias y miembros UDT: conservar identidad base y ruta completa.

No usar coincidencias por substring como prueba de identidad.

### 2. Confirmar físicamente cada extremo, de forma independiente

#### Entrada / sensor

Exigir al menos una evidencia física fuerte:

- alias o dirección de módulo de entrada;
- canal analógico/discreto declarado como entrada;
- primera variable en unidades de ingeniería después de un bloque de escalado;
- uso como PV sin pasar por acumuladores, promedios, SP, simulaciones o derivados.

La variable ISA debe provenir de evidencia del canal, nombre inequívoco, descripción o unidad. Si las fuentes discrepan, conservar `Variable=''` y enviar a revisión.

#### Salida / elemento final

Exigir:

- alias o dirección de módulo de salida, o escritura final única hacia el dispositivo;
- dirección de pin AOI demostrada como `Output`;
- trazabilidad desde un mando hasta el canal o UDT de equipo.

Clasificar por separado:

- `VALVULA_CONTROL`: candidata a función `V`.
- `VALVULA_ON_OFF`: candidata a `XV`, solo con evidencia discreta/semántica.
- `MOTOR_VDF` o `MOTOR_ARRANQUE`: elemento final físico relacionado con el lazo, pero no convertirlo automáticamente en una función ISA inexistente. Debe conservar vínculo de lazo y usar la convención de equipo aprobada por Ingeniería.
- `SALIDA_FISICA_TIPO_PENDIENTE`: salida confirmada, función sin demostrar.

### 3. Construir relaciones sin exigir un PID perfecto

Modelar el programa como grafo dirigido de lecturas y escrituras. Un PID/AOI ambiguo puede actuar como nodo opaco si están demostrados sus pines de entrada y salida.

Crear evidencias independientes:

```text
Entrada física -> acondicionamiento -> pin de proceso
pin de mando -> acondicionamiento -> salida física
```

La confianza del extremo físico y la confianza del vínculo al lazo deben ser campos separados. No bajar la clasificación física de una entrada segura porque haya selector, cascada o múltiples salidas más adelante.

### 4. Asignar confianza por vínculo individual

| Nivel | Condiciones mínimas | Acción |
|---|---|---|
| ALTA | Identidad física exacta, área y variable únicas, un solo componente topológico, vínculo uno-a-uno y sin escritores alternativos | Puede recibir propuesta de lazo |
| MEDIA | Extremo físico confirmado, pero existe selector, cascada, cruce de rutina o tipo de salida pendiente | Clasificar I/O; no numerar todavía |
| BAJA | Dirección o rol inferido, varias rutas, área/variable ausente o múltiples escritores | Revisión manual |

La confianza se asigna a cada relación `origen -> destino`, no al PID completo.

### 5. Formar familias antes de numerar

Una familia numerable debe cumplir:

- área conocida;
- variable de proceso conocida;
- componente topológico único;
- al menos una entrada física inequívoca;
- cada salida incluida debe estar demostrada como elemento final del mismo componente;
- ninguna identidad puede pertenecer simultáneamente a dos familias;
- sin escritores alternativos no resueltos.

Si una entrada segura no tiene salida demostrada, se conserva como instrumento físico pendiente de agrupación. No recibe un número autónomo hasta demostrar que es independiente o confirmar su familia.

### 6. Asignar números en una sola corrida global

- Cargar la base actual en `mode=ro` y `PRAGMA query_only=ON`.
- Reservar los 11 tags manuales restantes y sus combinaciones área + variable + número.
- Usar el backup de 693 únicamente como inventario/procedencia, nunca como verdad de numeración.
- Ordenar familias por una clave determinista de PLC/scope.
- Reservar números solo en memoria.
- Todos los integrantes de una familia comparten `Área + Variable + Número`.
- No escribir en SQLite.

### 7. Salida de revisión

Generar un nuevo CSV de propuestas, sin importación automática, con:

```text
PLC_Origen
Scope
Tag_Original_PLC
Rol_IO
Evidencia_Fisica
Area
Variable
Tipo_Elemento_Final
Lazo_Candidato
Confianza_Fisica
Confianza_Vinculo
Tag_Propuesto_ISA
Estado
Motivo
```

Estados recomendados:

- `PROPUESTA_IO_ALTA`
- `IO_CONFIRMADO_LAZO_PENDIENTE`
- `SALIDA_TIPO_PENDIENTE`
- `MULTIPLES_LAZOS`
- `REVISION_MANUAL`

## Primera ola recomendada

1. Procesar primero los **2 grupos** cuyos extremos rescatados son íntegramente ALTA.
2. Revisar los **62 grupos** con entrada y salida para separar vínculos uno-a-uno de selectores/cascadas.
3. Resolver función y naturaleza física de las salidas: hoy **96 de 101** no tienen función ISA demostrada.
4. Mantener sin número las **495 señales** localizadas pero sin lazo.
5. Regenerar la reconciliación read-only después de la liberación de `200_PT_004`.
6. Someter el CSV resultante a aprobación antes de cualquier migración.
