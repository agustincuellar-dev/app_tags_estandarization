# Manual Corporativo de Estandarización de Instrumentación y Control
## Ingenio La Florida

**Versión:** 0.2 (corrección de alcance incorporada 19/08/2026)
**Alcance de esta versión:** motor de auditoría corrido sobre 12 PLCs canónicos (~17.300 tags relevados), con cruce contra variables vivas de planta y detección de código muerto operativos. Pendiente extender al resto de los PLCs del Ingenio.
**Audiencia:** Operadores, técnicos de instrumentación e ingenieros de Mantenimiento, Operaciones e Ingeniería.

---

## 1. Objetivo del Estándar

Durante años, cada PLC del Ingenio fue creciendo con el criterio de la persona que lo programó en su momento. El resultado, confirmado al auditar el PLC piloto, es un código heredado donde conviven, sin ninguna regla común:

- **Instrumentos físicos reales** (transmisores de presión, temperatura, nivel, caudal) nombrados de formas distintas según quién los cargó: `PT-104`, `CAL_S10_TT_ENT_CAL_1`, `VACIO_2DA_PT`, entre otras variantes.
- **Variables de software puro** (acumuladores, banderas de falla, bloques de escalado, lógica de arranque) mezcladas en el mismo espacio de nombres que los instrumentos, con prefijos como `SCL_`, `ACUM_`, `FALLA_`, `B_`.
- **Nombres de materiales de proceso** (`JUGO`, `MELADO`) usados como si fueran parte del identificador técnico del instrumento, en vez de ir en la descripción.
- **Ningún criterio de numeración compartido entre áreas**, lo que hace imposible saber, solo mirando un tag, a qué sector de la planta pertenece o qué tipo de variable es.

Esta mezcla no es solo un problema estético: impide construir pantallas de SCADA consistentes, dificulta el mantenimiento cruzado entre turnos y PLCs, y hace que Mantenimiento, Operaciones e Ingeniería hablen de la "misma variable" con nombres distintos.

**El objetivo de este estándar es simple: que el nombre de un tag, por sí solo, le diga a cualquier persona qué es, dónde está y para qué sirve** — sin necesitar preguntarle a quien lo programó.

---

## 2. Marco Normativo (La Regla de Oro)

Todo tag del Ingenio pertenece a uno de **dos mundos**, y nunca a los dos a la vez:

### Mundo A — ANSI/ISA-5.1-2024 (el instrumento físico y el proceso)

Se usa **exclusivamente** para lo que representa una función real de medición, indicación o control sobre el proceso: un transmisor, un indicador, un lazo de control, una válvula. Es la norma que entiende un instrumentista, un P&ID o un ingeniero de procesos, sin importar la marca del PLC.

### Mundo B — ISA-88 / IEC 61131-3 / UDTs de Rockwell (la memoria interna del software)

Se usa para todo lo que es **implementación de software dentro del PLC**: la lógica de escalado de una señal, el acumulador de horas de servicio, la bandera de falla de un bloque, el estado de un arranque de motor. Estas variables no representan un instrumento nuevo — son "partes internas" del instrumento o de la lógica, y se organizan como **miembros de un tipo de dato estructurado (UDT)**, según IEC 61131-3.

**La regla de oro:** si vas a nombrar algo que un instrumentista podría señalar con el dedo en la planta (un transmisor, una válvula, un sensor), usás el Mundo A (ISA-5.1). Si vas a nombrar algo que solo existe dentro del programa (un cálculo, una bandera, un contador), usás el Mundo B (UDT). Nunca se mezclan en el mismo tag.

---

## 2.1 Alcance del universo tageable (corrección de Ingeniería, 19/08/2026)

Con la experiencia de auditar los primeros 12 PLCs completos, Ingeniería acotó explícitamente qué entra al Mundo A (ISA). No es cualquier cosa con un token ISA reconocible en el nombre — **es únicamente lo que forma parte de un lazo de control con instrumento físico real**:

- **Transmisores** (`PT`, `TT`, `LT`, `FT`, etc.)
- **Válvulas de control** (`PV`, `LV`, `FV`, etc.)
- **Válvulas de seguridad** (`SV`)

Regla del ingeniero, textual: ***"se tagea lo que se controla".*** Nada más entra al Mundo A.

### Cómo identificar la Variable de Proceso real (y no un derivado)

En el programa, la cadena de una señal analógica es siempre:

