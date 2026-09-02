# Resumen Ejecutivo de Avance
## Proyecto de Estandarización de Instrumentación y Control — Ingenio La Florida

**Fecha:** 27 de agosto de 2026
**Informe anterior:** `Resumen_Ejecutivo_Avance_260826` (26/08/2026)

---

## 1. Resumen del período

Jornada intensiva de una sola sesión, con dos frentes que se retroalimentaron: por un lado la **aplicación de la corrección de alcance** que Ingeniería había emitido el 19/08 ("solo se tagea lo que se controla") sobre los 12 PLCs canónicos; por el otro, el descubrimiento de que el motor de auditoría estaba **descartando instrumentos reales** por limitaciones propias de su tokenizador. El resultado combinado llevó la efectividad ISA de planta de **59,7% a 73,0%**.

Además, y como cierre estructural del día, se diseñó e implementó el mecanismo de **Aprendizaje por Excepción**: la aplicación ahora aprende de las excepciones desde la base de datos, en vez de requerir un parche en código Python cada vez que aparece un tag no reconocido.

Cinco frentes:

1. Filtro agresivo de alcance ISA ("solo se tagea lo que se controla") sobre los 12 PLCs.
2. Nueva categoría `EQUIPOS_LOGICA` para el proyecto paralelo de Mantenimiento Mecánico.
3. Resolución de tres PLCs estancados (Painel, TRAPICHE2022, Calderas 8/9/10) — incluido un **bug de área homónima**.
4. Hallazgo mayor: el tokenizador no detectaba la nomenclatura ISA clásica (`FIT100`), perdiendo la isla de vapor completa.
5. Implementación del motor de Aprendizaje por Excepción, integrado de punta a punta al pipeline.

---

## 2. Aplicación del filtro de alcance ISA

Se implementó en `src/auditar_l5x.py` el filtro que formaliza la regla de Ingeniería del 19/08. Criterios agregados a `clasificar()`, en orden de evaluación:

| Filtro | Destino | Motivo |
|---|---|---|
| Alias crudo que alimenta bloque de escalado (`SCL`) | `INTERNA` | Señal pre-escalado, duplica al instrumento real |
| Instancia de bloque de escalado (`SCP`/`SCALE`/`SCL_xx`) | `INTERNA` | Acondicionamiento de señal, no el instrumento |
| Tag derivado (tokens `ACUM`, `TOTAL`, `HR`, `DIA`, `TURNO`, `PROM`) | `INTERNA` | Reporte acumulado, no la variable de proceso |
| `TIMER`, `COUNTER`, `DEADTIME`, `FBD_COUNTER`, `FBD_ONESHOT` | `INTERNA` | Lógica de programa |
| Datatype `INT` | `INTERNA` | Setpoints/consignas de receta, no la PV medida |
| Prefijos `FALLA_`, `TRIP_`, `BIT_`, `IS_`, `SLOT_`, `LOC_`, `MAR_`, `SP_`, `PROTEC_`, `ALM_`, `PROPORCION_` | `INTERNA` | Flags y consignas de software |

**Piloto en DIBACCO** (antes de aplicarlo masivamente): 59 tags reclasificados, efectividad 50,5% → 59,9%. Validado y recién entonces extendido a los otros 11 PLCs.

### 2.1 Corrección de dos fugas detectadas en la validación

Al auditar el resultado por `datatype` se detectaron dos categorías que se habían colado indebidamente como instrumentos:

- **`FBD_COUNTER`** (3 tags) — contadores de programa (`CONTADOR_DE_BALANZADAS`, `BALANZA_EN_FALLA`).
- **`INT`** (35 tags) — setpoints de receta (`Velocidad_carga`, `Espesor_de_carga`, `Tiempo_velocidad_interm`).

Regla de Ingeniería que zanjó el criterio: *"se tagea el instrumento que mide, no la cajita de texto donde el operador pone la velocidad deseada"*.

---

## 3. Nueva categoría `EQUIPOS_LOGICA`

A pedido del proyecto paralelo de mecánica, los equipos de fuerza motriz **no se mezclan** con la basura de programación. Se creó una clase propia:

- **Comportamiento métrico:** igual que `INTERNA_SISTEMA` — no suma al éxito ISA ni entra al denominador del universo de proceso.
- **Alcance:** datatype `ARRANQUE_MOTOR_2` y tags con token `ARRANQUE`.
- **Volumen:** **406 tags** identificados a nivel planta (FABRICA 135, Calderas 8/9/10 83, TRAPICHE2022 60, CALD_LA_FLORIDA 53, jw2013 49, CENTRIFUGA 15, cenizas2020 7, DIBACCO 4).

Quedan marcados con `clase=EQUIPOS_LOGICA` en los CSV para que Mantenimiento Mecánico los filtre directamente.

---

## 4. Desbloqueo de tres PLCs estancados

### 4.1 `Painel_Ctr_Turb_Moenda`: 11,4% → 97,8%

El diagnóstico inicial ("es un panel brasileño, falta dialecto") resultó **incorrecto**. La investigación mostró que **172 de 203 tags pendientes (85%) ya estaban correctamente clasificados** — el bloqueo era que este PLC **no tenía entrada en `AREA_DEFECTO_POR_PLC`**, así que sus tags quedaban como `???_TRIP_2301` en vez de `100_TRIP_2301`. Se le asignó Área 100 (Molienda).

El remanente real de dialecto era de solo 31 tags, mapeados así:

| Prefijo PT-BR | Función ISA | Lectura |
|---|---|---|
| `VIB_`, `IMP_`, `DESB_` | `V` | Vibración / Análisis Mecánico |
| `AUX_CALCULO_ARRASTE` | `INTERNA` | Cálculo derivado, no medición |

### 4.2 `TRAPICHE2022`: 53,7% → 82,2%

Mismo patrón: de 770 pendientes, **531 (69%) no eran problema de clasificación** sino de área o de trazado Fase 4. Se confirmó por distribución real (1451 de 1596 tags con área resuelta caían en Molienda) y se asignó Área 100 por defecto, sin pisar las áreas minoritarias ya detectadas (800/300/200/400/900).

Reglas de limpieza aplicadas al remanente real: `SENSOR_` sin datatype → `INTERNA`; `FLOTACION_` → `Z` (posición del rodillo del molino); `IC_CINTA_` → `I` (corriente de motor de cinta); `FBD_ONESHOT` y `PROTEC_` → `INTERNA`.

### 4.3 `Calderas_8_9_10_Desaireador`: bug de área homónima

**Hallazgo importante:** el prefijo `DES` significa *Destilería* (área 200) en toda la planta, **pero en este PLC significa Desaireador** (equipo de calderas, área 300). Confirmado por el alias real en el `.L5X`:

```
DES_2_S5_BBA_11_ESTADO  ->  alias_for: 'Desaireador_2:5:I.Data.0'
```

**267 tags (25% del PLC)** estaban etiquetados como si pertenecieran a Destilería. Se implementó un mecanismo de **override de área scoped por PLC** (`MAPEO_AREA_OVERRIDE_POR_PLC`), que corrige el homónimo sin alterar el mapeo global correcto de Destilería.

> **Nota de costo:** este fix requirió modificar 6 funciones de `auditar_l5x.py` y enhebrar un parámetro nuevo (`mapeo_area`) por toda la cadena de llamadas. Ese costo fue precisamente lo que motivó el trabajo de la Sección 6.

Además se mapearon los dampers (`C8_*`, `C9_*`, `C10_*`, `DAMP_*`) a la letra ISA **`D`** — elementos finales de control de caudal de aire/gases.

---

## 5. Hallazgo mayor: la nomenclatura ISA clásica no se detectaba

Investigando por qué las calderas seguían estancadas en 52-54%, se descubrió que **`detectar_funcion_isa()` solo partía el nombre por `_`, `-` y `.`**. Por lo tanto:

```
FIT100      -> None      (aunque 'FIT' SÍ está en ISA_VALIDOS)
PIT100      -> None
XV106       -> None
PT_DOMO_C10 -> 'PT'      (con separador sí funcionaba)
```

La ironía es que se trata de **la nomenclatura ISA clásica** — la que mejor cumple la norma — y era justamente la que el motor no alcanzaba. Detrás de ese patrón estaba **la isla de vapor completa** de CALD_LA_FLORIDA, con descripción confirmada en el `.L5X`:

| Tag | Descripción real |
|---|---|
| `PIT100` | PRESSÃO DO BALÃO (presión de domo) |
| `LIT100A` / `LIT100B` | NIVEL DO BALÃO lado direito/esquerdo |
| `FIT100` / `FIT101` | VAZÃO DE AGUA DE ALIMENTAÇÃO / VAPOR PRINCIPAL |
| `LV100` | VALVULA DE ALIMENTAÇÃO DE AGUA |
| `FV101` | VALVULA DE PARTIDA |
| `PV101_9D/9E`, `PV105_1/2` | DAMPER VENT. PRIMARIO / EXAUSTOR IDF |
| `XV106`…`XV122` | ACIONAMENTO GRELHA 1-14, DESCARGA DE FUNDO |
| `LIC100` | CONTROL DE NIVEL DEL DOMO |

**218 instrumentos reales recuperados a nivel planta.**

### 5.1 La trampa que se evitó: `TC` no es Temperature Controller

Una regex ingenua habría capturado también 42 tags `TC01`, `TC02`… como si fueran controladores de temperatura. Las descripciones probaron lo contrario:

```
SD_TC01A  ->  "SENSOR DESALINHAMENTO A - MOTOR ESTEIRA DE DISTRIBUIÇÃO"
```

`TC` = **Transportador de Correa** (*esteira*), no Temperature Controller.

**Solución adoptada:** en vez de depender de las descripciones (la mitad están vacías), se discriminó **por cantidad de dígitos**: los lazos ISA de la planta usan 3-4 dígitos (`TT100`, `TIT111`), los equipos usan 1-2 (`TC01`, `TT01`). Verificado contra los 12 PLCs: 218 recuperados, **cero falsos positivos**.

### 5.2 Segundo criterio: el nombre gana sobre el datatype

`DINT` estaba en la lista de datatypes internos, pero en Calderas 8/9/10 el integrador guarda variables de proceso reales como enteros escalados (`DES_2_LT_TK_ALCOHOL_1` = NIVEL TANQUE DE ALCOHOL). Se implementó la excepción: **cuando el nombre trae un código ISA explícito, esa evidencia manda sobre el tipo de dato** — acotada a `DINT` y solo cuando el nombre no tiene además marcadores internos propios (`B_`, `SCL_`).

47 tags recuperados; **21 llegaron a tag ISA completo, 26 quedaron bloqueados por la deuda de área** (ver Sección 8).

---

## 6. Aprendizaje por Excepción — la app ahora aprende sola

El día dejó en evidencia el costo del patrón actual: **cada excepción nueva era una edición de código Python + re-corrida completa**. Se diseñó e implementó el mecanismo que lo reemplaza.

### 6.1 Arquitectura

Dos tablas nuevas en `app_etiquetas/schema.sql`:

- **`reglas_aprendidas`** — patrón + tipo de match (`EXACTO` / `PREFIJO` / `REGEX`) + acción (`FUNCION_ISA` / `INTERNA` / `EQUIPOS_LOGICA` / `FISICO_ISA` / `RESERVADO`) + scope opcional por PLC + motivo.
- **`tags_no_clasificados`** — la bandeja de pendientes.

Tres módulos:

- **`app_etiquetas/aprendizaje.py`** — `buscar_regla()`, `archivar_pendiente()`, `resolver_pendiente()`, más `listar_pendientes()` y `descartar_pendiente()`.
- **`src/aprendizaje_motor.py`** — el puente. `clasificar_con_aprendizaje()` es un reemplazo *drop-in* de `clasificar()`.
- Integración en `auditar_l5x.procesar()` y `procesar_todos_l5x.procesar_uno()`, mediante **parámetros opcionales con import diferido**: si no se pasa conexión, el motor sigue siendo standalone, sin ninguna dependencia de la Tags App.

### 6.2 Flujo

1. El motor clasifica con sus reglas de código.
2. Si un tag queda `SIN_CLASIFICAR`, **consulta la base antes de rendirse**.
3. Si tampoco hay regla, **archiva el tag solo** en la bandeja.
4. El usuario lo resuelve con un clic → la regla queda persistida → **la próxima corrida lo resuelve sola**.

