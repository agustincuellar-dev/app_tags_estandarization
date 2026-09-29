# Resumen ejecutivo de avance — 21/09/2026

**Proyecto:** Estandarización ISA-5.1 — Ingenio La Florida  
**Directorio:** `C:\Users\Administrador\Downloads\AUTOMATISMO_AGUSTIN`  
**Jornada cubierta:** lunes 21/09/2026  
**Condición operativa:** auditoría y generación de propuestas; SQLite de producción preservada según la autorización puntual de cada operación.

> Este informe cubre exclusivamente la jornada del 21/09/2026. Fue reconstruido el 22/09 desde el registro primario de Hermes y desde los artefactos existentes en disco; no se tomó el handoff como fuente única.

## 1. Resumen ejecutivo

La jornada tuvo una sesión efectiva de **07:25:34 a 12:18:27**, con **1.173 registros** en Hermes: 17 mensajes de usuario, 558 mensajes de asistente y 598 resultados de herramientas. Después de deduplicar mensajes espejo, quedaron **7 solicitudes sustantivas**:

1. Generar el informe correspondiente al viernes 18/09.
2. Incorporar `XV` a la lectura humana de la aplicación.
3. Ejecutar las dos olas autorizadas de alta masiva.
4. Unificar procedencia, ampliar el detalle de la app y corregir la exportación Excel.
5. Restaurar el CSV v3 y verificarlo contra producción.
6. Agregar la columna `PLC` a Búsqueda Expandida.
7. Ejecutar el sprint de frontera v4.

El resultado técnico de cierre de la jornada fue:

- Producción con **119 tags**, `integrity_check=ok` y SHA-256 `2c25c9b76df5ce00027e073597ea297d5844970ed1c9936aee411aaa277d501b`.
- Backup histórico de 693 tags sin cambio: SHA-256 `ee1df1c901f254bd1a97785a709f3ee154c0ac0503657866d536d1325778c440`.
- Propuesta v3 restaurada y consistente con producción: 99 tags, 33 lazos.
- Propuesta v4 generada en archivos separados: 105 tags, 35 lazos.
- El sprint v4 bajó el bloqueo post-filtro de 177 a **175** y el trazador crudo elevó `CERRABLE_HOY` de 33 a **55**.
- No se ejecutó ningún `--apply` durante el sprint v4 ni se modificó SQLite en esa fase.

## 2. Alta masiva autorizada

El usuario autorizó explícitamente la inserción de los 99 tags de v3 en dos olas.

| Ola | Áreas | Resultado |
|---|---|---:|
| 1 | 200 y 300 | 20 → 59 tags |
| 2 | 100, 500, 600 y 700 | 59 → 119 tags |

Las verificaciones posteriores confirmaron:

- 119 tags en producción.
- Los 20 tags anteriores intactos.
- `integrity_check=ok`.
- Catálogo `XV` preexistente sin filas duplicadas.
- Auditorías de alta presentes con procedencia.
- Backup histórico de 693 tags sin cambio.

Esta fue la única escritura de producción mencionada en la jornada y contó con autorización explícita del usuario.

## 3. Corrección de procedencia y restauración del CSV

Se aplicó la corrección autorizada sobre los 99 tags masivos:

- Descripción unificada con `Migrado de:`.
- 12 salidas `CANAL_CRUDO` con aclaración explícita de que escriben directo al canal y no tienen tag de campo.
- Backup byte-idéntico antes de la actualización.
- Auditoría por cada re-redacción.
- Restauración posterior del CSV desde `propuesta_numeracion_masiva_180926_v3_pre_redaccion.csv`.

Verificación final del CSV restaurado y reaplicado:

- 99/99 tags presentes en producción.
- 99/99 números coincidentes.
- 99/99 descripciones idénticas a la base, byte a byte.
- `Estado_Propuesta` y `Escritura_SQLite` preservados.
- SHA final del CSV canónico: `aae1f99858a2f4062a4f7f32a76088966a28241d132ed69e6940dac85fa97a74`.

## 4. Aplicación y exportación

### 4.1 Lectura humana

Se agregó `MAPEO_FUNCIONES["XV"] = "Válvula Todo/Nada"` y se fijó mediante pruebas la lectura de:

- `500_LXV_008` como válvula todo/nada de nivel.
- `700_PXV_008` como válvula todo/nada de presión.

### 4.2 Búsqueda Expandida

La tabla incorporó `PLC` inmediatamente después de `Estado`. La resolución se verificó contra el inventario real:

| `plc_origen` | Celda mostrada |
|---|---|
| `DESTILERIA` | `10.128` |
| `FABRICA` | `10.118 / 10.119` |
| `Calderas_8_9_10_Desaireador` | `10.195 / 10.196` |
| `TRAPICHE2022` | `10.99` |
| sin PLC | `—` |

La base tenía 119 tags y no quedó ningún `plc_origen` sin resolver entre los valores presentes.

### 4.3 Excel y detalle del tag

Se consolidó el exportador Excel para búsqueda rápida y expandida:

- Banner amarillo combinado en fila 1.
- Encabezado en fila 3.
- Datos desde fila 4.
- `freeze_panes=A4`.
- Columna `Tag_Studio5000` amarilla completa.
- El detalle del tag muestra `Procedencia (Migrado de):` o `—`.

## 5. Sprint de frontera v4

### 5.1 FASE 1 — Envoltorios AOI

Se creó `src/envoltorios_l5x.py`, que parsea:

- Parámetros AOI y su `Usage`.
- Hojas FBD.
- Rungs RLL dentro del CDATA de `<Text>`.
- Líneas ST.
- Camino interno entre pines y ambigüedades.

Se corrigió el corte del trazador en pines como `SALIDA_MV` y `VALOR_SALIDA`, que antes no coincidían con el filtro `MV`/`Out`. Los caminos únicos atraviesan ahora `PROPORCION_AM`, `ALIMENTADOR_BAGAZO` y `LIMITADOR` cuando la evidencia XML lo permite.

`SEL`, `B_SELECTORA` y `Relacao` aparecen como definiciones, pero no se encontraron instancias ejecutables en las hojas analizadas. No se inventaron cierres para ellas.

### 5.2 FASE 2 — Escritores RLL/ST

El trazador extendido indexa escritores en escalera y ST, además de los `ORef` FBD. Esto permitió resolver tags intermedios escritos en otra rutina o programa.

Caso testigo: `DIBACCO/MainProgram/PID/Ctrol_Presion_Escape_Tamiz`, donde el camino incluye `MOV(EA_PIT302_1_actual_Value, PID_14PV)`.

### 5.3 FASE 3 — Gobernanza

Se generó `decisiones_pendientes_v4.csv` con 32 bloqueos clasificados:

| Regla | Casos |
|---|---:|
| R-B | 11 |
| R-C | 10 |
| R-A + R-C | 7 |
| R-A | 2 |
| R-B + R-C | 1 |
| Sin regla aplicable | 1 |

Todas las filas de decisión quedaron como propuestas, con `Requiere_Autorizacion=SI` y `Escritura_SQLite=NO`.

## 6. Métricas v3 → v4

| Métrica | v3 | v4 | Delta |
|---|---:|---:|---:|
| Lazos en propuesta | 33 | 35 | +2 |
| Tags en propuesta | 99 | 105 | +6 |
| `CERRABLE_HOY` post-filtro | 33 | 35 | +2 |
| `CERRABLE_HOY` trazador crudo | 33 | 55 | +22 |
| `BLOQUEADO_ANALIZADOR` | 123 | 113 | -10 |
| `BLOQUEADO_DOCUMENTAL` | 25 | 23 | -2 |
| `BLOQUEADO_EXTREMO_COMPARTIDO` | 21 | 30 | +9 |
| `BLOQUEADO_VARIABLE_AMBIGUA` | 4 | 5 | +1 |
| `BLOQUEADO_AREA_AMBIGUA` | 3 | 2 | -1 |
| `REVISION_ELEMENTO_FINAL` | 1 | 2 | +1 |

La diferencia entre los 55 cierres crudos y los 35 de la propuesta no es un error: los 20 restantes requieren aplicar reglas de gobernanza, resolver identidad funcional o conservar un bloqueo explícito.

## 7. Artefactos principales de la jornada

| Archivo | SHA-256 |
|---|---|
| `exports/propuesta_numeracion_masiva_180926.csv` | `5fffd3726010dfc34820e9170fe0b20822c352fd475086549af95cf534c1ce19` |
| `exports/propuesta_numeracion_masiva_v4_210926.csv` | `64b1194bd674a9833170a5faa92ce078acd58a0f5bd7dfc9334fab3fd43d6c54` |
| `exports/analisis_210_lazos_v4_trazador.csv` | `f063018383e36532a538be4ed2e9fc0f5e11bfd821877984b4d13092aceaa54a` |
| `exports/analisis_210_lazos_v4.csv` | `d53957bf06e6b94d993c6fb42db65232f3579800fb25634aa5d66983c954ec36` |
| `exports/decisiones_pendientes_v4.csv` | `179ec80f0e27a4d5e63bd9438966389ba1e44d16fcf6fd9e810371bc1b16f60e` |
| `exports/resumen_sprint_v4.csv` | `b70e23f49a553736273506f37e904fa588eb1fb536c4b26b9e7a0eeb7d5783ee` |

La frontera derivada del L5X resultó byte-idéntica a la frontera previa; el cambio estuvo en el trazador y en el pase de propuesta.

## 8. Verificación y límites

- 211 tests OK en `tests/`.
- 16 tests OK en `app_etiquetas/`.
- `compileall` OK.
- `git diff --check` OK.
- Determinismo `PYTHONHASHSEED=11/97`: artefactos v4 byte-idénticos.
- Canónicos v3 preservados por hash tras ejecutar el pipeline v4.
- No hubo revisión independiente externa durante esta jornada; el cierre corresponde a pruebas y verificaciones ejecutadas en el propio proyecto.
- La evidencia es XML estático: no demuestra ejecución runtime, estado real de campo ni exclusividad operacional fuera de lo declarado en los archivos.

## 9. Estado al cierre

La base de producción quedó en 119 tags y el paquete v4 quedó preparado para revisión, sin aplicar decisiones R-A/R-B/R-C. Las áreas ambiguas, los elementos finales sin identidad suficiente y los bloqueos sin regla aplicable permanecieron fuera de la propuesta concreta.

La jornada terminó con la numeración v3 protegida por una línea base congelada y con un guardarraíl contra renumeración accidental por documentos que alimentan U5.

**Fuente primaria temporal:** sesión Hermes `20260916_103822_d52f4c`, mensajes del 21/09/2026 entre 07:25:34 y 12:18:27 (-03:00).  
**Condición SQLite al cierre:** producción `2c25c9b7…`, 119 tags, `integrity_check=ok`, sin `-wal`/`-journal`.
