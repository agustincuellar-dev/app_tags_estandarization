# Informe integral de avance — 18/09/2026 (viernes)
## Alta autorizada de los 9 tags, sprint de numeración masiva y paquete listo para inserción

**Proyecto:** Estandarización ISA-5.1 — Ingenio La Florida  
**Directorio de trabajo:** `AUTOMATISMO_AGUSTIN`  
**Alcance temporal:** actividades del 18/09/2026, de 09:37 a 12:27 (hora local)  
**Condición operativa:** solo lectura sobre SQLite, con **una única escritura autorizada** (§4)  
**Fuente de la reconstrucción:** `state.db` de Hermes (sesión `20260916_103822_d52f4c`, 470 mensajes del día) + mtime de los artefactos

---

## 1. Resumen ejecutivo

El viernes 18/09 fue la jornada más productiva del proyecto: **se pasó de 9 a 99 tags candidatos trazados** (11× el objetivo planteado a la mañana) y se dejó el paquete listo para inserción en dos olas, sin tocar la base de producción fuera de la escritura expresamente autorizada.

Los siete resultados de la jornada:

1. **Se sanéo la propuesta de 9 tags** (P1/P2/P4) con un módulo determinístico nuevo de ocupación; el CSV quedó en v2 (`4137bbce…`) y luego v2.1 (`c40ec1f3…`).
2. **Se ejecutó la única escritura del proyecto**: el alta autorizada de los 9 tags aprobados, **11 → 20 tags**, con verificación completa y trazabilidad `Migrado de <identidad PLC>`.
3. **Se atacaron los 40 lazos "casi listos"** con un motor nuevo (`src/trazador_lazos_profundo.py`): **32 cerrables**, cuando antes cerraban 0.
4. **Se generó la propuesta masiva**: `exports/propuesta_numeracion_masiva_180926.csv` — **37 lazos / 111 tags** candidatos, con evidencia XML completa y **cero inserciones**.
5. **Se corrió el pase de corrección determinístico (R1–R7)** sobre esa propuesta: quedó en **33 lazos / 99 tags** (`1b7894ad…`), con 11 variables corregidas y 4 lazos retirados con causa.
6. **Se aplicaron las decisiones confirmadas A y B y la regla R8** → v3 del entregable (`0729eac9…`): convención XV, `Digital`/`Analógico` correcto y 12 salidas declaradas `CANAL_CRUDO:<dirección>`.
7. **Se construyó y validó el inserter por olas** (`src/insertar_propuesta_masiva.py`), con **dry-run de las dos olas mostrado completo** y prueba end-to-end sobre una copia de la base: ola 1 → 59 tags, ola 2 → 119 tags.

Durante toda la jornada, **fuera del paso 2**:

- no se escribió en SQLite;
- no se insertaron, actualizaron ni eliminaron registros;
- no se ejecutaron migraciones ni purgas;
- **no se asignó ningún número ISA definitivo** (todos son candidatos `NO_INSERTAR`);
- los 11 tags manuales permanecieron intactos.

La suite de pruebas pasó de **85 a 173 tests**, todos verdes.

---

## 2. Las cinco órdenes del día

| Hora | Orden recibida | Resultado |
|---|---|---|
| 09:37 | Solo lectura; decisiones cerradas (mantener 081/082/083, regla de "Migrado de", autorización de P1/P2/P4); segundo entregable en dry-run | CSV v2 `4137bbce…`, 3 módulos nuevos, 26 tests nuevos, **111 OK**; `--apply` **no** ejecutado |
| 10:28 | Orden exacta: (1) copia raíz ← v2, (2) `--apply`, (3) verificación post, (4) parche v2.1 sin tocar la DB | **11 → 20 tags**, `b91fefe6…`, 9 filas de auditoría, v2.1 `c40ec1f3…` |
| 10:49 | Dump read-only de los 9 tags vivos + **sprint de numeración masiva** (Fases 1 a 4) | **111 tags candidatos / 37 lazos**, motor de trazado profundo, **132 OK** |
| 11:28 | Pase de corrección determinístico (R1–R7) sobre la propuesta masiva | **99 tags / 33 lazos** `1b7894ad…`, **153 OK** |
| 12:19 | Decisiones A y B confirmadas + R8 + inserter por olas + dry-run completo | v3 `0729eac9…`, inserter, dry-run 39/60 tags, **173 OK** |