### 6.3 Validación end-to-end

| Prueba | Resultado |
|---|---|
| Regresión (`usar_aprendizaje=False`) | Idéntico al motor puro |
| No-invasividad (bandeja vacía) | Dashboard sin cambios — 0 tags movidos |
| Ciclo completo con tag real (`AUX_SPTIT410`) | CSV de salida con la nota *"Resuelto por regla aprendida #7 (Tags App, sin tocar auditar_l5x.py)"* |
| Precedencia `REGEX` > `PREFIJO` | `ME101_10_CORRENTE` → `IT`, no `EQUIPOS_LOGICA` |
| Scoping por PLC | `ME126` resuelve en CALD_LA_FLORIDA, **no** en FABRICA |

### 6.4 Primer uso real en producción

Las últimas 10 reglas del día **se cargaron por este mecanismo, sin tocar una línea de Python**, resolviendo 259 pendientes de CALD_LA_FLORIDA:

| Regla | Tipo | Destino | Resolvió |
|---|---|---|---|
| `SLOT` | PREFIJO | `RESERVADO` | 40 |
| `SD_`, `SE_`, `SR_`, `SFR_` | PREFIJO | `INTERNA` | 64 |
| `^ME\d.*_CORRENTE$` | REGEX | `FUNCION_ISA` / `IT` | 5 |
| `^ME\d.*_A(_\d+)?$` | REGEX | `FUNCION_ISA` / `IT` | 28 |
| `^ME\d.*_(Reference\|REF)$` | REGEX | `INTERNA` | 27 |
| `^ME\d.*_ALM$` | REGEX | `INTERNA` | 27 |
| `ME` | PREFIJO | `EQUIPOS_LOGICA` | 68 |

**Nota de criterio:** los 33 tags de corriente de motor se mapearon a `IT` (medición real) en vez de descartarlos, manteniendo **consistencia con la decisión de `IC_CINTA_*` → `I`** tomada horas antes en TRAPICHE2022. Los `SLOT*_RES*` se verificaron uno por uno: los 40 tienen descripción **y** `alias_for` vacíos — son canales de reserva físicamente sin instrumento, idénticos a los `RESERVA_*` que el motor ya clasificaba `RESERVADO`.

---

## 7. Dashboard final de planta

<pre class="tabla-mono">
PLC                             Tags totales   Match de vida   % Match vida   % Efectividad ISA
------------------------------  ------------   -------------   ------------   ------------------
CALD_LA_FLORIDA                        1.736           1.736         100,0%               87,7%
CENTRIFUGA_DE_PRIMERA                  1.827           1.827         100,0%               82,6%
Calderas_8_9_10_Desaireador            1.439           1.435          99,7%               54,8%
DIBACCO                                  582             582         100,0%               67,1%
FABRICA                                3.140           3.138          99,9%               58,1%
Painel_Ctr_Turb_Moenda                   243             240          98,8%               97,8%
TRAPICHE2022                           2.492           2.492         100,0%               82,2%
USINA_LA_FLORIDA                         925             925         100,0%               90,8%
cenizas2020                              793             787          99,2%               88,8%
jw2013                                 1.735             980          56,5%               38,1%
------------------------------  ------------   -------------   ------------   ------------------
TOTAL PLANTA (ponderado)              14.912          14.142          94,8%               73,0%
</pre>

### Evolución del día

| PLC | Inicio (18/08) | Cierre (27/08) | Δ |
|---|---|---|---|
| CALD_LA_FLORIDA | 48,7% | **87,7%** | +39,0 |
| TRAPICHE2022 | 52,8% | **82,2%** | +29,4 |
| Painel_Ctr_Turb_Moenda | (nuevo) | **97,8%** | — |
| USINA_LA_FLORIDA | 79,0% | **90,8%** | +11,8 |
| CENTRIFUGA_DE_PRIMERA | 72,5% | **82,6%** | +10,1 |
| DIBACCO | 50,5% | **67,1%** | +16,6 |
| Calderas_8_9_10 | 50,4% | 54,8% | +4,4 |
| cenizas2020 | 86,5% | 88,8% | +2,3 |
| FABRICA | (nuevo) | 58,1% | — |
| jw2013 | 42,9% | 38,1% | −4,8 |
| **TOTAL PLANTA** | **59,7%** | **73,0%** | **+13,3** |

