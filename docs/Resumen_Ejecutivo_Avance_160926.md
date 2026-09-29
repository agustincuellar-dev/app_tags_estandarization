# Informe integral de avance — 16/09/2026 (miércoles)
## Cierre de Fase 2, revisión independiente y apertura de la propuesta de 9 tags

**Proyecto:** Estandarización ISA-5.1 — Ingenio La Florida  
**Directorio de trabajo:** `AUTOMATISMO_AGUSTIN`  
**Alcance temporal:** actividades realizadas el 16/09/2026  
**Condición operativa:** auditoría estrictamente de solo lectura

---

## 1. Resumen ejecutivo

El 16/09 fue una jornada de **cierre y verificación**, no de construcción de motores. Se cerró el ciclo abierto el 15/09, se sometió lo producido a revisión independiente, se corrigieron los dos defectos que esa revisión encontró, se emitió el informe del 15/09 y se generó la primera propuesta concreta de numeración.

Los seis resultados de la jornada:

1. Se completaron **tres rondas de revisión independiente** sobre los módulos y artefactos del cierre de Fase 2.
2. Esa revisión **detectó dos defectos reales** en `src/frontera_controladores.py`; ambos se corrigieron y se re-verificaron.
3. Se **regeneró y verificó** el paquete completo de exportaciones de cierre.
4. Se emitió el **informe integral del 15/09** en `.md` y `.pdf`.
5. Se generó `exports/propuesta_numeracion_3_lazos.csv` — **9 tags concretos, no insertados**.
6. Se hizo el **traspaso de contexto** a un chat nuevo; en ese chat se revisó la propuesta de 9 tags contra su propia evidencia y **aparecieron 4 discrepancias** (§ 8).

Durante toda la jornada:

- no se escribió en SQLite;
- no se insertaron, actualizaron ni eliminaron registros;
- no se ejecutaron migraciones ni purgas;
- **no se asignó ningún número ISA definitivo**;
- los 11 tags manuales permanecieron protegidos.

---

## 2. Revisión independiente del día

Se ejecutaron cuatro sesiones de revisión separadas del agente de trabajo, todas de solo lectura y sin edición.

| Hora | Objeto revisado | Veredicto |
|---|---|---|
| 08:48 – 08:50 | Seguridad y lógica de `src/propuesta_historica_lazos.py` y su test | **Aprobado** (`passed: true`) |
| 08:55 – 08:58 | Delta de `src/frontera_controladores.py` | **Rechazado** (`passed: false`) — 2 errores de lógica |
| 09:00 – 09:05 | Re-verificación de los dos fixes aplicados | **Aprobado** (`passed: true`) |
| 09:30 – 09:33 | CSV `propuesta_numeracion_3_lazos.csv` (9 tags) | **SIN VEREDICTO** |

### 2.1 Revisión de la numeración histórica (08:48)

Aprobada sin editar ni ejecutar escrituras. Confirmó que la única conexión SQLite de producción usa URI `mode=ro` con `PRAGMA query_only=ON`, que además compara SHA-256 antes y después y **aborta si cambia una base**, y que la identidad histórica exige scope no vacío, PLC y tipo declarado.

Dejó dos observaciones **no bloqueantes**:

- falta una prueba que rechace explícitamente cualquier URI SQLite sin `mode=ro` (hoy la protección queda cubierta por la implementación, `query_only` y hash, no por una aserción directa);
- las escrituras SQLite de los tests crean exclusivamente una base temporal de fixture: conviene dejar documentada esa excepción para no interpretar «cero escrituras» como prohibición de fixtures temporales.

### 2.2 Revisión del CSV de 9 tags (09:30) — sin veredicto

La sesión revisó el CSV recién generado pero **terminó sin respuesta final**: quedó en llamadas de herramienta y no emitió conclusión. Coincide con la nota del traspaso de contexto, que consigna el fallo del revisor por límite de uso (`HTTP 429`).

**Consecuencia que se declara explícitamente: la propuesta de 9 tags NO tiene firma de revisor independiente.** Las verificaciones que la respaldan son del agente principal (§ 8).

---

## 3. Defectos detectados y corregidos

La revisión DELTA de las 08:55 rechazó el módulo de frontera con dos errores concretos:

**Defecto 1 — reclasificación incompleta (`src/frontera_controladores.py:463-471`).**  
El código cambiaba `Motivo_Bloqueo` a `EXTREMO_COMPARTIDO` sin actualizar `Submotivo_Bloqueo` ni `Detalle_Bloqueo`. Las **6 filas** afectadas conservaban submotivo y detalle de la causa anterior, de modo que `resumen_frontera_por_causa.csv` atribuía `EXTREMO_COMPARTIDO` a `CAMINO_COMPLETO_NO_APROBADO`, `PIN_SIN_CONEXION` o `INSTRUCCION_LADDER_NO_SOPORTADA`, y `Detalle_Bloqueo` no mostraba la evidencia del extremo compartido.

**Defecto 2 — techo por causa sobrestimado (`src/frontera_controladores.py:489-496`).**  
El cálculo del techo por causa no exigía que esa causa fuese el **único** tipo de bloqueo, a diferencia del cálculo conservador por motivo. Las discrepancias materiales registradas fueron:

| Causa | Techo informado (incorrecto) | Techo correcto |
|---|---:|---:|
| `ALIAS_NO_RESUELTO` | 33 | 0 |
| `INSTRUCCION_LADDER_NO_SOPORTADA` | 3 | 0 |
| `MIEMBRO_UDT_NO_RESUELTO` | 6 | 0 |
| `AOI_ENVOLTORIO` | 11 | 10 |

Ambos defectos inflaban el impacto atribuible a cada mejora futura, es decir, **el pronóstico de cierre era optimista por construcción**.

### 3.1 Re-verificación posterior (09:00 – 09:05) — aprobada

- Las 6 filas `EXTREMO_COMPARTIDO` quedaron con `Motivo_Bloqueo` **y** `Submotivo_Bloqueo` iguales a `EXTREMO_COMPARTIDO`, con detalles concretos de los extremos y propietarios compartidos.
- Los techos por causa **suman exactamente** los techos por motivo: `AOI_ENVOLTORIO` = 10, `TAG_INTERMEDIO_SIN_LECTOR` = 1, el resto = 0.
- El código exige una sola mitad alcanzada y un conjunto de bloqueadores exactamente igual a `{motivo}`.
- Los textos de consistencia interpolan las métricas calculadas: 213 declaraciones, 145 invocaciones y 6 definiciones AOI no alcanzadas.
- Prueba dirigida: 2/2. Suite general: **77 pruebas OK** y 2 errores de importación por ausencia de `ttkbootstrap` en ese entorno, ajenos a los fixes.

> **Conciliación con el día de hoy:** ejecutada con el intérprete Python 3.13 (que sí tiene `ttkbootstrap`), la suite completa da **85 tests OK**. Los 77 aprobados de la revisión más los módulos que entonces no pudieron importarse explican la diferencia.

---

## 4. Paquete de exportaciones regenerado y verificado

Todas las cifras fueron recontadas sobre los archivos en disco.

| Archivo | Filas | Observación |
|---|---:|---|
| `exports/reconciliacion_catalogo_isa_v3.csv` | 973 | SHA-256 `01e488c2d771af6c…` |
| `exports/frontera_210_controladores.csv` | 210 | 213 declaraciones − 3 aprobadas |
| `exports/frontera_controladores_con_invocacion_xml.csv` | 142 | invocación XML demostrada |
| `exports/declaraciones_controlador_sin_invocacion.csv` | 68 | sin invocación |
| `exports/verificacion_determinismo_cierre.csv` | 14 | artefactos byte-idénticos con semillas 11 y 97 |
| `exports/registro_global_ocupacion.csv` | — | ocupación global |
| `exports/evidencia_historica_9_identidades.csv` | 9 | trazabilidad histórica |
| `exports/cobertura_tablas_historicas.csv` | 16 | 8 tablas × 2 fuentes |
| `exports/consistencia_213_pid.csv` | 7 | 213 / 145 / 68 / 32 / 6 |
| `exports/resumen_frontera_por_causa.csv` | 12 | post-fix |
| `exports/resumen_frontera_por_motivo.csv` | 10 | post-fix |
| `exports/metricas_frontera.csv` | 18 | métricas de frontera |
| `exports/verificacion_final_solo_lectura.json` | — | `escrituras_sqlite: 0`, `tests: 85 OK` |

### 4.1 Acciones del catálogo reconciliado

```text
SIN_LAZO                578
REVISION_LAZO           271
REVISION_MANUAL          99
CONSERVAR_SIN_CAMBIOS    11
CANDIDATO_PID             8
CANDIDATO_ENTRADA         3
CANDIDATO_SALIDA          3
                      ----
                       973
```

