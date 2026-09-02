# Resumen Ejecutivo de Avance
## Proyecto de Estandarización de Instrumentación y Control — Ingenio La Florida

**Fecha:** 28 de agosto de 2026
**Informe anterior:** `Resumen_Ejecutivo_Avance_270826` (27/08/2026)

---

## 1. Resumen del período

Viernes 28/08, **última jornada del sprint con asistencia de IA** (ventana 07:30–12:30). El plan original apuntaba a la matriz de Mantenimiento, la curaduría de la bandeja y las exportaciones pendientes; la realidad del día se reacomodó alrededor de tres frentes que resultaron más rentables y que se cerraron con **3 minutos de sobra**:

1. **Misterio de planta resuelto:** el PLC "fantasma" `jw2013` (38,1%, el peor de la planta) resultó ser **el PLC principal de DESTILERIA** escondido bajo el nombre de un tacho viejo. Con el `.L5X` fresco, Destilería entró al tablero con **83,0%** de efectividad de partida.
2. **Saneamiento sistémico de la base:** se confirmó que el **23,1% de los tags cargados** eran acumulados matemáticos tageados como instrumentos; se retiraron 126, se marcaron 56 en observación, se eliminaron 11 pares de duplicados y se comprimió la numeración (fase de setup). La base pasó de 663 a **684 tags**, con 682 `Instalado`.
3. **Tags App a nivel de producción:** las 5 mejoras de UI/UX pedidas por el ingeniero (botón de tag propuesto visible, buscador inteligente, seguridad en eliminar, fecha/hora y tipo de señal en la grilla), más el descubrimiento y **fix de un bug crítico**: `eliminar_tag()` estaba roto desde el día uno (FK contra `auditoria` sin capturar) y el botón "Eliminar" crasheaba siempre.
4. **Backfill de metadata desde los 12 `.L5X`:** se pobló `alias_for`, `datatype` y la columna Entrada/Salida para los 682 tags históricos; **140 tags físicos** quedaron con I/O real identificado.
5. **Proyecto greenfield CO2:** se desglosaron los **12 instrumentos tageables** de la Columna Recuperadora de CO2 (Área 200) bajo norma estricta y se agregó el campo **`fluido_proceso`** a la app (informativo, nunca parte del tag).

El tablero de planta cerró en **76,3%** de efectividad ISA (73,0% → 76,3%), impulsado por el reemplazo del archivo muerto de 38,1% por el PLC real de Destilería.

---

## 2. Misterio de planta resuelto: "jw2013" era DESTILERIA

### 2.1 La charla de pasillo

La pista vino de los compañeros: *"¿cuál es la IP del jw?"* — *"la 10.128"* — *"pero la 128 es de Destilería"* — *"sí, por eso. jw es un tacho"*. El nombre `jw2013` era el de un tanque viejo; el archivo que se auditaba como jw2013 era en realidad **el PLC principal de Destilería** (misma IP, mismo PLC).

### 2.2 Reemplazo del canónico

Se colocó el `.L5X` actualizado (exportado hoy 07:51) en `archivos ACD y L5X auditados\dist\auditoria l5x y ACD` y se verificó integridad antes de tocar nada:

```
TargetType="Controller", Controller Name="DESTILERIA", 1704 tags
```

Cambios aplicados:

| Acción | Detalle |
|---|---|
| `jw2013.L5X` | Archivado en `data_historica/backup_canonicos_reemplazados_280826/` con nota del porqué — **no se borró nada** |
| `DESTILERIA.L5X` | Cargado como canónico (12 canónicos, `jw2013` desapareció del pipeline) |
| Área por defecto | `DESTILERIA → 200` en `AREA_DEFECTO_POR_PLC` |
| `MANUAL_IP_OVERRIDES` | **Retirado** — existía desde el 06/08 y forzaba la IP `.128` a asociarse con jw2013 por desconfianza del Excel de Yanco; el Excel siempre tuvo razón |

La prueba de que el override estaba mal: el match contra planta viva pasó de **56,5% (jw2013) a 99,2% (DESTILERIA)** — casi el doble de tags confirmados vivos, con el mismo Excel.

### 2.3 Desglose de clases del PLC nuevo (1.690 tags vivos)