---

## 8. Deuda técnica identificada (documentada, no resuelta)

Se dejan explícitamente anotadas tres deudas, ninguna resuelta hoy:

1. **Deuda de área (~730 tags plantawide).** Tags correctamente clasificados pero sin código de área resoluble por nombre ni por Scope, que quedan como `???_FT_006`. Es el **cuello de botella principal de Calderas 8/9/10** (340 tags): 26 de los 47 rescatados por la regla `DINT` siguen bloqueados por esto. Se resolverá con la matriz de Mantenimiento.

2. **Deuda de trazado Fase 4 (~1.000 tags).** Tags `SCALE`/`.Raw` y acumuladores `.Tot`/`.Fault` correctamente marcados `INTERNA`, pero para los que el motor no logra identificar a qué instrumento base pertenecen (`"parece miembro .Raw pero no se halló el instrumento base"`).

3. **`EA_VARIAVEIS` / `IN_ANALOGICO` (60 tags en DIBACCO).** Congelados a la espera de confirmación de campo con Ingeniería, por decisión explícita — no se tocaron.

### Advertencia metodológica sobre la métrica

Parte de la mejora del día proviene de **sacar tags del denominador** (`RESERVADO`, `EQUIPOS_LOGICA`, `INTERNA_SISTEMA` son higiene y no computan). Esto es legítimo cuando se trata de canales físicamente vacíos o de equipos que no son lazos ISA — y en cada caso se verificó la evidencia antes de aplicarlo. Pero conviene tenerlo presente: **el 73,0% mide "de lo que es tageable bajo ISA, cuánto está tageado"**, no "qué porcentaje de todo el PLC está resuelto".

---

## 9. Estado actual y próximos pasos

**Situación:** 10 PLCs vivos auditados, efectividad de planta 73,0%; motor de Aprendizaje por Excepción operativo e integrado al pipeline; 1.388 tags en bandeja de pendientes (259 ya resueltos por regla, 1.129 esperando curaduría).

**Prioridades sugeridas:**

1. **Actualizar `jw2013`** — su `.L5X` es viejo; se descartó del análisis del día. Se actualizará desde la red. Es el peor PLC de la planta (38,1%) y el único que retrocedió.
2. **Resolver la deuda de área** con la matriz de Mantenimiento — desbloquearía Calderas 8/9/10 y buena parte de FABRICA de un solo golpe.
3. **Curar la bandeja de pendientes** desde la Tags App (1.129 tags) — ahora es trabajo de datos, no de código.
4. **Construir la pantalla de bandeja** en la Tags App (hoy las funciones existen pero se invocan por script; falta la UI con el "clic").
5. Sigue pendiente de informes anteriores: exportar `LA_FLORIDA` (IP `.160`, 676 tags vivos sin auditar), Excel de Yanco de Fermentación (`.131`/`.132`) para descongelar `DESTILERIA_RECUPERADO`/`vinaza`, y los 1.136 conflictos de numeración histórica.

---

## 10. Archivos modificados hoy

| Archivo | Cambio |
|---|---|
| `src/auditar_l5x.py` | Filtros de alcance, `EQUIPOS_LOGICA`, detección ISA pegada, override de área por PLC, nombre-sobre-datatype, enganche de aprendizaje |
| `src/procesar_todos_l5x.py` | `EQUIPOS_LOGICA` fuera del denominador; conexión al motor de aprendizaje |
| `src/generar_dashboard_planta.py` | `EQUIPOS_LOGICA` en clases de higiene |
| `src/aprendizaje_motor.py` | **Nuevo** — puente motor ↔ Tags App |
| `app_etiquetas/aprendizaje.py` | **Nuevo** — lógica de Aprendizaje por Excepción |
| `app_etiquetas/schema.sql` | **Nuevo** — tablas `reglas_aprendidas` y `tags_no_clasificados` |
| `app_etiquetas/database.py` | Fix: orden de áreas `ORDER BY nombre` → `ORDER BY codigo` |
| `docs/Roadmap_Arquitectura_Inteligente.md` | **Nuevo** — diseño de la arquitectura contextual |