Siguen **eliminadas por completo** las acciones operativas `AGREGAR_CON_LAZO` y `RENUMERAR_CON_LAZO`, y el CSV sigue sin columna `Tag_Propuesto_ISA`.

### 4.2 Frontera de los 210 controladores incompletos

Distribución por motivo de bloqueo (post-fix):

| Motivo | Afectados |
|---|---:|
| `OTRO_CON_EVIDENCIA` | 93 |
| `ALIAS_NO_RESUELTO` | 44 |
| `PIN_SIN_CONEXION` | 28 |
| `AOI_ENVOLTORIO` | 15 |
| `INSTRUCCION_LADDER_NO_SOPORTADA` | 11 |
| `MIEMBRO_UDT_NO_RESUELTO` | 10 |
| `EXTREMO_COMPARTIDO` | 6 |
| `MULTIPLES_ESCRITORES` | 1 |
| `TAG_INTERMEDIO_SIN_LECTOR` | 1 |
| `TAG_INTERMEDIO_SIN_ESCRITOR` | 1 |

Prioridades legado: **1** = 38 (PID–salida), **2** = 2 (entrada–PID), **3** = 0, **4** = 170.  
Techos condicionales vigentes: `AOI_ENVOLTORIO` = 10 y `TAG_INTERMEDIO_SIN_LECTOR` = 1. **Cierres garantizados: 0.** Los techos son condicionales, nunca pronósticos.

---

## 5. Informe del 15/09 emitido

A las 09:14 se emitió el informe integral del 15/09 en los tres formatos de la casa:

```text
docs/Resumen_Ejecutivo_Avance_150926.md          13.939 bytes
docs/Resumen_Ejecutivo_Avance_150926.pdf         10 páginas (verificado)
docs/Resumen_Ejecutivo_Avance_150926_portada.png
```

---

## 6. Propuesta concreta de 9 tags (generada 09:29)

**Archivo:** `exports/propuesta_numeracion_3_lazos.csv` — 10.064 bytes  
**SHA-256:** `8c3ae8da184ee821c413a02e9d173d75ecf6b1c9263f4d80f7579458f3910235`  
**Estructura:** 9 filas × 29 columnas, delimitado por `;`, con BOM.

| # | Rol | Identidad actual | Área | Var | Nº | Tag propuesto |
|---|---|---|---|---|---|---|
| 1 | ENTRADA | `DES_S1_LT_TK_DESAIREADOR` | 300 | L | 083 | `300_LT_083` |
| 2 | CONTROLADOR | `B_DES_LC_DOMO` | 300 | L | 083 | `300_LIC_083` |
| 3 | SALIDA | `DES_S6_PV_VALVULA_EVACUACION_DES` | 300 | L | 083 | `300_LV_083` |
| 4 | ENTRADA | `Slot_FT_AGUA` | 200 | F | 081 | `200_FT_081` |
| 5 | CONTROLADOR | `B_Ctrol_FT_AGUA_A_MOSTO` | 200 | F | 081 | `200_FIC_081` |
| 6 | SALIDA | `Slot_PV_VALVULA_CAUDAL_AGUA` | 200 | F | 081 | `200_FV_081` |
| 7 | ENTRADA | `Slot_LT_TK_AGUA_POTABLE` | 200 | L | 082 | `200_LT_082` |
| 8 | CONTROLADOR | `B_Ctrol_TK_AGUA_POTABLE` | 200 | L | 082 | `200_LIC_082` |
| 9 | SALIDA | `Slot_PV_VALVULA_NIVEL_TK_AGUA` | 200 | L | 082 | `200_LV_082` |

Las 9 filas llevan `Estado_Propuesta = PROPUESTA_CONCRETA_PARA_REVISION — NO_INSERTAR` y `Escritura_SQLite = NO`.

---

## 7. Traspaso de contexto (10:24)

Se cerró el chat de trabajo largo (394 mensajes, iniciado el 03/09) y se preparó el traspaso:

```text
docs/Contexto_Handoff_160926.md          15.404 bytes
docs/Prompt_Continuacion_160926.txt       3.617 bytes
```

El contexto de traspaso contiene reglas permanentes, entorno e intérprete correcto, estado de las bases con hashes, los 3 lazos aprobados con rutas XML y `AliasFor`, la propuesta de 9 tags con su SHA-256, las verificaciones, las limitaciones declaradas, la colisión de nombre de archivo con `src/propuesta_historica_lazos.py`, los hallazgos 213/145/68 y 32/6, la frontera de 210 con sus causas y la disciplina de verificación.