| Clase | Tags |
|---|---|
| `INTERNA` | 859 |
| `INTERNA_SISTEMA` | 289 |
| `FUNCIONAL_ISA` | 212 |
| `EQUIPO_DISCRETO` | 121 |
| `SIN_CLASIFICAR` | 110 |
| `EQUIPOS_LOGICA` | 79 |
| `FISICO_ISA` | 18 |
| `RESERVADO` | 2 |

**Efectividad de partida: 83,0%** — mejor que CALD_LA_FLORIDA cuando empezamos ayer.

### 2.4 Confirmación de identidad

Los tags reales de la isla hablan solos: `CAUDALIMETRO_MELAZA`, `DENSIDAD_MELAZA`, `LT_CUBA_1…LT_CUBA_6` (nivel de cubas de fermentación), `NIVEL_TK_VINO`, `IT_CENTRIFUGA_2`, `PID_CTROL_PT_DESTILADORA_KP` — vocabulario 100% de destilería/fermentación, coincidente con la confirmación de Ingeniería.

> **Nota de alcance:** `DESTILERIA_RECUPERADO` es otro equipo físico del mismo complejo, de un proyecto distinto, y **sigue congelado** a la espera del Excel de Yanco (`.131`/`.132`). No se tocó ni se confundió con este PLC.

---

## 3. Hallazgo sistémico: los acumulados eran estadística tageada como instrumentos

El ingeniero explicó que los transmisores cuentan diferenciales pequeños, los guardan y promedian por hora y por día — de ahí los `ACUM_DIA_ACT`, `ACUM_DIA_ANT`, `ACUM_HR_*`, `ACUM_TOTAL`. El instinto de Agustín: *"me hace ruido que esté tageado eso"*. Tenía razón.

### 3.1 Qué es realmente esto

`ACUM_*`/`HR`/`DIA`/`TURNO` **no son mediciones nuevas**: son valores calculados a partir de la lectura de un instrumento que ya tiene su propio tag. El motor de auditoría ya los conoce: cualquier tag con esos tokens cae directo a `INTERNA` (`TOKENS_TAG_DERIVADO`, Criterio 3c de `clasificar()`).

Hay además una regla física estricta ya escrita en `Manual_Estandarizacion.md` (Sección 4): **un acumulado/totalizador solo tiene sentido físico sobre Caudal o Cantidad (F/Q)**. Una presión, temperatura o nivel no se "totaliza" — no existe "el nivel acumulado del día".

### 3.2 El tamaño real del problema (medido, no estimado)

**182 de los 789 tags ya cargados en la Tags App (23,1%)** seguían este patrón:

| Variable | Tags | Instrumentos base afectados | ¿Válido como `.Tot`? |
|---|---|---|---|
| TT (Temperatura) | 85 | 17 | ❌ No |
| FT (Caudal) | 56 | 10 | ✅ Sí, pero no como tag propio |
| LT (Nivel) | 20 | 4 | ❌ No |
| PT (Presión) | 16 | 5 | ❌ No |
| PIT (Presión) | 5 | 1 | ❌ No |

- **126 tags (LT+PT+PIT+TT)** violan la regla física directamente — ni siquiera deberían modelarse como `.Tot`.
- **56 de FT** son físicamente válidos como concepto de totalización, pero tampoco deberían ser tags numerados propios: deberían vivir como miembro `.Tot`/`.Tot_Prev` del mismo tag base.

Es la misma familia que el 26/08 (`PT_VAPOR_ENTRADA_ACUM_*`, 6 tags, tratada como caso puntual): ahora se confirma que es **un patrón de migración repetido 37 veces en toda Destilería**. Verificación cruzada: el motor clasifica los 182 correctamente como `INTERNA` en el `.L5X` fuente — la divergencia es **100% de la carga manual**, no del motor. Y en los 12 PLCs no hay **ningún** caso en que el enlace automático a `.Tot` haya funcionado (deuda técnica de Fase 4, nunca resuelta).

### 3.3 Acción ejecutada (con bitácora)

En una sola transacción, verificada contra la base real (no solo el log):

| Acción | Resultado |
|---|---|
| 126 tags TT/LT/PT/PIT derivados de acumulados | `estado='Retirado'` — se quedan con su historial (no se borran), liberan su lazo |
| 56 tags FT | Siguen `Instalado`, con comentario *"ATENCIÓN: Totalizador derivado. Evaluar migración a miembro .Tot del instrumento base"* |
| Auditoría | 126 filas `CAMBIO_ESTADO` + 56 `MODIFICACION`, cada una con el motivo |