```
Entrada Analógica cruda  →  Bloque de Escalado (SCP/SCL)  →  primera salida en unidades de ingeniería
```

**Esa primera salida, la que sale directo del escalado, es la Variable de Proceso** — la única que representa lo que el instrumento físico mide, y por lo tanto la única candidata a tag ISA (`PT`, `TT`, `LT`, `FT`...).

**Todo lo que se calcula DESPUÉS de esa salida — acumulados de hora/día/turno, promedios, totales, alarmas derivadas — NO es la variable de proceso y NO lleva tag ISA propio**, aunque el nombre conserve el mismo prefijo y "parezca" el mismo instrumento.

**Caso real que motivó esta corrección:** la familia `PT_VAPOR_ENTRADA*` en Destilería tenía 6 variantes (`PT_VAPOR_ENTRADA`, `_ACUM_DIA_ACT`, `_ACUM_DIA_ANT`, `_ACUM_HR_ACT`, `_ACUM_HR_ANT`, `_ACUM_TOTAL`), las 6 clasificadas automáticamente como `PT` por compartir el mismo token. Bajo esta corrección, como mucho **una** (la salida directa del escalado) es tag ISA real; las otras 5 son acumulados derivados, fuera de alcance — coherente además con la regla física ya existente en este manual (Sección 4): un acumulador nunca aplica sobre una Presión, así que ya había una señal de alerta ahí antes de esta corrección.

**Consecuencia práctica:** ante una familia de variables con el mismo prefijo, no se tagean todas — se identifica cuál es la salida del bloque de escalado (la variable de proceso) y solo esa entra al Mundo A. El resto queda en Mundo B (UDT, ej. `.Tot`) o directamente fuera del universo de tageo si no aporta valor de instrumentación.

---

## 3. Estructura de Tags ISA (Instrumentos de Campo)

### Regla de construcción

```
[AREA]_[VARIABLE+FUNCIÓN]_[NÚMERO]
```

**Ejemplo:** `300_PT_001` → Área 300 (Calderas), variable Presión, función Transmisor, lazo número 001.

- **AREA**: código numérico de 3 dígitos, fijo por sector de la planta (tabla abajo).
- **VARIABLE+FUNCIÓN**: letras ISA-5.1 (ej. `PT` = Presión + Transmisor, `TT` = Temperatura + Transmisor, `FIC` = Caudal + Indicador/Controlador).
- **NÚMERO**: secuencial de 3 o 4 dígitos, asignado **por lazo de control completo** — todos los instrumentos de un mismo lazo comparten el mismo número (ej. `300_PT_001` y `300_PIC_001` son el mismo lazo).

### Tabla oficial de áreas

| Código | Área |
|---|---|
| 000 | Recepción y Preparación de Caña |
| 100 | Molienda (MOL) |
| 200 | Destilería (DEST) |
| 300 | Calderas / Generación de Vapor (CAL) |
| 400 | Clarificación y Encalado (CLA) |
| 500 | Evaporación (EVAP) |
| 600 | Cocimiento / Tachos (COC) |
| 700 | Centrifugado / Purga (CCV — Centrifugado comparte esta serie por ser la misma etapa) |
| 800 | Secado y Envase (SEC) |
| 900 | Fuerza Motriz / Turbogeneradores (FM — etapa Usina) |
| 950 | Tratamiento de Agua y Servicios (TAS) |

### Reglas semánticas obligatorias

- **Prohibido usar nombres de materiales de proceso** (`JUGO`, `MELADO`, `CACHAZA`, `BAGAZO`, `MIEL`, `MASA`) como parte del tag. El material identifica el fluido, no el instrumento — **eso va en el campo Descripción**, nunca en el nombre técnico.
- Aplican las restricciones del diccionario corporativo ISA (algunas ya verificadas en la auditoría del piloto):
  - `PI` para un visor local está mal — un visor local de presión es `PG`.
  - `TI` para un visor local está mal — un visor local de temperatura es `TG`.
  - Un diferencial de presión usa `D` (`PDT`/`FD`), no se confunde con presión simple.
  - `J` **nunca** se usa como letra de función para "Jugo" — esa letra está reservada para Potencia/Scan.
  - `IS` no es un código ISA-5.1 válido; si aparece, hay que identificar la función real del instrumento.
- Cuando el nombre no trae un token ISA literal pero describe una variable de uso corporativo local (ej. "Humedad", "Brix"), se aplican letras locales acordadas: **Humedad → `M`**, **Brix/Densidad → `D`**.