**Advertencia registrada:** `src/propuesta_historica_lazos.py` escribe ese **mismo nombre de archivo** con otro esquema. Ejecutarlo sobrescribe la propuesta de 9 tags. El CSV debe resguardarse antes de correrlo.

---

## 8. Revisión de la propuesta en el chat nuevo (10:38 – 10:44)

En el chat nuevo se re-verificó la propuesta de 9 tags contra su propia evidencia, sin tocar bases ni el CSV. **Lo que pasó:**

| Verificación | Resultado |
|---|---|
| Área 300 del desaireador (3 documentos, línea a línea) | ✅ confirmada |
| Los 3 lazos cierran (traza de `Wire` en el FBD) | ✅ completa |
| Controladores con `DataType="CONTROL_NIVEL"` | ✅ los 3, incluido el de caudal |
| `AliasFor` de entradas y salidas vs. el CSV | ✅ coinciden los 6 |
| Números 083/081/082 libres (5 universos, incl. los 10 L5X) | ✅ libres |
| Coincidencias históricas de las 4 identidades | ✅ existen con los alias citados |
| SHA-256 de ambas bases | ✅ sin cambios |

### 8.1 Cuatro discrepancias encontradas (no corregidas en silencio)

**P1 — Citas de fila no reproducibles.** El CSV cita `PLCs fila 3` y `Programas fila 18` (desaireador) y `Programas fila 14` (destilería). Real: la hoja `PLCs` del desaireador tiene 2 filas y el PLC está en la **fila 2**; `Programas` tiene 7 filas y el programa `DES` está en la **fila 6**; en destilería `Programas` tiene 4 filas y `FERMENTACION` está en la **fila 3**. La sustancia se sostiene, la referencia no.

**P2 — La columna de números vigentes no sale de la fuente que cita.** Área 300 declara `001-016|020|081|106`: en la hoja `Tags` de `.195/.196` los tokens `020` y `081` tienen **0 coincidencias** y `106` aparece solo dentro de `Program:C10.B_ST_DOSIFICADOR_1_CALD106` (código de equipo). La extracción ISA-like de esa hoja da `001-022, 025, 026`. Área 200 declara `001-009|011-015|101-109|201-210|601`: la fuente entrega 001-033, 036-051, 056-070, 086, 101-109, 111, 115, 121, 201-210, 215, y el `601` proviene de `BBA_VINO_A_JW_601B` (equipo). La lista está incompleta **y** con tokens mal atribuidos; la conclusión (083/081/082 libres) no cambia, pero esa columna no es evidencia reproducible como está escrita.

**P3 — `200_FT_082` está mal clasificado.** El CSV lo llama «histórico retirado» citando `Resumen_Ejecutivo_Avance_280826.md:123`. La línea 123 real es `| FT_VINO_A_JW_ACUM_HR_ACT | 200_FT_082 | ~~200_FT_079~~ |`: **200_FT_082 está en la columna «Conservar»**, no en Eliminar. (Para 081 la cita sí es correcta: línea 125, `~~200_FT_081~~` en Eliminar.) Hoy 082 no está ocupado — no está en la base de 11, ni en el backup de 693, ni en `DESTILERIA.L5X` — pero por la regla 8 (un número retirado no se recicla) y por el propio registro del proyecto, **082 es el más débil de los tres números**. Dato adicional: 082/083/084 se asignaron a acumulados/derivados (`FT_VINO_A_JW_ACUM_*`), y la línea 108-109 del mismo informe establece que los derivados no llevan tag numerado.

**P4 — La entrada no está cableada directo al controlador (en los 3 lazos).** Los `Wire` reales muestran que el pin `PV` recibe un tag **interno**, no el alias de campo:

| Lazo | Pin `PV` recibe | El CSV propone como ENTRADA |
|---|---|---|
| Desaireador | `DES_LT_TK_DESAIREADOR` (Base REAL) | `DES_S1_LT_TK_DESAIREADOR` |
| Agua a mosto | `FT_AGUA` (Base REAL) | `Slot_FT_AGUA` |
| Agua potable | `LT_TK_AGUA_POTABLE` (Base REAL) | `Slot_LT_TK_AGUA_POTABLE` |