Regla de criterio confirmada para el día: **solo el instrumento real lleva tag propio; cualquier derivado/acumulado va como comentario o se descarta, nunca como tag numerado nuevo.** Se aclaró explícitamente que esto no elimina el tagueo de variables de proceso, controladores (PIC/LIC/FIC) y actuadores (PV/LV/FV): se tagea todo el lazo, lo que no se tagea es la variable matemática de reporte.

---

## 4. Saneamiento de la base de datos (fase de setup)

### 4.1 Los 11 pares de duplicados — la pista era `plc_origen`

Un campo **`plc_origen` que ni siquiera está declarado en `schema.sql`** (lo agregó el script de carga externo `carga_masiva`, 30/07/2026) deduplicaba por `(plc_origen, tag_viejo)`, pero el mismo PLC físico aparecía bajo distintas grafías en los datos fuente de esa fecha — y no las reconocía como la misma cosa. Resultado: **11 pares (22 tags) duplicados**, no un caso aislado.

La corrección invirtió el supuesto original: **no es el 023 el bueno, es el 024** (trazaba al canónico `Calderas_8_9_10_Desaireador` completo, no al truncado `..._Des`).

| Descripción origen | Conservar | Eliminar | Motivo |
|---|---|---|---|
| `DES_LT_TK_AGUA_DE_POZO` | `200_LT_024` | ~~200_LT_023~~ | origen truncado |
| `FT_VINO_A_JW_ACUM_HR_ACT` | `200_FT_082` | ~~200_FT_079~~ | origen fechado (16062026) |
| `FT_VINO_A_JW_ACUM_HR_ANT` | `200_FT_083` | ~~200_FT_080~~ | ídem |
| `FT_VINO_A_JW_ACUM_TOTAL` | `200_FT_084` | ~~200_FT_081~~ | ídem |
| `TT_SALIDA_CAL_VINO` | `300_TT_036` | ~~300_TT_032~~ | ídem |
| `TT_SALIDA_CIGARRO` | `300_TT_037` | ~~300_TT_033~~ | ídem |
| `TT_SALIDA_ENF_ALCOHOL` | `300_TT_038` | ~~300_TT_034~~ | ídem |
| `TT_TC_204` | `300_TT_039` | ~~300_TT_035~~ | ídem |
| `FT_JUGO`, `FT_VINO_A_JW`, `LT_TK_LAVADO_GRILLA_INT` | número más bajo | número más alto | duplicados "puros" del mismo origen, sin desempate |

**Regla aprobada y ejecutada:** los 8 primeros conservan el que traza al canónico vigente; los 3 últimos conservan el número de lazo más bajo.

### 4.2 Consolidación final: 663 → 684 tags

```
663 (inicio) − 11 (duplicados eliminados) + 6 (Nivel de Cubas LT_CUBA_1..6)
             + 26 (Isla de Vapor, correlativos 300) = 684 tags
```

- **682 `Instalado` + 2 `Planificado`** (`250_PV_001`/`250_PV_002`, válvulas de escape de presión, cargadas el 31/07 por "Agustin" — no son basura). Cero `Retirado`.
- **Fechas históricas:** los 32 tags migrados hoy tenían fecha de hoy; se hizo backdate a **2026-07-30 09:43:44** (la fecha real de la carga masiva original), con rastro en `auditoria`.
- **Compresión de numeración (fase de setup):** se comprimieron las **12 familias afectadas** en un bloque transaccional — `200_LT` quedó corrido 1→34, `300_XV` 1→17 — con **0 duplicados y 0 violaciones de integridad referencial**.

> **Criterio de fase, dejado explícito:** en la fase de armado de la línea base se **borra físicamente y se renumera** para no arrastrar huecos de una carga vieja y sucia. Cuando la app entre en uso cotidiano, la regla cambia: **el tag no se borra, pasa a `Retirado` (mostrado en rojo) y su número nunca se reutiliza** (`MAX(numero_loop)+1`), preservando la trazabilidad de planos e informes.

---

## 5. Tags App a nivel de producción (mejoras del ingeniero)

El ingeniero vio la app y pidió mejoras de UI/UX; además, en el camino se destapó un bug crítico.

