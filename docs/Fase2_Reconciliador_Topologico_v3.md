# Fase 2 — Reconciliador topológico endurecido (CSV v3)

**Fecha:** 14/09/2026
**Módulo:** `src/reconciliador_topologico_v3.py`
**Salida:** `exports/reconciliacion_catalogo_isa_v3.csv`
**Ninguna base fue modificada. No se eliminó ningún registro. No se ejecutó ninguna migración.**

---

## 1. Endurecimientos implementados

| Requisito | Estado | Cómo se implementó |
|---|---|---|
| Fin de la búsqueda por subcadena | ✅ | `Encontrado_L5X` se resuelve contra el índice de **declaraciones XML**; nunca contra el texto del archivo |
| Clave de identidad exacta | ✅ | `(PLC, alcance Controller/Program, tag base, miembro, AliasFor)` |
| Tags locales no se mezclan | ✅ | Declaraciones indexadas por `(scope, nombre)`; resolución local-antes-que-global |
| Tres confianzas separadas | ✅ | `Confianza_Fisica`, `Confianza_Pertenencia_Lazo`, `Confianza_Funcion_ISA` + `Confianza_Final` |
| Peor confianza domina | ✅ | `worst_confidence()` aplicado en cada agregación |
| Sin acciones operativas en grupos problemáticos | ✅ | `action_for()` devuelve `REVISION_LAZO` si hay problemas |
| Acciones nuevas | ✅ | `CANDIDATO_ENTRADA`, `CANDIDATO_SALIDA`, `CANDIDATO_PID`, `REVISION_LAZO` |
| Sin números ISA | ✅ | El CSV v3 **no tiene columna** `Tag_Propuesto_ISA` |
| FBD `FromID/FromParam/ToID/ToParam` | ✅ | Grafo por arista de pin, no solo por nodo |
| Cruces entre rutinas | ✅ | Aristas globales por identidad; el trazado cruza rutinas y hojas |
| Ladder lectura/escritura | ✅ | Lexer de texto neutral; `MOV/COP/CPS/SCP` destino, `OTE/OTL/OTU` escritura |
| Structured Text `:=` | ✅ | Parseo por línea con destino y referencias del lado derecho |
| AOI por definición y pines reales | ✅ | `Parameter Usage` Input/Output + cuerpo con PID/PIDE nativo; sin exigir nombres |
| Motor ≠ válvula | ✅ | `classify_output()` separa MOTOR / VALVULA / DESCONOCIDO; motor queda sin función ISA |
| Extremo compartido entre lazos | ✅ | Si un extremo pertenece a más de un controlador, todos los grupos involucrados pasan a `REVISION_LAZO` |
| Resultado reproducible | ✅ | Aristas y vecinos ordenados; salida byte-idéntica entre semillas de `PYTHONHASHSEED` |

---

## 2. Entregables

### CSV v3

```text
exports/reconciliacion_catalogo_isa_v3.csv
973 filas · 16 columnas · 168 KB · sin Tag_Propuesto_ISA
sha256 01e488c2d771af6c9da38fa89c5ff422e2f2b8c6d1f2c62da82b5cbde8f12616
```

Columnas: `PLC_Origen`, `Tag_Anterior`, `Tag_Original_PLC`, `Encontrado_L5X`, `Alcance`,
`Rol_Propuesto`, `Area`, `Variable`, `Funcion`, `Loop_ID`, `Confianza_Fisica`,
`Confianza_Pertenencia_Lazo`, `Confianza_Funcion_ISA`, `Confianza_Final`, `Accion`, `Motivo`.

### Métricas solicitadas

| Métrica | Valor |
|---|---:|
| Entradas únicas | **17** |
| Salidas únicas | **50** |
| PID únicos | **209** |
| Grupos completos entrada–PID–salida | **10** |
| Grupos entrada–PID (sin salida demostrada) | **2** |
| Grupos PID–salida (sin entrada demostrada) | **38** |
| Señales físicas sin lazo | **578** |
| Lazos candidatos totales | 213 |

### Ambigüedades por motivo

| Motivo | Casos |
|---|---:|
| Entrada física no demostrada | 201 |
| Elemento final no demostrado | 165 |
| Extremo compartido entre lazos | 9 |
| Múltiples destinos | 5 |
| Múltiples entradas | 2 |

### Diferencias respecto del CSV anterior

| Aspecto | v2 | v3 |
|---|---:|---:|
| Filas | 1006 | 973 |
| `Encontrado_L5X = SI` | 895 | **863** (−32) |
| `AGREGAR_CON_LAZO` | presente | **eliminada** |
| `RENUMERAR_CON_LAZO` | presente | **eliminada** |
| `CANDIDATO_ENTRADA` | — | 3 |
| `CANDIDATO_SALIDA` | — | 3 |
| `CANDIDATO_PID` | — | 8 |
| `REVISION_LAZO` | — | 271 |
| `SIN_LAZO` | — | 578 |