Intensidad de la sesión (state.db): 117 llamadas a `terminal`, 83 a `patch`, 20 a `read_file`, 15 a `write_file`, 2 a `memory`.

---

## 3. Saneamiento de la propuesta de 9 tags (09:37 – 10:29)

Se corrigieron los tres puntos observados en la revisión del 16/09, **sin cambiar los números** 081/082/083:

- **P1 — citas documentales.** Corregidas a los valores reales (`.195`/`.196` → hoja `PLCs` fila 2 y `Programas` fila 6, programa `DES`, rutina `DES_LC_DESAIREADOR`).
- **P2 — ocupación de números.** Nuevo módulo `src/identificadores_vigentes.py` con extracción léxica **reproducible** (regla `<MORFEMA ISA>_<número de 2-3 dígitos>`, excluyendo tokens de equipo como `BNOT_xx`, `ADD_xx`, `SCL_xx`, `MUL_xx`). Resultado: la ocupación real del área 300 es `101-103|105-122` (21 números) y la del área 200 es `101-109|201-209` (18). La versión v1 informaba mal: contaba instancias de escalera y tokens inexistentes (`020`, `081`, `601`).
- **P4 — camino real de wires.** Columna `Tag_Intermedio` con la cadena completa (alias de campo → bloque `SCL` → tag interno REAL → PV → MV → alias de salida); declarada la **acción inversa** del lazo de agua potable (`ACCION_CTRL_DIREC1_INVER0 = 0`); registrado el `IRef LT_CUBA_1` sin cable como ambigüedad sin acción.
- **Nota_Sucesion** por número: 081 (dueño previo `FT_VINO_A_JW_ACUM_TOTAL`, retirado 28/08), 082 (figuraba como "Conservar", nunca insertado), 083 (sin antecedente en área 300; salto de área 200→300 documentado).
- **Gobernanza documentada:** la prohibición de reutilizar números retirados (regla 8) rige **desde la puesta en producción con operarios**; la DB está en construcción, por lo que la reasignación trazada es aceptable.

Entregables: `src/generar_propuesta_numeracion_v2.py`, `src/diferencias_propuesta_v1_v2.py`, `src/insertar_9_tags_aprobados.py` (dry-run probado, transacción `BEGIN IMMEDIATE` con `ROLLBACK` ante colisión), test de determinismo por subproceso, diff v1→v2 (135 filas) y diff v2→v2.1 (3 filas).

---

## 4. La única escritura del proyecto: alta de los 9 tags (10:28 – 10:49)

### Orden de ejecución autorizado

1. La copia suelta `propuesta_numeracion_3_lazos.csv` de la raíz se sobrescribió con el v2 de `exports/` (verificado con `cmp`, byte-idéntico).
2. `src/insertar_9_tags_aprobados.py --apply` → **11 → 20 tags**.
3. Verificación post-inserción:

| Control | Resultado |
|---|---|
| Tags en producción | **20**, todos con estado `Planificado` |
| `PRAGMA integrity_check` | `ok` |
| SHA-256 de la base | `c450eb3f…84ca17` → **`b91fefe6…5ba6b6`** |
| Backup histórico de 693 tags | `ee1df1c9…78c440` — **sin cambio** |
| Backup nuevo (pre-inserción) | copia **byte-idéntica** con el hash `c450eb3f…` + backup por API (no byte-idéntico: la API rearma el archivo página a página) |
| Auditoría | **9 filas, ids 3986–3994**, `tag_id` 1095–1103, usuario `agustin (via Hermes)`, fecha `2026-09-18 10:29:21`, detalle `Migrado de <identidad PLC>` |
| Los 11 tags manuales | intactos en contenido |

4. Parche **documental** v2.1 (`c40ec1f3…`) sobre la coincidencia histórica del número 082, **sin tocar la DB**; la copia de la raíz se resincronizó con v2.1.

