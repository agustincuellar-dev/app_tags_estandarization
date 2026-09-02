# Resumen Ejecutivo de Avance
## Proyecto de Estandarización de Instrumentación y Control — Ingenio La Florida

**Fecha:** 26 de agosto de 2026
**Informe anterior:** `Resumen_Ejecutivo_Avance_180826` (18/08/2026)

---

## 1. Resumen del período

Período con un giro de enfoque importante: por primera vez, el proyecto tagueó instrumentación que **no viene de un `.L5X`** — un proyecto físico nuevo en Destilería (columna de lavado de gases CO2), reconstruido a partir de un data-sheet técnico y las notas de campo del ingeniero. Ese ejercicio, a su vez, disparó dos cosas más grandes: un hallazgo real de datos mal etiquetados en el código ya auditado, y una **corrección formal de alcance** por parte de Ingeniería que redefine qué es y qué no es tageable bajo ISA-5.1 de acá en adelante. Tres frentes:

1. Tagueo de la Columna de Lavado de Gases CO2 (Destilería) — primer caso de instrumentación 100% física, sin origen en código de PLC.
2. Hallazgo colateral: la familia `PT_VAPOR_ENTRADA*` en Destilería, probable "Peso Total" mal homologado a "Presión Transmisor".
3. Corrección de alcance del proyecto — nueva regla de Ingeniería sobre qué se tagea, incorporada al Manual de Estandarización (v0.1 → v0.2).

---

## 2. Columna de Lavado de Gases CO2 — primer tagueo desde cero

Un proyecto nuevo en Destilería (columna recuperadora de CO2/alcohol, fabricante NEW PRO Engenharia) necesitaba tagueo de instrumentación **antes** de que exista ningún `.L5X` — el PLC todavía no está programado. Regla acordada desde el arranque: se discute y valida el criterio de tagueo en conversación, y recién después se carga en Tags App — nunca al revés.

### 2.1 Reconstrucción del inventario

Se combinaron dos fuentes: el data-sheet técnico del fabricante (tabla de bocas de conexión) y tres fotos del cuaderno de campo del ingeniero, que resolvieron ambigüedades que el plano solo no develaba. Resultado: **3 lazos PID completos**, confirmados por una nota explícita del ingeniero ("Programar controles columna: 1. PID Nivel, 2. PID Alimentación Agua, 3. PID Presión de columna — 3 entradas analógicas, 3 salidas analógicas"):

| Lazo | Entrada (AI) | Controlador | Salida (AO) |
|---|---|---|---|
| Presión de columna | `200_PT_NNN` | `200_PIC_NNN` | `200_PV_NNN` — válvula 16", CO2 desde cubas |
| Nivel de columna | `200_LT_NNN` | `200_LIC_NNN` | `200_LV_NNN` — drena a `TK_FLEGNAZA` |
| Alimentación de agua | `200_FT_NNN` | `200_FIC_NNN` | `200_FV_NNN` — agua de lavado |

Más 3 visores locales del data-sheet (`200_LG_NNN` × 3), 2 entradas RTD en reserva sin asignar, y 3 equipos con convención corporativa (no ISA numerada): `COL_CO2_ALCOHOL`, `TK_FLEGNAZA`, `BBA_FLEGMA_01`/`02`.

### 2.2 La ambigüedad PT vs. PDT — resuelta por peso de evidencia

El primer relevamiento verbal mencionó una válvula gobernada por presión diferencial. Investigando con el ingeniero surgió una duda real: ¿el transmisor de presión es `PT` o `PDT`? Se resolvió **no por autoridad de una sola respuesta, sino por peso de evidencia documental**: el data-sheet del fabricante dice `PT`, el cuaderno de un segundo ingeniero dice `PT`, y la primera respuesta verbal del mismo ingeniero también fue `PT` — el `PDT` apareció recién después de una batería de preguntas técnicas, patrón típico de auto-duda inducida más que de corrección real. Se cerró con `PT`.

### 2.3 Carga manual — guía entregada, no ejecutada por el asistente

Como esta instrumentación no sale de un `.L5X`, no hay carga masiva posible. Se entregó al usuario una guía paso a paso (Área/Variable/Función → Paso 2 → Paso 3 de Tags App) para dar de alta los 11 tags él mismo, con recomendación explícita de dejar trazabilidad en el campo Comentarios de cada lazo (qué otro tag es su par en el mismo lazo, ya que la app no ata automáticamente `PT`↔`PIC`↔`PV` entre sí).

---

## 3. Hallazgo colateral: la familia `PT_VAPOR_ENTRADA*` en Destilería

Durante la carga, el usuario notó que ya existían varios `200_PT_0XX` en la base — y sospechó, con buen criterio, que no todos eran transmisores reales. Se investigó la fuente:

<pre>PT_VAPOR_ENTRADA                  &rarr; 200_PT_021  (base)
PT_VAPOR_ENTRADA_ACUM_DIA_ACT     &rarr; 200_PT_022  (acumulado dia actual)
PT_VAPOR_ENTRADA_ACUM_DIA_ANT     &rarr; 200_PT_023  (acumulado dia anterior)
PT_VAPOR_ENTRADA_ACUM_HR_ACT      &rarr; 200_PT_024  (acumulado hora actual)
PT_VAPOR_ENTRADA_ACUM_HR_ANT      &rarr; 200_PT_025  (acumulado hora anterior)
PT_VAPOR_ENTRADA_ACUM_TOTAL       &rarr; 200_PT_026  (acumulado total)</pre>

Las 6 viven en la misma rutina, `ACUMULADOS_DESTILERIA` (Program `JW`). Más contundente todavía: el propio motor de auditoría **ya había marcado una violación física sobre esta familia hace meses**, sin que nadie le diera seguimiento — un acumulador (`.Tot`) no tiene sentido físico sobre una Presión, solo sobre Caudal/Cantidad (regla ya documentada en el Manual, Sección 4). Hipótesis de trabajo: "PT" en este contexto probablemente signifique **"Peso Total"** de vapor (común en ingenios, medido en toneladas para el balance de calderas), no "Presión Transmisor" — homónimo que el motor no puede distinguir por nombre solo. Queda pendiente de confirmación con Ingeniería; no se tocó nada de esta familia todavía.

Este hallazgo terminó siendo el disparador directo de la corrección de alcance de la Sección 4.

---

## 4. Corrección de alcance del proyecto (Ingeniería, 19/08/2026)

Con la experiencia acumulada de auditar PLCs completos, Ingeniería acotó formalmente qué entra al universo ISA. Se incorporó como nueva **Sección 2.1** del Manual de Estandarización (que pasa de v0.1 a **v0.2**):

- **Qué se tagea bajo ISA, y nada más:** transmisores, válvulas de control y válvulas de seguridad — el lazo de control con instrumento físico real. Regla textual del ingeniero: *"se tagea lo que se controla"*.
- **Cómo identificar la Variable de Proceso real** entre una familia de nombres parecidos: en el programa, la cadena es `Entrada Analógica cruda → Bloque de Escalado (SCP/SCL) → primera salida en unidades de ingeniería`. Esa primera salida es la única candidata a tag ISA. Todo lo que se calcula después (acumulados, promedios, alarmas derivadas) **no** es la variable de proceso y queda fuera de alcance, aunque conserve el mismo prefijo de nombre.
- El caso `PT_VAPOR_ENTRADA*` (Sección 3) quedó documentado en el Manual como el ejemplo real que motivó la corrección.

El Manual actualizado se publicó en PDF (`Manual_Estandarizacion.pdf`).

---

## 5. Material de difusión

A pedido del usuario (visita externa a recibir una explicación del proyecto), se redactó un texto de presentación de alto nivel — qué problema resuelve el proyecto, cómo funciona el motor de auditoría, cómo se valida contra la planta viva, los números actuales del dashboard, y la corrección de alcance recién incorporada — pensado para leerse o parafrasearse en una reunión, no como documento técnico.

---

## 6. Estado actual y próximos pasos

**Situación:** Manual de Estandarización en v0.2 con la corrección de alcance formalizada; primer caso de tagueo físico (sin `.L5X` de origen) resuelto conceptualmente y con guía de carga entregada; un hallazgo de datos mal etiquetados documentado y pendiente de confirmación.

**Prioridades sugeridas:**

1. Confirmar con Ingeniería el significado real de `PT_VAPOR_ENTRADA*` (Presión vs. Peso Total) y, si corresponde, reclasificar esa familia bajo la función `Q` (Totalizador) en vez de `PT`.
2. Terminar la carga manual de los 11 tags de la Columna CO2 en Tags App y verificar la identidad de los 3 lazos.
3. Revisar, con la nueva regla de alcance (Sección 2.1 del Manual), si hay otras familias de acumulados/derivados ya cargadas como `FUNCIONAL_ISA` en los 12 PLCs canónicos que deberían salir de ese universo — candidato directo a una pasada de limpieza sobre `resultados/`.
4. Sigue pendiente: exportar `LA_FLORIDA` (IP `.160`), Excel de Yanco de Fermentación (`.131`/`.132`) para descongelar `DESTILERIA_RECUPERADO`/`vinaza`, y los 1.136 conflictos de numeración histórico.

---

## 7. Nota metodológica

La corrección de alcance de la Sección 4 no es retroactiva por sí sola: los 12 PLCs canónicos ya auditados conservan su clasificación tal como está en `resultados/` hasta que se haga una revisión explícita bajo la nueva regla. El hallazgo de la Sección 3 es un caso puntual documentado, no una reclasificación masiva — evitar tratarlo como tal hasta confirmación de campo.
