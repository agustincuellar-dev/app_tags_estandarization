# Informe integral de avance — 15/09/2026 (martes)
## Fase 2 del reconciliador ISA — endurecimiento y evidencia

**Proyecto:** Estandarización ISA-5.1 — Ingenio La Florida  
**Directorio de trabajo:** `AUTOMATISMO_AGUSTIN`  
**Alcance temporal:** actividades realizadas el 15/09/2026  
**Condición operativa:** auditoría estrictamente de solo lectura

---

## 1. Resumen ejecutivo

Durante el 15/09/2026 se completó el endurecimiento de la Fase 2 del reconciliador topológico ISA sobre los diez archivos L5X definitivos de planta.

La jornada produjo cuatro resultados principales:

1. Se creó el reconciliador endurecido `src/reconciliador_topologico_v3.py`.
2. Se regeneró el catálogo de auditoría en `exports/reconciliacion_catalogo_isa_v3.csv`.
3. Se aislaron tres grupos topológicos que cumplen los criterios técnicos para una eventual numeración futura.
4. Se generó evidencia XML específica de esos tres grupos y una auditoría separada del universo PID/AOI.

La Fase 2 fue aceptada exclusivamente como auditoría. Durante estas tareas:

- no se escribió en SQLite;
- no se insertaron, actualizaron ni eliminaron registros;
- no se ejecutaron migraciones;
- no se asignaron números ISA;
- no se generaron tags ISA definitivos;
- los 11 tags manuales permanecieron protegidos.

---

## 2. Punto de partida de la jornada

Al comenzar la Fase 2 estaban disponibles:

- una base de producción con 11 tags manuales protegidos;
- un backup histórico con 693 registros, utilizado únicamente como inventario;
- diez L5X definitivos en `L5X_Produccion/`;
- un reconciliador anterior con coincidencias por texto y riesgos de mezclar scopes;
- un CSV anterior de 1.006 filas que todavía contenía acciones operativas incompatibles con una auditoría estricta.

```text
CALD_LA_FLORIDA.L5X
CENTRIFUGA_DE_PRIMERA.L5X
Calderas_8_9_10_Desaireador.L5X
DESTILERIA.L5X
DIBACCO.L5X
FABRICA.L5X
Painel_Ctr_Turb_Moenda.L5X
TRAPICHE2022.L5X
USINA_LA_FLORIDA.L5X
cenizas2020.L5X
```

---

## 3. Reconciliador topológico v3

Se desarrolló:

```text
src/reconciliador_topologico_v3.py
```

El motor quedó organizado alrededor de identidades XML y relaciones topológicas demostrables, sin utilizar búsquedas por subcadena.

### 3.1 Identidad exacta

La identidad L5X se definió con los siguientes componentes:

```text
PLC
Controller@Name
DeclarationScope
BaseTag@Name
MemberPath
AliasFor, como evidencia asociada
```

`DeclarationScope` distingue explícitamente:

```text
Controller
Program:<Program@Name>
```

Con este criterio:

- `LT_1` no coincide con `LT_10`;
- tags locales iguales de programas diferentes no se mezclan;
- los miembros estructurados conservan su ruta completa;
- las direcciones de módulo con `:` no se fragmentan;
- una descripción textual no demuestra identidad;
- una definición AOI no se confunde con una instancia de planta.

### 3.2 Identidad de ocurrencia

Las apariciones se conservaron por:

```text
L5X_ID
lenguaje
Program
Routine
Sheet o Rung
NodeID u ordinal
```

Esto permitió diferenciar una identidad declarada de sus apariciones en rutinas y hojas distintas.

---

## 4. Lenguajes y estructuras consideradas

### 4.1 FBD

Se procesó la conectividad pin a pin mediante:

```text
FromID + FromParam → ToID + ToParam
```

Los IDs se mantuvieron scoped por PLC, programa, rutina y hoja.

### 4.2 Ladder / RLL

Se diferenciaron lecturas y escrituras para instrucciones como:

```text
MOV, COP, CPS, SCP
OTE, OTL, OTU
```