Los 9 tags quedaron así:

| Área | Número | Tags |
|---:|---:|---|
| 300 | 083 | `300_LT_083`, `300_LIC_083`, `300_LV_083` |
| 200 | 081 | `200_FT_081`, `200_FIC_081`, `200_FV_081` |
| 200 | 082 | `200_LT_082`, `200_LIC_082`, `200_LV_082` |

Después del alta se subieron los dos tests preexistentes que fijaban el conteo en 11 → 20, **manteniendo la igualdad estricta a propósito** (para que cualquier escritura no autorizada rompa la suite) y se agregó un test de estado real. Suite: **113 OK**.

---

## 5. Sprint de numeración masiva (10:49 – 11:37)

**Objetivo del día:** pasar de 9 a 30-50 tags. **Resultado: 111 tags candidatos (37 lazos).**

### 5.1 Fase 1 — los 40 lazos "casi listos"

Diagnóstico: 31 de los 40 bloqueos por `ALIAS_NO_RESUELTO` **no eran alias irresolubles** sino:

- **referencias cruzadas entre programas** del tipo `\FAB_ESCALADOS.CCV_PT_10_5BAR`, y
- **bloques de escalado intermedios** (`SCL`, `MOV`, `ADD`).

Cadena real verificada a mano (el parser la cortaba):

```text
ISLA_FAB_AI:9:I.Ch5Data (dirección física)
  → SCL_45 (In) → CCV_PT_10_5BAR (REAL interno)
  → \FAB_ESCALADOS.CCV_PT_10_5BAR → PV de B_PC_10_5
  → MV_VALV_NC → CCV_S16_PCV_10BAR_5BAR_SECADOR → ISLA_FAB_AI:16:O.Ch[3].Data
```

Nuevo motor `src/trazador_lazos_profundo.py` (22,6 KB): referencias cruzadas entre programas, recorrido **dentro** de bloques (SCL, MOV, ADD, MUL, LIMIT…), direcciones físicas de módulo como terminal válido, pines `MV*` (`MV_VALV_NC` / `MV_VALV_NA`), trazado hacia adelante para la salida y clasificación en cuatro categorías (`CERRABLE_HOY`, `BLOQUEADO_EXTREMO_COMPARTIDO`, `BLOQUEADO_ANALIZADOR`, `BLOQUEADO_DOCUMENTAL`).

**Resultado: 32 de 40 cerrables** (antes: 0). Los 20 que no entraron: 13 por extremo compartido verificado (p. ej. `CCV_S7_PT_VAP_ESCAPE` lo leen 5 controladores distintos), 5 requieren analizador más profundo, 1 área ambigua y 1 variable no determinable.

### 5.2 Fase 2 — los 7 grupos completos

| Grupo | Resultado |
|---|---|
| `CONTROL_PRESION_2_20_10` | entra — nº 042 |
| `B_Ctrol_FT_MELAZA` | entra — nº 086 |
| `B_DES_PC_DESAIREADOR`, `B_DES_PC_VALVULA_20_10` | bloqueados: extremo compartido en hoja |
| `B_Ctrol_LT_TK_ENCALADO` | bloqueado: la salida alcanza 2 direcciones físicas distintas |
| `B_Ctrol_LT_TK_PESADO` | bloqueado: declaración sin invocación XML |
| `B_CL_TOLVA` | bloqueado: REAL interno sin escritor en el XML |

### 5.3 Fase 3 — la propuesta masiva

- `exports/propuesta_numeracion_masiva_180926.csv` — **37 lazos / 111 tags** (`20560397…`), 3 tags por lazo con el mismo número, `Estado_Propuesta = PROPUESTA_CONCRETA_PARA_REVISION — NO_INSERTAR` y `Escritura_SQLite = NO` en todas las filas.
- `exports/resumen_propuesta_masiva_180926.csv` y `exports/bloqueos_propuesta_masiva_180926.csv` (173 filas: 123 analizador, 25 documental, 21 extremo compartido, 3 área ambigua, 1 variable ambigua).
- `exports/analisis_210_lazos.csv` — **52 cerrables de 210** declaraciones de controlador.
- Libertad de números verificada contra **5 universos** independientes: DB de producción, backup de 693, inventarios online, identificadores ISA-like de los 10 L5X y números citados en `docs/*.md`.