El camino real es **alias de campo → bloque `SCL` → tag interno REAL → pin `PV` → `MV` → alias de salida**, y se verificó completo (`IRef` del alias → `In` del `SCL` → `Out` → `ORef` interno). Los lazos sí cierran y la identidad de campo propuesta es la correcta; lo que falta es que el CSV declare el tag intermedio — la categoría que el reconciliador ya denomina `TAG_INTERMEDIO_SIN_LECTOR` / `ALIAS_NO_RESUELTO`.

Detalle adicional del lazo de agua potable: `ACCION_CTRL_DIREC1_INVER0` está cableado a `0` (en los otros dos vale `1`), y en esa misma hoja hay un `IRef LT_CUBA_1` declarado **sin cable** al bloque.

---

## 9. Estado de la propuesta al cierre del 16/09

- La propuesta de 9 tags existe, está verificada y **no está insertada**.
- **No se asignó ningún número ISA definitivo.**
- **No hay firma de revisión independiente** sobre el CSV de 9 tags.
- Las verificaciones de respaldo son del agente principal, con las cuatro salvedades de § 8.1.

---

## 10. Disciplina de verificación aplicada

| Control | Resultado |
|---|---|
| Suite completa (Python 3.13, `-W error::ResourceWarning`) | **85 tests OK** |
| `python.exe -m compileall -q src tests` | OK |
| `git diff --check` | OK |
| SHA-256 de ambas bases antes y después | sin cambios |
| `PRAGMA integrity_check` en ambas | `ok` |
| Generación con `PYTHONHASHSEED=11` y `97` | 14 artefactos byte-idénticos |
| Escrituras SQLite | **0** |

Hashes de cierre:

```text
app_etiquetas/tags_ingenio.db                           c450eb3f017a7f51636aaca8df5194f9385b084f05a6ac0450902738c384ca17  (11 tags)
app_etiquetas/backups/...antes_purga_20260911...db      ee1df1c901f254bd1a97785a709f3ee154c0ac0503657866d536d1325778c440  (693 tags)
exports/propuesta_numeracion_3_lazos.csv                8c3ae8da184ee821c413a02e9d173d75ecf6b1c9263f4d80f7579458f3910235  (9 filas)
exports/reconciliacion_catalogo_isa_v3.csv              01e488c2d771af6c9da38fa89c5ff422e2f2b8c6d1f2c62da82b5cbde8f12616  (973 filas)
```

---

## 11. Pendientes abiertos

1. **Decisión sobre los 9 tags.** Nada se inserta sin autorización expresa.
2. **`200_FT_082` en revisión (P3).** Sostener el 082 o reasignar el lazo de agua potable.
3. **Corregir el CSV vigente (P1, P2, P4).** Citas de fila, lista de números vigentes y columna del tag intermedio.
4. **Firma independiente de la propuesta.** El intento del 16/09 quedó sin veredicto.
5. **Los 210 controladores incompletos.** Mejoras de mayor techo: `AOI_ENVOLTORIO` (10) y `TAG_INTERMEDIO_SIN_LECTOR` (1).
6. **Numeración masiva pendiente** para los grupos restantes, cuando se autorice.

---

## 12. Archivos creados o actualizados el 16/09

### Exportaciones

```text
exports/reconciliacion_catalogo_isa_v3.csv
exports/frontera_210_controladores.csv
exports/frontera_controladores_con_invocacion_xml.csv
exports/declaraciones_controlador_sin_invocacion.csv
exports/consistencia_213_pid.csv
exports/resumen_frontera_por_causa.csv
exports/resumen_frontera_por_motivo.csv
exports/metricas_frontera.csv
exports/registro_global_ocupacion.csv
exports/evidencia_historica_9_identidades.csv
exports/cobertura_tablas_historicas.csv
exports/definiciones_controladores_xml.csv
exports/inventario_controladores_xml.csv
exports/verificacion_determinismo_cierre.csv
exports/verificacion_bases_solo_lectura.csv
exports/verificacion_final_solo_lectura.json
exports/propuesta_numeracion_3_lazos.csv          ← propuesta vigente
```

### Documentación

```text
docs/Resumen_Ejecutivo_Avance_150926.md
docs/Resumen_Ejecutivo_Avance_150926.pdf
docs/Resumen_Ejecutivo_Avance_150926_portada.png
docs/Contexto_Handoff_160926.md
docs/Prompt_Continuacion_160926.txt
```

### Código corregido

```text
src/frontera_controladores.py    defectos 1 y 2 corregidos y re-verificados
```

---

Informe generado el 17/09/2026 a las 09:09 — corresponde a las actividades del 16/09/2026. Toda la jornada se ejecutó en modo solo lectura.