También se conservaron las llamadas AOI textuales y sus argumentos.

### 4.3 Structured Text

Se analizaron asignaciones con la forma:

```text
destino := expresión;
```

El lado izquierdo se trató como escritura y las referencias del lado derecho como lecturas.

### 4.4 AOI

Las definiciones AOI se trataron como plantillas. La dirección de parámetros se obtuvo de `Usage=Input`, `Output` o `InOut`.

Una definición no se contó por sí sola como lazo de planta. La evidencia de control requirió PID/PIDE dentro del cuerpo o una cadena equivalente demostrada.

---

## 5. Modelo de confianza y bloqueo

Se separaron tres dimensiones:

```text
Confianza_Fisica
Confianza_Pertenencia_Lazo
Confianza_Funcion_ISA
```

La confianza final adopta siempre el peor nivel.

Los siguientes problemas impiden acciones operativas y obligan a revisión:

- ciclos;
- múltiples escritores;
- múltiples entradas;
- múltiples destinos;
- scope ambiguo;
- extremo físico compartido;
- entrada no demostrada;
- elemento final no demostrado;
- actuador no identificado;
- función ISA no demostrada.

Se eliminaron las acciones antiguas:

```text
AGREGAR_CON_LAZO
RENUMERAR_CON_LAZO
```

Las acciones de auditoría quedaron limitadas a:

```text
CANDIDATO_ENTRADA
CANDIDATO_SALIDA
CANDIDATO_PID
REVISION_LAZO
REVISION_MANUAL
SIN_LAZO
CONSERVAR_SIN_CAMBIOS
```

El CSV v3 no contiene una columna `Tag_Propuesto_ISA`.

---

## 6. Determinismo

Durante las pruebas se detectó un defecto real: el recorrido de aristas almacenadas en conjuntos producía resultados distintos entre procesos según `PYTHONHASHSEED`.

Antes de la corrección, el mismo corpus llegó a informar 2, 3 y 7 grupos habilitables.

Se corrigió mediante:

- ordenamiento de aristas;
- vecinos ordenados;
- colas de recorrido deterministas;
- orden estable de grupos y filas;
- comparación en subprocesos con semillas diferentes.

El CSV v3 final resultó byte-idéntico entre distintas semillas.

---

## 7. Resultado de `reconciliacion_catalogo_isa_v3.csv`

Archivo generado:

```text
exports/reconciliacion_catalogo_isa_v3.csv
```

Resultado:

```text
Filas: 973
SHA-256: 01e488c2d771af6c9da38fa89c5ff422e2f2b8c6d1f2c62da82b5cbde8f12616
```

### 7.1 Acciones registradas

| Acción | Filas |
|---|---:|
| SIN_LAZO | 578 |
| REVISION_LAZO | 271 |
| REVISION_MANUAL | 99 |
| CONSERVAR_SIN_CAMBIOS | 11 |
| CANDIDATO_PID | 8 |
| CANDIDATO_ENTRADA | 3 |
| CANDIDATO_SALIDA | 3 |

### 7.2 Métricas topológicas informadas al cierre de la Fase 2

| Métrica | Cantidad |
|---|---:|
| Entradas únicas | 17 |
| Salidas únicas | 50 |
| Conteo PID inicial del reconciliador | 209 |
| Grupos completos entrada–PID–salida | 10 |
| Grupos entrada–PID | 2 |
| Grupos PID–salida | 38 |
| Señales físicas sin lazo | 578 |

### 7.3 Ambigüedades principales

| Motivo | Cantidad |
|---|---:|
| Entrada física no demostrada | 201 |
| Elemento final no demostrado | 165 |
| Extremo compartido entre lazos | 9 |
| Múltiples destinos | 5 |
| Múltiples entradas | 2 |

---

## 8. Diferencias respecto del CSV anterior

La comparación registró:

```text
CSV anterior: 1.006 filas
CSV v3:        973 filas
Diferencia:    -33 filas
```

Se rechazaron coincidencias que el método anterior consideraba encontradas por subcadena o texto incidental.

Cambios principales:

- encontrados por identidad real: 863;
- 32 coincidencias anteriores dejaron de aceptarse;
- se eliminaron acciones de inserción y renumeración;
- se separaron las tres confianzas;
- se agregó bloqueo por extremos compartidos;
- se mantuvieron los motores como elementos finales sin convertirlos en válvulas;
- no se propuso ningún número ISA.

---

## 9. Grupos completos y habilitación futura

Se detectaron diez grupos completos. Solo tres cumplieron simultáneamente:

1. identidad XML exacta;
2. scope inequívoco;
3. área demostrada;
4. variable ISA demostrada;
5. una entrada;
6. un controlador;
7. un elemento final;
8. ausencia de escritores alternativos;
9. ausencia de extremos compartidos;
10. confianza final ALTA.

### 9.1 Tres grupos habilitados para evidencia

#### Calderas — nivel del desaireador

```text
PLC: Calderas_8_9_10_Desaireador
Program: DES
Routine: DES_LC_DESAIREADOR
Scope: Program:DES
Controlador: B_DES_LC_DOMO
Entrada: DES_S1_LT_TK_DESAIREADOR
Salida: DES_S6_PV_VALVULA_EVACUACION_DES
Área inferida: 300
Variable ISA: L
```

#### Destilería — caudal de agua a mosto

```text
PLC: DESTILERIA
Program: FERMENTACION
Routine: PID_FERMENTACION
Scope: Program:FERMENTACION
Controlador: B_Ctrol_FT_AGUA_A_MOSTO
Entrada: Slot_FT_AGUA
Salida: Slot_PV_VALVULA_CAUDAL_AGUA
Área inferida: 200
Variable ISA: F
```

#### Destilería — nivel del tanque de agua potable

```text
PLC: DESTILERIA
Program: FERMENTACION
Routine: PID_FERMENTACION
Scope: Program:FERMENTACION
Controlador: B_Ctrol_TK_AGUA_POTABLE
Entrada: Slot_LT_TK_AGUA_POTABLE
Salida: Slot_PV_VALVULA_NIVEL_TK_AGUA
Área inferida: 200
Variable ISA: L
```

Estos tres grupos quedaron habilitados únicamente para generar evidencia. No quedaron habilitados para escribir en la base ni para numerar.

### 9.2 Siete grupos completos bloqueados

Los otros siete grupos completos quedaron bloqueados por:

- extremos compartidos;
- múltiples destinos;
- múltiples entradas simultáneas.

Entre ellos se registraron:

```text
B_DES_PC_DESAIREADOR
B_DES_PC_VALVULA_20_10
CONTROL_PRESION_2_20_10
B_Ctrol_FT_MELAZA
B_Ctrol_LT_TK_ENCALADO
B_Ctrol_LT_TK_PESADO
B_CL_TOLVA
```

---

## 10. Evidencia específica de los tres grupos

Se creó:

```text
src/generar_evidencia_fase2.py
```

Y se generó:

```text
exports/evidencia_3_lazos_habilitados.csv
```

El archivo contiene una fila por grupo e incluye:

- PLC, Program, Routine y Scope;
- instancia única del controlador;
- tipo de bloque o AOI;
- pin de entrada;
- camino XML completo desde la entrada hasta el controlador;
- pin de salida;
- camino XML completo hasta el elemento final;
- tag de entrada y salida;
- `AliasFor` y dirección física;
- área inferida y evidencia utilizada;
- variable ISA inferida y evidencia utilizada;
- confirmación de que la ocurrencia no procede de `AddOnInstructionDefinitions`;
- búsqueda inversa de otros controladores que usen la misma entrada o salida;
- confianza final y observaciones de repetición.

Resultado:

```text
Grupos documentados: 3
Confianza final: ALTA en los 3
Otros controladores sobre la misma entrada: NO
Otros controladores sobre la misma salida: NO
Números ISA asignados: 0
```

---

## 11. Auditoría PID/AOI generada el 15/09

Se generó el archivo solicitado:

```text
exports/auditoria_209_pid.csv
```