### 5.4 Fase 4 — analizador y tests

19 tests nuevos del trazador. Defectos propios encontrados y corregidos durante el día: el parser tomaba `\FAB_ESCALADOS.CCV_PT_10_5BAR` como *el programa* en vez del tag; la constante `L5X` quedó tapada por la clase homónima; el trazado cortaba en el bloque tratando `SCL_45` como tag; `analizar()` devolvía dicts incompletos en las salidas tempranas (lo destaparon los tests). Suite: **132 OK**.

---

## 6. Pase de corrección determinístico R1–R7 (11:28 – 11:38)

La propuesta masiva pasó de **111 a 99 tags** (37 → 33 lazos). Los 4 lazos que salieron, con causa:

| Lazo | Motivo |
|---|---|
| `DESTILERIA/FERMENTACION/B_Ctrol_NIVEL_CUBA_1` | el elemento final es un arrancador de motor → `REVISION_ELEMENTO_FINAL`, sin numerar |
| `DESTILERIA/JW/PID_Ctrol_Grado_Alcohol` | el tag que alimenta PV no aporta morfema y el AOI no determina variable |
| `FABRICA/FAB_CCV/B_PID_VAL_20_10_AUX_1` y `_2` | ídem (caso previsto por el usuario) |

Reglas aplicadas y su efecto:

| Regla | Efecto medido |
|---|---|
| R1 variable por morfema del tag interno que alimenta PV | **11 lazos con variable corregida** (p. ej. `TT_AGUA_INMIBICION` → **T**; v1 la tenía como L) |
| R2 función de salida | 29 salidas `XV` (pin todo/nada) y 4 `V` (pin `MV` analógico); arrancadores separados |
| R3 identidad de entrada | desapareció `SIN TAG PLC`: 32 entradas con **tag REAL interno** y 1 declarada `CANAL_CRUDO:<dirección>` |
| R4 columnas nuevas | `Descripcion_Propuesta`, `Fluido_Proceso`, `Tipo_Senal`, `Entrada_Salida_BD`, `DataType_BD` |
| R5 renumeración | por área y variable, re-verificada en los 5 universos, número compartido por lazo |
| R6 ocupación extendida | áreas **100, 200, 300, 500, 600 y 700** (FABRICA es multi-área: prefijo `EVAP`→500, `COC`→600, `CCV`→700) |
| R7 análisis re-etiquetado | **19 de 210 filas** con estado final distinto del trazado, conservando el crudo en `Clasificacion_Trazado` |

**Verificación del dato sospechoso:** el "1" del área 500 **no es un error** — es `500_IT_001` del backup de 693 (comprobado contra la base) y `500_FT_001` citado en el manual.

Cuatro defectos propios detectados y corregidos en este pase:

1. Los universos de ocupación estaban limitados a las áreas 200 y 300 (la verificación de libertad de 100/500/600/700 era incompleta).
2. **Grave:** `src/generar_propuesta_masiva.py` escribía el nombre canónico del entregable y, al correr dentro de la suite, **pisó la v2 corregida** (quedó comprobado: 112 líneas, 26 columnas). Es el mismo trap que el handoff documenta para `propuesta_historica_lazos.py`. Se movió el generador a `…_v1.csv` y se agregó un **test de regresión** que lo ejecuta y verifica que la v2 no cambie.
3. Re-correr el pase duplicaba dos columnas del encabezado del análisis.
4. Faltaba `estado_crudo()`: tras el re-etiquetado, el generador leía el estado post-filtro y dejaba de detectar extremos compartidos. El pipeline quedó idempotente y con test de reproducción.

Suite: **153 OK**.

---

## 7. Decisiones A y B + R8 → v3, y el inserter por olas (12:19 – 12:27)