| Mejora | Implementación |
|---|---|
| **Botón de Tag Propuesto visible** | Chip grande (18pt, fondo ámbar, borde) + botón "Copiar" rediseñado; cambia a celeste en modo edición |
| **Buscador inteligente** | Nueva sección "Paso 5": barra de búsqueda con filtro en tiempo real (`<KeyRelease>`) sobre tag, descripción/alias, comentarios y PLC de origen, sobre grilla Treeview con scroll |
| **Seguridad en Eliminar** | Doble confirmación severa (`askyesno` con ícono de advertencia, texto de irreversibilidad, sugiere usar `Retirado`) + botón visualmente achicado |
| **Columnas nuevas** | Fecha/Hora de creación y Tipo de Señal en la grilla; campo `datatype` agregado a la base (no existía) con combobox al alta/edición |
| **Tipo de Señal** | `inferir_tipo_senal(datatype)`: `BOOL→Digital`, `REAL/INT/DINT→Analógico` |
| **Sincronización Paso 2 → Paso 5** | Seleccionar un tag en el listbox lo inyecta en el buscador y filtra la grilla a ese único resultado |
| **Color rojo para `Retirado`** | `tree.tag_configure("retirado", foreground=ROJO_PELIGRO)` — listo para producción |

**Bug crítico encontrado y arreglado de raíz:** `eliminar_tag()` estaba **roto desde el día uno** para cualquier tag creado normalmente — la FK con `auditoria` (la misma que mordió ayer) hacía que el `DELETE` explotara con `IntegrityError` sin capturar. El botón "🗑️ Eliminar" **crasheaba**, no solo "confirmaba poco". Se reprodujo, se arregló y se re-testó end-to-end (alta, búsqueda, edición, eliminación de tags de prueba contra la base real).

---

## 6. Backfill de metadata: `alias_for`, `datatype` y Entrada/Salida

El barrido (`backfill_alias.py`, script temporal **borrado tras correr**) cruzó los **682 tags instalados** contra los 12 `.L5X` canónicos, por nombre de tag viejo o por `Description` exacta cuando el nombre no había quedado guardado:

| Resultado | Cantidad |
|---|---|
| Con `AliasFor` real (hardware físico `:I.`/`:O.` de módulo) | **140** |
| Encontrado, pero tag interno/calculado sin alias (correcto, no es fallo) | 515 |
| No encontrado en su `.L5X` | 1 |
| Ambiguo — `Description` repetida entre 2+ tags, no se adivinó | 26 |

Los 27 no resueltos son casi todos del mismo cluster (`300_XV_001..017`, `300_FIC_001`, `300_PIC_005/007`): en el `.L5X` real hay dos tags con la misma Description (la válvula "cruda" y su variante `Grelha_XV1xx`, o el miembro `_ALM`). Se prefirió dejar sin `alias_for` antes que adivinar mal.

**Bonus necesario:** ningún tag traía `datatype` poblado desde la carga original; para los 140 con alias se usó el **`Radix` de Rockwell como proxy** (Float→REAL, Binary→BOOL; Decimal se dejó sin resolver por ambiguo). Resultado: **139 de 140** con Digital/Analógico + Entrada/Salida completo, y **572 tags con datatype** (antes solo 32) — el Tipo de Señal mejoró en toda la grilla, no solo en el pedazo I/O. 655 tags actualizados, con una fila `MODIFICACION` en `auditoria` por cada uno.

### 6.1 Refactor de la inferencia y limpieza semántica

- `inferir_tipo_senal()` volvió a Digital/Analógico puro; se agregó **`inferir_entrada_salida()`** como columna propia con 4 estados posibles (sin adivinar ninguno):

| Valor | Significado |
|---|---|
| `Entrada` / `Salida` | `alias_for` trae marcador Rockwell real (`:I.`/`:O.` o `_IN`/`_OUT` como token completo — probado a propósito contra falsos positivos tipo `S1_IT_RAS_INCLINADA`) |
| `Memoria / Red` | ya se cruzó contra el `.L5X` y es una variable que se lee por memoria/comunicación |
| `N/D` | todavía no se sabe (139/682 sin `alias_for` capturado, o formato no reconocido) |

- **Cambio de nombre semántico:** el estado que decía "Interna" pasó a llamarse **"Memoria / Red"**. El ingeniero lo pidió: instrumentos reales como `200_LT_029` (LT_CUBA_1) no van cableados directo al rack — llegan por red/bus y en el PLC figuran en memoria sin alias `:I.`. Decir "Interna" se confundía con la clase `INTERNA` de auditoría (la de descartar basura) y hacía parecer inválido un tag perfectamente válido.