Las 32 identidades que la v2 daba por encontradas y la v3 rechaza eran coincidencias
por subcadena (descripciones, nombres más largos o definiciones AOI), no declaraciones exactas.

---

## 3. Criterio de habilitación futura de numeración

Solo puede recibir número un grupo que cumpla **todo**:

1. identidad XML exacta (declaración indexada por scope);
2. scope inequívoco (una única resolución);
3. área y variable demostradas;
4. exactamente una entrada;
5. exactamente un controlador;
6. exactamente un elemento final;
7. sin escritores alternativos, sin extremos compartidos y sin problemas abiertos.

**Estado actual de ese criterio:**

```text
Grupos con entrada + PID + salida: 10
Con cardinalidad uno-a-uno y sin ningún problema: 3
De esos, con confianza final ALTA: 3
```

Los 3 grupos que hoy cumplen el criterio completo:

```text
Calderas_8_9_10_Desaireador/Program:DES/B_DES_LC_DOMO
    DES_S1_LT_TK_DESAIREADOR      -> DES_S6_PV_VALVULA_EVACUACION_DES

DESTILERIA/Program:FERMENTACION/B_Ctrol_FT_AGUA_A_MOSTO
    Slot_FT_AGUA                  -> Slot_PV_VALVULA_CAUDAL_AGUA

DESTILERIA/Program:FERMENTACION/B_Ctrol_TK_AGUA_POTABLE
    Slot_LT_TK_AGUA_POTABLE       -> Slot_PV_VALVULA_NIVEL_TK_AGUA
```

No se les asignó número: quedan como **asociaciones topológicas estables** a la espera
de la decisión de Ingeniería.

### Por qué los otros 7 grupos completos no habilitan

| Grupo | Motivo |
|---|---|
| `B_DES_PC_DESAIREADOR` | Extremo compartido entre lazos |
| `B_DES_PC_VALVULA_20_10` | Extremo compartido con `CONTROL_PRESION_2_20_10` |
| `CONTROL_PRESION_2_20_10` | Extremo compartido con `B_DES_PC_VALVULA_20_10` |
| `B_Ctrol_FT_MELAZA` | Extremo compartido entre lazos |
| `B_Ctrol_LT_TK_ENCALADO` | Múltiples destinos (2 válvulas) |
| `B_Ctrol_LT_TK_PESADO` | Múltiples destinos (2 válvulas) |
| `B_CL_TOLVA` | Extremo compartido + 8 entradas simultáneas |

---

## 4. Verificación ejecutada

```text
Suite completa: Ran 70 tests — OK
compileall — OK
git diff --check — OK
db_actual_unchanged = true
backup_historico_unchanged = true
CSV byte-idéntico entre PYTHONHASHSEED=0 y PYTHONHASHSEED=987654
```

Pruebas obligatorias incorporadas (`tests/test_reconciliador_topologico_v3.py`, 13 pruebas):

- `LT_1` no coincide con `LT_10`.
- Dos tags locales iguales en programas distintos no se mezclan.
- La peor confianza domina.
- Un lazo problemático nunca recibe acción operativa.
- Trazado entre rutinas FBD.
- Lectura/escritura Ladder.
- Asignación Structured Text.
- AOI detectada por definición y dirección de pines, no por nombre.
- Motor no se convierte en válvula.
- Extremo compartido entre lazos impide candidato.
- Resultado estable entre semillas de hash.
- Asociaciones ordenadas de forma determinista.
- Hash de ambas DB idéntico antes y después.

---

## 5. Defecto encontrado y corregido durante la fase

La primera versión del trazado producía resultados **distintos entre ejecuciones**
(3, 2 y 7 grupos habilitables en corridas sucesivas) porque recorría el conjunto de
aristas sin orden definido y el orden de iteración de un `set` depende de la semilla
de hash del proceso.

Corrección: las aristas y los vecinos se recorren en orden estable y las asociaciones
se devuelven ordenadas por `Loop_ID`. Se agregó una prueba que ejecuta el cálculo en
dos subprocesos con semillas distintas y compara la huella completa.

---

## 6. Límites declarados

- La rutina SFC ejecutable no está soportada: se declara fuera de alcance.
- Dos rutinas RLL sin `RLLContent` se tratan como opacas, no como vacías.
- Los cuerpos AOI se analizan como plantilla, nunca como lazos de planta.
- `VisiblePins` es presentación: la dirección de datos proviene de `Wire` y `Parameter Usage`.
- Persisten 201 grupos sin entrada física demostrada y 165 sin elemento final demostrado;
  se resuelven con más evidencia de campo o de P&ID, no por inferencia automática.
- El emparejamiento de los 693 históricos usa el nombre exacto declarado en el PLC indicado
  por `plc_origen`; los 30 no encontrados y los 69 sin nombre recuperable quedan en revisión.