---

## 4. Estructura de Variables Internas (UDTs)

### Por qué ya no van "sueltas"

Prefijos como `FALLA_`, `SCL_`, `SIM_`, `ACUM_` no describen un instrumento nuevo: describen **una propiedad interna de un instrumento que ya existe** (su estado de falla, su señal cruda antes de escalar, su modo de simulación, su acumulado). Dejarlos como tags sueltos e independientes rompe la trazabilidad: nada indica, con solo mirar `FALLA_PT_101`, que esa bandera pertenece al mismo lazo que `PT_101`.

La solución es encapsularlos como **miembros con punto** del UDT analógico del instrumento (ej. `Transmisor_Analogo`), siguiendo IEC 61131-3:

| Prefijo/sufijo heredado | Miembro de UDT | Significado |
|---|---|---|
| `FALLA_`, `ERR_`, `FLT_` | `.Fault` | Falla del instrumento |
| `SCL_`, `RAW_`, `CRUDA_` | `.Raw` | Valor crudo (4-20 mA sin escalar) |
| `SIM_`, `PRUEBA_`, `FRZ_` | `.Sim` | Modo simulación / forzado |
| `ACUM_`, `TOTAL_`, `TOT_` | `.Tot` | Acumulador / totalizador interno |

**Ejemplos reales verificados en el PLC piloto:**

- `SCL_03` (sin ningún nombre de instrumento en sí mismo) → se rastreó el cableado del diagrama de bloques y se confirmó que alimenta a `CCV_S7_PT_VAP_VG2` → pasa a ser **`700_PT_006.Raw`**.
- `ACUM_FT_JUGO_CLARO` → **`500_FT_001.Tot`**.

### Regla física obligatoria: `.Tot` solo aplica a Flujo o Cantidad (F/Q)

Un acumulador (`.Tot`) **solo tiene sentido físico sobre variables de Caudal (F) o Cantidad (Q)** — son las únicas magnitudes que se pueden integrar/totalizar en el tiempo de forma coherente (ej. litros acumulados, toneladas acumuladas).

**Una Presión (`PT`), Temperatura (`TT`) o Nivel (`LT`) nunca lleva `.Tot`.** Si un tag heredado sugiere lo contrario (ej. `ACUM_PT_VAP_ESCAPE`, un "acumulado" sobre una presión), es una **inconsistencia física heredada**, no un dato válido: debe marcarse para revisión de ingeniería de campo antes de migrarlo, nunca asumirse ni forzarse automáticamente.

Cuando un tag interno no puede vincularse con certeza a ningún instrumento (por nombre ni por cableado), **no se inventa el enlace**: queda como lógica de estado con el prefijo de área correspondiente (ej. `700_ARRANQUE_PLANTA`) o, si ni el área puede determinarse con evidencia sólida, se deja pendiente de revisión manual antes que asumir un dato incorrecto.

---

## 5. Flujo de Trabajo para Nuevos Tags

Antes de que cualquier tag nuevo entre al SCADA o se cargue en un PLC, debe pasar por esta secuencia:

1. **Clasificar**: ¿Es un instrumento físico real (Mundo A - ISA) o una variable de software interna (Mundo B - UDT)? Nunca ambos.
2. **Si es instrumento (Mundo A)**:
   - Identificar el área (tabla de la Sección 3) y la letra de Variable+Función según el diccionario ISA corporativo.
   - Verificar que no repita un número de lazo ya usado en esa área.
   - Confirmar que el nombre no contenga materiales de proceso ni códigos ISA inválidos.
   - Construir el tag: `[AREA]_[VARIABLE+FUNCIÓN]_[NÚMERO]`.
3. **Si es variable interna (Mundo B)**:
   - Identificar a qué instrumento ya numerado pertenece (si corresponde) y asignarlo como miembro con punto (`.Fault`, `.Raw`, `.Sim`, `.Tot`), respetando la regla física del `.Tot` (solo F/Q).
   - Si no pertenece a ningún instrumento (lógica de estado, arranque, control general), nombrarlo en `UPPER_SNAKE_CASE` con el prefijo de área que corresponda.
4. **Validar contra este manual** antes de dar de alta el tag — en caso de duda, consultar con Ingeniería antes de cargarlo al controlador.

---

*Documento vivo: este manual se actualizará a medida que se procesen los 32 PLCs del Ingenio y aparezcan nuevos casos no cubiertos por esta primera versión.*