Verificado en vivo: `200_FT_002 → Analógico (Entrada)`, `200_LT_029 → Memoria / Red`, `300_XV_001 → N/D`.

---

## 7. Dashboard final de planta

<pre class="tabla-mono">
PLC                             Tags totales   Match de vida   % Match vida   % Efectividad ISA
------------------------------  ------------   -------------   ------------   ------------------
CALD_LA_FLORIDA                        1.736           1.736         100,0%               87,7%
CENTRIFUGA_DE_PRIMERA                  1.827           1.827         100,0%               82,6%
Calderas_8_9_10_Desaireador            1.439           1.435          99,7%               54,8%
DESTILERIA                             1.704           1.690          99,2%               83,0%
DIBACCO                                  582             582         100,0%               67,1%
FABRICA                                3.140           3.138          99,9%               58,1%
Painel_Ctr_Turb_Moenda                   243             240          98,8%               97,8%
TRAPICHE2022                           2.492           2.492         100,0%               82,2%
USINA_LA_FLORIDA                         925             925         100,0%               90,8%
cenizas2020                              793             787          99,2%               88,8%
------------------------------  ------------   -------------   ------------   ------------------
TOTAL PLANTA (ponderado)              14.881          14.852          99,8%               76,3%
</pre>

### Evolución del día

| PLC | Ayer (27/08) | Hoy (28/08) | Δ |
|---|---|---|---|
| jw2013 | 38,1% | *(reemplazado)* | — |
| DESTILERIA | *(no existía)* | **83,0%** | nuevo |
| **TOTAL PLANTA** | **73,0%** | **76,3%** | **+3,3** |

La aritmética del total es exacta: 14.912 − 1.735 (jw2013) + 1.704 (DESTILERIA) = 14.881 tags; match de vida 14.142 − 980 + 1.690 = 14.852.

> **Nota metodológica:** a diferencia del 27/08 (mejora por higiene del denominador), el salto de hoy proviene de **descubrir que el peor PLC era en realidad otro**: se reemplazó un archivo muerto de 38,1% por el código real y fresco de Destilería. Es el tipo de ganancia que no sale de clasificar mejor, sino de conocer la planta — y quedó validada contra el Excel de Yanco (99,2% de match de vida).

---

## 8. Proyecto greenfield: Columna Recuperadora de CO2 (Área 200)

Se desglosó la instrumentación de la columna para carga manual por el usuario (el PLC todavía no está programado; la lista se reconstruyó del **data-sheet del fabricante NEW PRO Engenharia** + notas de campo del ingeniero). Son **3 lazos PID completos** (confirmados por la nota del ingeniero: *"1. PID Nivel, 2. PID Alimentación Agua, 3. PID Presión de columna"*):

### 8.1 Los 12 instrumentos tageables