### 7.1 Lo aplicado al entregable

| Decisión / regla | Resultado |
|---|---|
| **A** — convención de casa con función `XV` | 29 salidas `700_PXV_008`, `500_LXV_088`, `200_FXV_087`, `100_TXV_029`…; `XV` pelado reservado a válvulas de corte fuera de lazo; documentado en la columna `Nota_Convencion` |
| **R8** — tipo de señal | **29 `Digital`** (pines `MV_VALV_NC`/`MV_VALV_NA`) y **70 `Analógico`** (las 4 salidas `MV`, todas las entradas y los controladores) |
| **B** — salidas sin alias | **12 salidas** pasan a `Migrado_De = CANAL_CRUDO:<dirección>` con la dirección conservada en `AliasFor_Direccion_Fisica` |

Evidencia de que la decisión A era la correcta: el tag pelado `700_XV_008` se lee como variable **X** ("Sin clasificar"), mientras `700_PXV_008` se lee correctamente como variable de presión.

Backlog de limpieza pre-paro generado: `exports/salidas_canal_crudo_pendientes.csv` (`a59e3b52…`), 12 filas con lazo, dirección, módulo y slot — `fermerntacion2022_islas` slots 7 y 8 (9 salidas), `jw_fermerntacion_2022` slot 11 (2), `ISLA_FAB_AI` slots 12 y 13 (2). **Sin alias de campo no hay nada que renombrar en Studio 5000.**

v3 del entregable: **99 tags / 34 columnas**, SHA-256 `0729eac9…`; v2 resguardada (`1b7894ad…`); diff v2→v3 (`6eadc710…`, 113 diferencias: 29 por A, 29 por R8, 12 por B + 31 notas y 12 descripciones).

### 7.2 Puerta de calidad ISA y lectura humana

- Se corrió el **validador ISA de la propia app** (`app_etiquetas/validador_isa.py` + `isa_rules.py`) sobre los 99 tags: **0 problemas duros** (cualquier fallo bloquea el paquete y aborta el `--apply`). Las 99 "sugerencias" son indicadores locales que la app propone siempre y **no bloquean**.
- Control negativo verificado: un `700_PT_008` aislado sí reporta "Falta Controlador / Falta Actuador", o sea que el "sin problemas" significa algo.
- `validar_funcion_isa("XV")` pasa y `XV` está permitida para las variables P, T, L y F.
- **Lectura humana:** resuelve los 99 tags sin error. Queda un hueco real: el diccionario **hardcodeado** `MAPEO_FUNCIONES` de `app_etiquetas/app_tags.py:64` no incluye `XV`, así que la app muestra el código crudo ("**XV de Nivel**" en lugar de "Válvula Todo/Nada de Nivel"). No se corrigió en silencio: queda pendiente de autorización (§11).

### 7.3 El inserter por olas

`src/insertar_propuesta_masiva.py` (`61742db5…`), reutilizando el patrón probado del alta de 9 tags:

- lee **solo** el CSV final (v3);
- **dry-run por defecto**; escribe únicamente con `--apply`;
- backup **byte-idéntico** con timestamp **+** backup por API, ambos verificados contra la base;
- **una transacción `BEGIN IMMEDIATE` por ola**, con `INSERT OR IGNORE` de la fila del catálogo de funciones `XV` **dentro** de la transacción (nunca antes) — la fila ya existía (id 2148, "Válvula Todo/Nada / On-Off"), así que el `INSERT OR IGNORE` deja 0 filas nuevas y no la altera;
- **re-chequeo en el instante de insertar**: tag inexistente y número sin ocupantes ajenos a la ola;
- **fila de auditoría** `Migrado de <identidad>` por alta;
- verificación dentro de la transacción y `ROLLBACK` total ante cualquier error o colisión.

| Ola | Áreas | Lazos / tags | Conteo |
|---|---|---:|---|
| 1 | 200 y 300 | 13 / 39 | 20 → **59** |
| 2 | 100, 500, 600 y 700 | 20 / 60 | 59 → **119** |