El nombre conserva el conteo heredado de 209, pero el análisis scope-aware produjo 213 identidades declaradas distintas por:

```text
(PLC, scope, instancia)
```

El archivo tiene 235 filas distribuidas así:

| Categoría registrada el 15/09 | Filas |
|---|---:|
| EJECUTADA_CONTROLLER_PROGRAM | 213 |
| SOLO_DEFINICION_AOI | 3 |
| REPETICION_MISMA_INSTANCIA | 19 |

La diferencia 209 → 213 se originó al conservar nombres iguales en scopes distintos en lugar de colapsarlos por nombre.

### Nota de control posterior

Una validación posterior, realizada al preparar el presente informe, determinó que la categoría de 213 estaba construida desde declaraciones de tipo PID/AOI y no demostraba por sí sola una invocación ejecutable.

La interpretación correcta es:

```text
Declaraciones únicas por PLC+scope+instancia: 213
Invocaciones XML exactas demostradas:        145
Declaraciones sin invocación XML:             68
```

Asimismo, el análisis posterior encontró 32 definiciones AOI con control nativo y 6 sin ruta de invocación XML desde Programs, incluyendo envoltorios anidados.

Esta nota no modifica lo ejecutado el 15/09; corrige la interpretación del conteo para evitar presentar una declaración como ejecución demostrada. El XML ejecutable tampoco demuestra ejecución efectiva en runtime.

---

## 12. Pruebas ejecutadas durante la jornada

Al finalizar la generación de evidencia se habían incorporado pruebas para:

- identidad exacta frente a subcadenas;
- separación de scopes;
- peor confianza dominante;
- bloqueo de acciones operativas en grupos problemáticos;
- trazado FBD;
- lectura y escritura Ladder;
- asignación Structured Text;
- dirección real de parámetros AOI;
- no convertir motores en válvulas;
- extremos compartidos;
- determinismo entre procesos;
- hash de ambas bases antes y después;
- generación de evidencia de exactamente tres grupos;
- ausencia de `Tag_Propuesto_ISA` en la evidencia;
- clasificación separada de PID/AOI.

Estado registrado:

```text
72 pruebas — OK
compileall — OK
git diff --check — OK
DB actual sin cambios — true
Backup histórico sin cambios — true
```

---

## 13. Seguridad de datos

Toda la jornada se mantuvo en modo de auditoría:

```text
SQLite production: solo lectura
Migraciones: 0
INSERT: 0
UPDATE: 0
DELETE: 0
Números ISA asignados: 0
Tags propuestos definitivos: 0
```

Las herramientas de evidencia trabajaron sobre XML y CSV. Las bases permanecieron fuera de cualquier ruta de escritura.

Estado protegido:

```text
DB actual: 11 tags manuales
Backup histórico: 693 tags
Integridad SQLite: ok
```

---

## 14. Archivos creados o actualizados el 15/09

### Código

```text
src/reconciliador_topologico_v3.py
src/generar_evidencia_fase2.py
```

### Pruebas

```text
tests/test_reconciliador_topologico_v3.py
tests/test_generar_evidencia_fase2.py
```

### Exportaciones

```text
exports/reconciliacion_catalogo_isa_v3.csv
exports/evidencia_3_lazos_habilitados.csv
exports/auditoria_209_pid.csv
```

### Documentación

```text
docs/Fase2_Reconciliador_Topologico_v3.md
docs/Resumen_Ejecutivo_Avance_150926.md
```

---

## 15. Estado al cierre del 15/09

La Fase 2 quedó aceptada únicamente como auditoría.

Al cierre de la jornada:

- el reconciliador v3 era determinista;
- la identidad XML era exacta y scoped;
- las acciones operativas de alta y renumeración estaban eliminadas;
- los tres grupos habilitados tenían evidencia XML completa;
- los demás grupos permanecían en revisión;
- no existía todavía una numeración preliminar autorizada;
- ninguna base había sido modificada.

El siguiente paso previsto era una fase separada de cierre de lazos y propuesta histórica de numeración, también en modo estrictamente solo lectura. Esa fase no forma parte del avance del 15/09.