| Lazo | Sensor | Controlador | Actuador |
|---|---|---|---|
| **Presión de columna** | `PT` (transmisor, entrada analógica) | `PIC` (controlador PID) | `PV` (válvula 16", entrada de CO2 desde las cubas) |
| **Nivel de columna** | `LT` (entrada analógica) | `LIC` (controlador PID) | `LV` (válvula que drena a `TK_FLEGNAZA`) |
| **Alimentación de agua** | `FT` (entrada analógica de caudal) | `FIC` (controlador PID) | `FV` (válvula de agua de lavado) |

Más **3 visores locales de nivel** (variable `L`, función `G` — visor/mirilla, sin electrónica) del data-sheet. **Total: 12 instrumentos tageables.**

**Quedan fuera del universo ISA** (regla "se tagea lo que se controla"): las 2 entradas RTD de reserva (sin asignar) y los equipos `COL_CO2_ALCOHOL`, `TK_FLEGNAZA`, `BBA_FLEGMA_01/02` — son equipos, no instrumentos, y van al inventario de Mantenimiento Mecánico.

**Ambigüedad resuelta:** el transmisor de presión es `PT`, **no** `PDT` — confirmado por 3 fuentes independientes (data-sheet, cuaderno de un segundo ingeniero, respuesta verbal del ingeniero principal).

> **Consejo de carga:** la app no ata automáticamente `PT↔PIC↔PV` como pares del mismo lazo — la trazabilidad se deja en el campo Comentarios de cada tag (ej. en `200_PT_0NN`: *"Lazo de Presión de Columna CO2, par: 200_PIC_0NN / 200_PV_0NN"*).

### 8.2 Campo nuevo: `fluido_proceso` ("Fluido / Producto")

El usuario pidió poder registrar qué fluido pasa por cada instrumento (alcohol 90°/96°/99°, agua pura, agua común, flegmasa, vino, CO2, vapor) — solo como información adicional, **sin que cambie el tag** (el Manual de Estandarización ya prohíbe materiales en el nombre técnico). No había lugar dedicado: `descripcion` está copada por "Migrado de X", `comentarios` se usa para notas del motor, y `ubicacion`/`rango_medicion`/`unidad` están casi siempre vacíos.

Se implementó de punta a punta:

| Capa | Cambio |
|---|---|
| `schema.sql` | Columna `fluido_proceso TEXT` (después de `alias_for`), con comentario: informativo, nunca entra en `tag_completo` |
| `database.py` | `ALTER TABLE` idempotente en `_migrar_columnas_faltantes()`; `crear_tag()`/`actualizar_tag()`/`buscar_tags()` con el campo (búsqueda incluida: buscar "flegmasa" encuentra los tags que la tienen) |
| `app_tags.py` | Combobox **editable** en Paso 3 (debajo de Datatype), lista pre-cargada + opción de escribir uno nuevo; columna propia en la grilla del Paso 5 |

La carga manual de los 12 instrumentos quedó pendiente de ejecutar por el usuario (la app ya proponía `200_LT_035` como primer tag del Lazo de Nivel).

---

## 9. Norma y cultura: ISO 14224 vs ISA-5.1, y el lugar de TOTVS

### 9.1 La discusión con Juan (Mantenimiento)

Juan leyó la ISO 14224 y notó que **no asigna una estructura cerrada** de nombres (da ejemplos: Bomba = PU, pero no una receta), y propuso usar la estructura ISA-5.1 para nombrar los equipos. La conclusión técnica: **usar ISA-5.1 para equipos mecánicos es una trampa de ingeniería** — la primera letra de ISA indica la variable física medida, así que una bomba "P-201" se leería como "Lazo de Presión 201" en cualquier plano P&ID o software.

La convención pactada, que comparte la raíz de áreas pero usa prefijos inconfundibles:

```
[Área (3 dígitos)] - [Clase de Equipo (ISO/jerga)] - [Correlativo]
   200                  BBA (Bomba)                     01        →   200-BBA-01
```

**Los instrumentos usan ISA-5.1; los equipos mecánicos usan taxonomía ISO/interna; se conectan por la base de datos sin chocarse en los planos.**

### 9.2 La pregunta del de usina ("¿no es mejor TOTVS?")

TOTVS es un **árbol de activos muertos para Automatización**: maneja jerarquías de mantenimiento (área, equipos, componentes físicos como rodamientos), pero no entiende ISA-5.1, no audita PLCs, no distingue una variable analógica de una digital y no genera nomenclatura para programar Studio 5000. La Tags App es el **puente de ingeniería** que el ERP no contempla: audita los `.L5X`, estandariza bajo norma, filtra basura de programación, calcula la efectividad ISA y evita duplicados. La respuesta técnica: conviven, no compiten — TOTVS gestiona las órdenes de trabajo de los fierros; la app le da de comer el tag exacto de automatización.

### 9.3 Arquitectura multi-usuario validada

El plan de arquitectura discutido con el jefe y los pasantes quedó revisado y aprobado:

- **SQLite en red:** usar carpeta SMB real (no OneDrive/Drive sincronizado) con disciplina de "un escritor por vez"; migrar a **PostgreSQL cuando duela** — la separación `database.py` vs `app_tags.py` está pensada para que ese cambio no toque la interfaz.
- **Inventario de Equipos separado de Señales:** mecánica carga contra una tabla de equipos propia (norma ISO 14224), con clave de deduplicación (nombre normalizado + área) — evita que dos personas relevan la misma máquina dos veces; `codigo_totus` como referencia cruzada opcional.
- **Los números muertos no resucitan:** un lazo dado de baja queda `Retirado` (nunca se borra ni se reutiliza); el siguiente correlativo es `MAX(numero_loop)+1`. La trazabilidad histórica (planos, informes) sigue apuntando al número.
- **`construir_tag()`:** "decirle a la empresa contratista qué tag va a usar" es el §4 del Roadmap de arquitectura — ya diseñado, pendiente de implementar.

---

## 10. Cierre del sprint, estado y pendientes

**Situación:** sprint de 5 horas cerrado a las 12:27 (3 minutos de margen). Planta en **76,3%**; Destilería incorporada con su identidad real (83,0%); base saneada con **684 tags** (682 instalados, numeración comprimida, fechas históricas correctas); Tags App en calidad de producción con bug crítico resuelto; metadata I/O poblada desde los `.L5X`; proyecto CO2 desglosado bajo norma con el campo de fluido listo.

**Repositorio:** subido a GitHub como `agustincuellar-dev/app_tags_estandarization` (privado; se hizo público temporalmente para el push y se volvió a privado). Commits del día: `b8c18d9` (UI + consolidación) y `3e72f8e` (refactor Entrada/Salida). **Pendiente:** la cuenta real de GitHub es `codecuellar` — transferir el repo (Settings → Transfer ownership) o re-apuntar el remoto (`git remote set-url origin https://github.com/codecuellar/app_tags_estandarization.git`).

**Prioridades sugeridas:**

1. **Carga manual de los 12 tags de la Columna CO2** (Área 200) usando el campo `fluido_proceso` nuevo — cerrar el greenfield en la base.
2. **Migración del resto de la Isla de Vapor:** de los ~218 instrumentos rescatados el 27/08 en CALD_LA_FLORIDA solo ingresaron 26 a la base; el lote completo sigue pendiente.
3. **Resolver los 27 tags ambiguos** de Calderas (`300_XV_001..017`, `300_FIC_001`, `300_PIC_005/007`) para completar el `alias_for` (Description duplicada en el `.L5X`).
4. **Decidir el destino de los 56 tags FT** en observación (¿se reportan/facturan como cantidad oficial?).
5. **Transferir el repo a `codecuellar`** y dejar el `README`/manuales al día.
6. Siguen abiertas de informes anteriores: deuda de área (~730 tags, con la matriz de Mantenimiento), deuda de trazado Fase 4 (~1.000 tags), pantalla de bandeja de pendientes en la Tags App, exportar `LA_FLORIDA` (IP `.160`, 676 tags sin auditar), Excel de Yanco de Fermentación (`.131`/`.132`) para `DESTILERIA_RECUPERADO`/vinaza, y los 1.136 conflictos de numeración histórica.

---

## 11. Archivos modificados hoy

| Archivo | Cambio |
|---|---|
| `app_etiquetas/app_tags.py` | 5 mejoras de UI/UX del ingeniero, buscador inteligente (Paso 5), seguridad en eliminar, columnas Fecha/Hora + Tipo de Señal + Entrada/Salida, sincronización Paso 2→5, color rojo `Retirado`, combobox `fluido_proceso` |
| `app_etiquetas/database.py` | **Fix crítico `eliminar_tag()`** (FK contra `auditoria`), `inferir_tipo_senal`/`inferir_entrada_salida`, `_migrar_nombres_area` (Ósmosis/Desfibrador), migraciones `datatype`/`alias_for`/`entrada_salida`/`fluido_proceso`, backdate de fechas históricas |
| `app_etiquetas/schema.sql` | Columnas `datatype`, `alias_for`, `entrada_salida`, `fluido_proceso` |
| `src/cruzar_planta_viva.py` | Retirado `MANUAL_IP_OVERRIDES` (forzaba IP `.128` → jw2013) |
| `auto_agustin/DESTILERIA.L5X` | **Nuevo canónico** — reemplaza a `jw2013` (Área 200 por defecto) |
| `data_historica/backup_canonicos_reemplazados_280826/` | `jw2013.L5X` archivado con nota (no se borró) |
| `backfill_alias.py` | **Temporal** — barrido de `alias_for`/`datatype`/Radix; creado y borrado en el día |
| `docs/Manual_Mantenimiento_Codigo.md` | **Nuevo** — manual de supervivencia del código (cómo modificar prefijos de área, diccionarios ISA y código vs. base de datos sin la IA) |
| Repositorio GitHub | `agustincuellar-dev/app_tags_estandarization` — commits `b8c18d9` y `3e72f8e` (pendiente transferencia a `codecuellar`) |