**Prueba end-to-end sobre una copia de la base** (nunca sobre producción): ola 1 → 59 tags, ola 2 → 119 tags, `integrity_check ok`, fila `XV` intacta, 108 filas de auditoría acumuladas, backup byte-idéntico conservando el hash pre-inserción, y hash de producción **sin cambio**.

**Defecto propio grave encontrado y corregido:** el re-chequeo del número contaba los tags de la **propia ola** (los 3 de un lazo comparten número a propósito), de modo que **toda ola habría hecho ROLLBACK**. Lo destapó la ejecución real del `--apply` sobre la copia; se corrigió para que solo bloqueen ocupantes ajenos a la ola.

### 7.4 Dry-run de las dos olas

```text
PLAN DE ALTA POR OLAS -- ola 1 (areas 200, 300)      PLAN DE ALTA POR OLAS -- ola 2 (areas 100, 500, 600, 700)
Base .....: app_etiquetas/tags_ingenio.db            Base .....: app_etiquetas/tags_ingenio.db
SHA-256 ..: b91fefe6…                                SHA-256 ..: b91fefe6…
Tags .....: 20 (esperado antes 20 / después 59)      Tags .....: 20 (esperado antes 59 / después 119)
Filas ....: 39 tags / 13 lazos                       Filas ....: 60 tags / 20 lazos
PUERTA ISA: 0 problemas duros · 39 sugerencias       PUERTA ISA: 0 problemas duros · 60 sugerencias
VALIDACIÓN: 0 colisiones duras · 0 avisos            VALIDACIÓN: 0 colisiones duras · 0 avisos
MODO DRY-RUN: no se escribió nada                    [OJO] la ola 2 espera 59 tags antes (hoy hay 20)
```

Transcripciones completas en `exports/dry_run_ola_1.txt` (412 líneas) y `exports/dry_run_ola_2.txt` (623 líneas). Suite final: **173 OK**.

---

## 8. Defectos detectados y corregidos el 18/09

Nueve defectos, ninguno de ellos ocultado; los dos graves son propios y de pérdida de datos o de aborto de escritura:

| # | Defecto | Severidad | Corrección |
|---|---|---|---|
| 1 | La extracción v1 de identificadores contaba instancias de escalera y tokens inexistentes | media | módulo determinístico nuevo (`identificadores_vigentes.py`) |
| 2 | El parser tomaba `\FAB_ESCALADOS.CCV_PT_10_5BAR` como programa | alta (bloqueaba los 40 lazos) | reclasificación de operandos |
| 3 | Constante `L5X` (directorio) tapada por la clase homónima | media | renombrada `DIR_L5X` |
| 4 | `analizar()` devolvía dicts incompletos en salidas tempranas | media | helper `resultado()` con todas las claves |
| 5 | Universos de ocupación limitados a las áreas 200/300 | media | extendidos a las 6 áreas |
| 6 | **El generador masivo escribía el nombre canónico y pisó la v2 entregada** | **grave** | se movió a `…_v1.csv` + test de regresión |
| 7 | Re-correr el pase duplicaba columnas del encabezado del análisis | baja | lista de columnas sin duplicados |
| 8 | Faltaba leer el estado crudo (el pipeline dejaba de ser idempotente) | media | `estado_crudo()` + test |
| 9 | **El re-chequeo del número en la transacción contaba su propia ola** | **grave** | solo bloquean ocupantes ajenos a la ola |

---

## 9. Estado al cierre de la jornada

| Elemento | Estado |
|---|---|
| Base de producción `app_etiquetas/tags_ingenio.db` | **20 tags**, todos `Planificado`; SHA-256 `b91fefe6…5ba6b6`; `integrity_check ok` |
| Backup histórico de 693 tags | `ee1df1c9…78c440` — **sin cambio** |
| Registros de auditoría del día | ids 3986–3994 (usuario `agustin (via Hermes)`, 10:29:21) |
| Propuesta de 9 tags | v2.1 `c40ec1f3…` — **ya insertada** (§4) |
| Propuesta masiva (entregable vigente) | **v3: 99 tags / 33 lazos** `0729eac9…` — **no insertada** |
| Versiones resguardadas de la masiva | v1 `20560397…`, v2 `1b7894ad…` |
| Frontera de controladores | 213 declaraciones · 210 incompletos · **52 cerrables** · 37 elegibles (33 tras R1/R2) |
| Bloqueos de la propuesta masiva | 123 analizador · 25 documental · 21 extremo compartido · 4 variable ambigua · 3 área ambigua · 1 elemento final |
| Suite de pruebas | **173 OK** (progresión del día: 111 → 113 → 132 → 153 → 173) |
| `app_etiquetas/backups/` | 5 archivos; los dry-run y los tests **no** crearon backups |

---

## 10. Disciplina de verificación aplicada

| Control | Resultado del 18/09 |
|---|---|
| Suite completa | 173 tests OK |
| `compileall` sobre `src` y `tests` | OK |
| `git diff --check` | OK (solo el aviso de fin de línea preexistente) |
| SHA-256 de ambas bases antes y después | producción cambió **solo** en el alta autorizada (`c450eb3f…` → `b91fefe6…`); backup de 693 sin cambio |
| `PRAGMA integrity_check` | `ok` en producción y en todos los backups generados |
| Determinismo entre procesos (`PYTHONHASHSEED` 11 y 97) | CSV byte-idénticos en los 7 artefactos del pase y de la v3 |
| Cero escrituras SQLite no autorizadas | única escritura: el alta de 9 tags; el `--apply` del inserter masivo se probó **solo sobre una copia** |
| Confirmación explícita de `Escritura_SQLite=NO` | presente en las 99 filas de la propuesta y en las 3 de la revisión de elemento final |

---

## 11. Pendientes abiertos

1. **Autorizar la ola 1 y la ola 2** del inserter masivo. El dry-run está listo y sin hallazgos; la ola 2 requiere la ola 1 aplicada (59 → 119).
2. **Lectura humana de `XV`:** agregar `"XV": "Válvula Todo/Nada"` al diccionario `MAPEO_FUNCIONES` de `app_etiquetas/app_tags.py` (una línea, con su verificación). Hoy la app muestra el código crudo. Pendiente de autorización.
3. **`--con-alias-for`:** por defecto el inserter escribe `tags.alias_for = ''`, espejo del alta de 9 (el `AliasFor` queda trazado en el CSV y en el backlog). Si se quiere la dirección también en la base, el flag ya está implementado.
4. **Backlog de limpieza pre-paro:** 12 salidas sin alias de campo (`salidas_canal_crudo_pendientes.csv`), para crear alias en Studio 5000 antes de la parada.
5. **Grupos y lazos todavía bloqueados:** los 5 grupos completos que no cerraron, más los 173 bloqueos del análisis masivo (123 por analizador, 25 documentales, 21 por extremo compartido).
6. **99 sugerencias de indicador local** de la app (un `PI/LI/TI` por lazo): no están incluidas en ninguna propuesta; decidir si se numeran.

---

## 12. Archivos creados o actualizados el 18/09

### Código (`src/`)

| Archivo | Hora | Rol |
|---|---|---|
| `identificadores_vigentes.py` | 11:29 | ocupación léxica reproducible (R6) |
| `generar_propuesta_numeracion_v2.py` | 10:29 | regenera la propuesta de 9 tags (v2/v2.1) |
| `diferencias_propuesta_v1_v2.py` | 10:30 | diff reproducible entre versiones del CSV |
| `insertar_9_tags_aprobados.py` | 10:29 | alta de los 9 tags (dry-run / `--apply`) |
| `trazador_lazos_profundo.py` | 10:57 | trazado XML profundo (Fases 1, 2 y 4) |
| `generar_propuesta_masiva.py` | 11:37 | propuesta masiva v1 y elegibilidad |
| `corregir_propuesta_masiva.py` | 12:22 | pase R1–R8 + decisiones A y B → v3 |
| `insertar_propuesta_masiva.py` | 12:25 | alta por olas con transacción y auditoría |

### Tests (`tests/`) — 173 en total

| Archivo | Tests |
|---|---:|
| `test_identificadores_vigentes.py` | 15 |
| `test_insertar_9_tags_aprobados.py` | 13 |
| `test_trazador_lazos_profundo.py` | 20 |
| `test_correccion_propuesta_masiva.py` | 25 |
| `test_insercion_propuesta_masiva.py` | 15 |
| (resto de la suite, sin cambios funcionales) | 85 |

### Exportaciones (`exports/`)

| Archivo | SHA-256 (inicio) |
|---|---|
| `propuesta_numeracion_3_lazos.csv` (v2.1, insertada) | `c40ec1f3…` |
| `propuesta_numeracion_3_lazos_v2.csv` (resguardo) | `4137bbce…` |
| `diff_propuesta_v1_v2.csv` / `diff_propuesta_v2_v2_1.csv` | `516f2635…` / `18250432…` |
| `identificadores_vigentes_por_area.csv` (6 áreas) | `db0a292b…` |
| `analisis_40_lazos.csv` / `analisis_210_lazos.csv` | `b6112abd…` / `8683c706…` |
| `propuesta_numeracion_masiva_180926_v1.csv` (generador) | `20560397…` |
| `propuesta_numeracion_masiva_180926_v2.csv` (resguardo) | `1b7894ad…` |
| **`propuesta_numeracion_masiva_180926.csv` (v3 vigente)** | **`0729eac9…`** |
| `diff_propuesta_masiva_v1_v2.csv` / `diff_propuesta_masiva_v2_v3.csv` | `36510efb…` / `6eadc710…` |
| `resumen_propuesta_masiva_180926.csv` | `696c8bcc…` |
| `bloqueos_propuesta_masiva_180926.csv` | `1bea6242…` |
| `revision_elemento_final_180926.csv` | `5f37fc00…` |
| `salidas_canal_crudo_pendientes.csv` | `a59e3b52…` |
| `dry_run_ola_1.txt` / `dry_run_ola_2.txt` | `5ff48488…` / `331bdc24…` |

### Documentación (`docs/`)

| Archivo | Contenido |
|---|---|
| `Resumen_Ejecutivo_Avance_180926.md` / `.pdf` | este informe |

---

## 13. Nota de cierre — hallazgo al emitir este informe (21/09)

Al generar y verificar este informe apareció un efecto no previsto, que quedó corregido y con test:

- El universo **U5** ("números citados en `docs/*.md`") leía **todos** los documentos, incluidos los informes de avance. Como este informe cita los tags candidatos del día (`100_TXV_029`, `200_FXV_087`, `500_LXV_088`, `700_PXV_008`), esos números pasaban a contarse como *ocupados* y **el entregable se renumeraba solo**: al re-correr el pase, v3 cambiaba de `0729eac9…` a `c484bfc1…` (área 100 029→031, área 200 087→096, área 700 008→009).
- Un documento **derivado** del CSV no puede alimentar el universo de ocupación de aquello que documenta, o cada informe renumeraría lo que describe. Se acotó U5: **no lee los informes de avance desde el 18/09/2026**; la documentación normativa (manuales, roadmap, handoff) y los informes anteriores se siguen leyendo.
- Verificado: con el corte, el pase vuelve a producir **exactamente** v3 `0729eac9…` (el entregable auditado y descripto en este informe) y la regeneración es reproducible. Se agregaron dos tests: que U5 no tome los números del informe y que el corte se calcule por **fecha real** (el primer intento comparó el nombre como texto y excluía también los informes de agosto).
- Queda como decisión del usuario si los informes **históricos** (26/08 a 16/09) también deben salir de U5: hoy aportan números que solo citan como candidatos. Al excluirlos, la numeración se ensancha (primeros libres: área 200 → 083, área 300 → 036, área 100 → 029), lo que cambiaría el entregable ya auditado. No se hizo sin autorización.

---

*Informe generado el lunes 21/09/2026 a partir de `state.db` de Hermes (sesión `20260916_103822_d52f4c`, 470 mensajes del 18/09), de los hashes de los artefactos y del mtime de cada archivo. No se escribió en SQLite para producirlo.*
