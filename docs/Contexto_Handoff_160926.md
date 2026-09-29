# Contexto de traspaso — Proyecto ISA-5.1 Ingenio La Florida
**Fecha del traspaso:** 16/09/2026
**Proyecto:** `C:\Users\Administrador\Downloads\AUTOMATISMO_AGUSTIN`
**Motivo:** continuar el trabajo en un chat nuevo con contexto reducido.

---

## 1. Reglas permanentes (no negociables)

Estas reglas vienen del usuario y se repitieron durante todo el trabajo. **Romperlas invalida cualquier entrega.**

1. Trabajar **únicamente** dentro de `C:\Users\Administrador\Downloads\AUTOMATISMO_AGUSTIN`.
2. SQLite **siempre solo lectura**: URI `mode=ro` + `PRAGMA query_only=ON`, conexiones cerradas explícitamente (`contextlib.closing`).
3. **Salidas exclusivamente en CSV.** Nunca escribir en bases, nunca migrar, nunca purgar.
4. **No asignar números ISA definitivos sin autorización explícita del usuario.**
5. No tocar los **11 tags manuales** de producción.
6. No eliminar funcionalidades existentes; no cambiar el tema de la app (`ttkbootstrap` `darkly`).
7. Ante ambigüedad: **preferir evidencia honesta y bloqueo** antes que inventar un resultado.
8. Los números de lazo **no se reutilizan** si ya existieron: un número retirado queda registrado y no se recicla.
9. Explicar la arquitectura **antes** de reescribir el motor de auditoría.

---

## 2. Entorno

| Elemento | Valor |
|---|---|
| Intérprete correcto | `C:/Users/Administrador/AppData/Local/Programs/Python/Python313/python.exe` |
| Intérprete del PATH | Python 3.11 — **NO sirve**, no tiene `ttkbootstrap` |
| Shell | bash (git-bash / MSYS), no PowerShell |
| Paquetes Python313 | `ttkbootstrap==2.2.2`, `reportlab`, `openpyxl`, `pymupdf` |
| `openpyxl` en el kernel `execute_code` | **NO disponible** — usar `terminal` con el Python 313 para leer `.xlsx` |

---

## 3. Estado de las bases (verificado)

| Base | Ruta | Tags | SHA-256 |
|---|---|---:|---|
| Producción | `app_etiquetas/tags_ingenio.db` | 11 | `c450eb3f017a7f51636aaca8df5194f9385b084f05a6ac0450902738c384ca17` |
| Histórica pre-purga | `app_etiquetas/backups/tags_ingenio_antes_purga_20260911_110901_186931.db` | 693 | `ee1df1c901f254bd1a97785a709f3ee154c0ac0503657866d536d1325778c440` |

`PRAGMA integrity_check = ok` en ambas.

**Números ocupados en producción (los 11 manuales):**
- Área 200: `004` (PIC/PIT/PV), `035` (LIC/LT/LV), `080` (FIC/FT/FV)
- Área 250: `001`, `002` (PV)

Backups adicionales en `app_etiquetas/backups/`: pre-alta-confianza, pre-purga, pre-eliminación de `200_PT_004`.

---

## 4. Los 3 lazos habilitados (Fase 2 — auditoría aceptada)

Los tres están en `L5X_Produccion/` y tienen confianza ALTA, identidad XML exacta, scope inequívoco, una entrada, un controlador y una salida.

### 4.1 Nivel del desaireador — área 300

```text
PLC:      Calderas_8_9_10_Desaireador
Program:  DES
Routine:  DES_LC_DESAIREADOR
Scope:    Program:DES
Controlador: B_DES_LC_DOMO (AOI CONTROL_NIVEL)
Entrada:  DES_S1_LT_TK_DESAIREADOR  → AliasFor Desaireador:2:I.Ch[4].Data
Salida:   DES_S6_PV_VALVULA_EVACUACION_DES → AliasFor Desaireador:6:O.Ch4Data
Variable ISA: L
```

### 4.2 Caudal de agua a mosto — área 200

```text
PLC:      DESTILERIA
Program:  FERMENTACION
Routine:  PID_FERMENTACION
Scope:    Program:FERMENTACION
Controlador: B_Ctrol_FT_AGUA_A_MOSTO (AOI CONTROL_NIVEL)
Entrada:  Slot_FT_AGUA → jw_fermerntacion_2022:6:I.Ch[0].Data
Salida:   Slot_PV_VALVULA_CAUDAL_AGUA → jw_fermerntacion_2022:10:O.Ch2Data
Variable ISA: F
```

### 4.3 Nivel del tanque de agua potable — área 200

```text
PLC:      DESTILERIA
Program:  FERMENTACION
Routine:  PID_FERMENTACION
Scope:    Program:FERMENTACION
Controlador: B_Ctrol_TK_AGUA_POTABLE (AOI CONTROL_NIVEL)
Entrada:  Slot_LT_TK_AGUA_POTABLE → jw_fermerntacion_2022:5:I.Ch[7].Data
Salida:   Slot_PV_VALVULA_NIVEL_TK_AGUA → jw_fermerntacion_2022:11:O.Ch1Data
Variable ISA: L
```

---

## 5. Entregable vigente: propuesta concreta de 9 tags

**Archivo:** `exports/propuesta_numeracion_3_lazos.csv`
**Tamaño:** 10.064 bytes — **SHA-256 `8c3ae8da184ee821c413a02e9d173d75ecf6b1c9263f4d80f7579458f3910235`**
**Filas:** 9 (3 lazos × 3 roles: ENTRADA / CONTROLADOR / SALIDA)

| Lazo | Área | Número | Tags propuestos |
|---|---:|---:|---|
| Desaireador (nivel) | 300 | **083** | `300_LT_083`, `300_LIC_083`, `300_LV_083` |
| Agua a mosto (caudal) | 200 | **081** | `200_FT_081`, `200_FIC_081`, `200_FV_081` |
| Agua potable (nivel) | 200 | **082** | `200_LT_082`, `200_LIC_082`, `200_LV_082` |

Todos los registros tienen `Estado_Propuesta = PROPUESTA_CONCRETA_PARA_REVISION — NO_INSERTAR` y `Escritura_SQLite = NO`.

### 5.1 Verificación 1 — área del desaireador (CONFIRMADA)

El desaireador pertenece al **área 300 (Calderas / Generación de Vapor)**. Fuentes:

- `docs/Manual_Estandarizacion.md` líneas 83-90 — tabla oficial: `300 = Calderas / Generación de Vapor`.
- `docs/Roadmap_Arquitectura_Inteligente.md` líneas 19-22 — `DES` significa *Destilería* (área 200) en toda la planta **excepto** en `Calderas_8_9_10_Desaireador`, donde significa *Desaireador* (área 300).
- `docs/Manual_Mantenimiento_Codigo.md` líneas 110-112 — `MAPEO_AREA_OVERRIDE_POR_PLC = {"Calderas_8_9_10_Desaireador": {"DES": "300"}}`.
- Inventarios online redundantes `.195` y `.196`, hoja `Programas` fila 18: programa `DES`, rutina `DES_LC_DESAIREADOR`.
- Tag base en el L5X: `DES_S1_LT_TK_DESAIREADOR` (tanque **desaireador**, no destilería).

### 5.2 Verificación 2 — números libres (PASÓ)

Cada número se comprobó contra tres universos independientes:

| Universo | Área 300 | Área 200 |
|---|---|---|
| 11 manuales actuales | ninguno | `004`, `035`, `080` |
| Otros dos lazos propuestos | 083, 081, 082 — todos distintos | ídem |
| Identificadores vigentes online | `001-016`, `020`, `081`, `106` | `001-009`, `011-015`, `101-109`, `201-210`, `601` |

Búsqueda exacta del token en **todos** los tags (sin filtro ISA-like) de las hojas `Tags`:

- `083` en los dos inventarios de Calderas/Desaireador → **0 coincidencias**
- `081` y `082` en el inventario de Destilería → **0 coincidencias**

**Advertencia metodológica:** los números `001-016` del área 300 provienen de la extracción del inventario online. La DB de producción en área 300 solo tiene *los* tags manuales ya listados (ninguno), pero los identificadores de campo/controlador vigentes **sí** ocupan esos números. Esa distinción quedó registrada en el CSV.

### 5.3 Coincidencias con el histórico retirado (registradas, NO bloquean)

Están en columnas separadas y **no se trataron como ocupación actual**, según instrucción explícita del usuario.

| Identidad actual | Coincidencia histórica | Observación |
|---|---|---|
| `DES_S1_LT_TK_DESAIREADOR` | `200_LT_012` (n=012, área 200) | "Migrado de" identidad exacta, pero área histórica != 300 |
| `DES_S1_LT_TK_DESAIREADOR` | `200_ST_009` (n=009, área 200) | comparte el mismo AliasFor físico → duplicidad |
| `DES_S6_PV_VALVULA_EVACUACION_DES` | `200_PV_003` (n=003, área 200) | "Migrado de" identidad exacta |
| `Slot_FT_AGUA` | `200_FT_002` (n=002, área 200) | PLC histórico `DESTILERIA_16062026` (fechado), scope ausente |
| `B_DES_LC_DOMO`, `B_Ctrol_FT_AGUA_A_MOSTO`, `Slot_PV_VALVULA_CAUDAL_AGUA`, `Slot_LT_TK_AGUA_POTABLE`, `B_Ctrol_TK_AGUA_POTABLE`, `Slot_PV_VALVULA_NIVEL_TK_AGUA` | sin coincidencia | — |

Histórico por número (backup de 693): **ninguna** fila con área 300 número 083 ni con 200/081 ni 200/082.
Documentación adicional:
- `docs/Resumen_Ejecutivo_Avance_280826.md:125` registra `200_FT_081` como **eliminado** (`FT_VINO_A_JW_ACUM_TOTAL`).
- `docs/Resumen_Ejecutivo_Avance_280826.md:123` registra `200_FT_082` histórico (`FT_VINO_A_JW_ACUM_HR_ACT`).
Ninguno de los dos existe hoy en la DB ni en el backup de 693 → son **números muertos históricos**, registrados por trazabilidad.

### 5.4 Limitaciones declaradas

- **No se localizó un P&ID** específico del lazo. La comprobación se apoyó en inventarios online de campo/controlador, L5X y documentación del proyecto. No afirmar que se revisó un plano que no existe.
- La propuesta del CSV fue construida por un script puntual de la sesión, **no existe todavía un módulo `src/` que la regenere**.

### 5.5 ⚠️ Colisión de archivo a tener presente

`src/propuesta_historica_lazos.py` escribe **ese mismo nombre de archivo** `exports/propuesta_numeracion_3_lazos.csv` pero con **otro esquema** (`PLC;Program;Routine;Scope;Controlador;...;Decision;Justificacion`).

**Ejecutar ese script sobrescribe la propuesta de 9 tags.** El contenido anterior era la propuesta histórica (que abortó con `0` candidatos: 2 BLOQUEADO_COLISION + 1 PENDIENTE_NUMERO) y es reproducible volviendo a correrlo. Antes de correrlo, resguardar el CSV actual.

---

## 6. Hallazgos estructurales importantes (Fase 2 y cierre)

### 6.1 Declaración ≠ ejecución ≠ runtime

El conteo "209 PID" era engañoso. Números correctos verificados:

```text
Declaraciones únicas por (PLC, scope, instancia): 213
Invocaciones XML exactas demostradas:             145
Declaraciones SIN invocación XML:                  68
Definiciones AOI con control nativo (PID/PIDE):    32  (36 bloques nativos dentro)
Definiciones AOI NO alcanzadas desde Programs:      6
```

El 213 se construyó desde declaraciones de tipo PID/AOI y **no** prueba invocación. El "3" de definiciones no ejecutadas venía de un criterio legado más estrecho. El XML ejecutable **tampoco** prueba ejecución en runtime (falta planificación de tareas).

### 6.2 Reconciliador v3

- `exports/reconciliacion_catalogo_isa_v3.csv` — **973 filas**, SHA-256 `01e488c2d771af6c9da38fa89c5ff422e2f2b8c6d1f2c62da82b5cbde8f12616`.
- Acciones: `SIN_LAZO` 578, `REVISION_LAZO` 271, `REVISION_MANUAL` 99, `CONSERVAR_SIN_CAMBIOS` 11, `CANDIDATO_PID` 8, `CANDIDATO_ENTRADA` 3, `CANDIDATO_SALIDA` 3.
- Eliminadas por completo `AGREGAR_CON_LAZO` y `RENUMERAR_CON_LAZO`.
- Sin columna `Tag_Propuesto_ISA`.
- Grupos completos entrada–PID–salida: 10 (solo 3 habilitados); entrada–PID: 2; PID–salida: 38; señales físicas sin lazo: 578.
- Ambigüedades: entrada no demostrada 201 · elemento final no demostrado 165 · extremo compartido 9 · múltiples destinos 5 · múltiples entradas 2.

### 6.3 Frontera de los 210 controladores incompletos

`exports/frontera_210_controladores.csv` — 210 filas = 213 declaraciones − 3 aprobadas. **No son 210 ejecutados.**

- Con invocación XML demostrada: **142** (`frontera_controladores_con_invocacion_xml.csv`)
- Sin invocación: **68** (`declaraciones_controlador_sin_invocacion.csv`)
- Prioridades legado: **1** = 38 (PID–salida), **2** = 2 (entrada–PID), **3** = 0, **4** = 170

Cinco causas principales que impiden cerrar:

| Submotivo | Afectados | Techo condicional |
|---|---:|---:|
| `DECLARACION_SIN_INVOCACION_XML` | 68 | 0 |
| `ALIAS_NO_RESUELTO` | 44 | 0 |
| `PIN_SIN_CONEXION` | 28 | 0 |
| `BLOQUE_FBD_SIN_MAPEO_DIRECCIONAL` | 18 | 0 |
| `AOI_ENVOLTORIO` | 15 | **10** |

Techo adicional: `TAG_INTERMEDIO_SIN_LECTOR` = 1. **Cierres garantizados: 0.** Los techos son condicionales, nunca pronósticos.

---

## 7. Disciplina de verificación aplicada

Repetir estos controles en cada entrega:

1. `"C:/.../Python313/python.exe" -W error::ResourceWarning -m unittest discover -s tests -q` → **85 tests OK**
2. `python.exe -m compileall -q src tests` → OK
3. `git diff --check` → OK
4. SHA-256 de **ambas** bases antes y después → sin cambios
5. `PRAGMA integrity_check` → `ok`
6. Generar con `PYTHONHASHSEED=11` y `PYTHONHASHSEED=97` → **CSV byte-idénticos** (14 artefactos verificados)
7. Confirmar explícitamente **cero escrituras SQLite**

**Lección crítica:** el determinismo es una propiedad de correctitud. Recorrer un `set` de aristas da resultados distintos entre procesos. Se corrigió ordenando aristas y vecinos. Un test dentro del mismo proceso **no** detecta esto: hay que usar subprocesos con semillas distintas.

---

## 8. Artefactos del proyecto

### Código

```text
src/reconciliador_topologico_v3.py      motor endurecido (identidad XML exacta, 3 confianzas)
src/generar_evidencia_fase2.py          evidencia de los 3 grupos + auditoría PID
src/propuesta_historica_lazos.py        propuesta histórica (OJO: sobrescribe el CSV de 9 tags)
src/frontera_controladores.py           diagnóstico de los 210
src/auditar_l5x.py                      motor de auditoría base
src/reconstruir_catalogo_isa.py         reconstrucción de catálogo (solo CSV)
src/md_a_pdf.py                         conversor MD→PDF (CLI posicional: entrada [salida])
```

### Tests

```text
tests/test_reconciliador_topologico_v3.py
tests/test_generar_evidencia_fase2.py
tests/test_propuesta_historica_lazos.py
tests/test_frontera_controladores.py
tests/test_preparar_y_auditar_planta.py
tests/test_expanded_reading.py
```

### Exportaciones clave (`exports/`)

```text
propuesta_numeracion_3_lazos.csv          ← ENTREGABLE VIGENTE (9 tags)
evidencia_3_lazos_habilitados.csv
frontera_210_controladores.csv
consistencia_213_pid.csv
reconciliacion_catalogo_isa_v3.csv
registro_global_ocupacion.csv
evidencia_historica_9_identidades.csv
verificacion_determinismo_cierre.csv
verificacion_final_solo_lectura.json
```

### Documentación

```text
docs/Manual_Estandarizacion.md                  tabla oficial de áreas
docs/Roadmap_Arquitectura_Inteligente.md        excepción DES→área 300
docs/Manual_Mantenimiento_Codigo.md             MAPEO_AREA_OVERRIDE_POR_PLC
docs/Fase2_Reconciliador_Topologico_v3.md
docs/Resumen_Ejecutivo_Avance_150926.md         informe del 15/09 (10 páginas)
docs/Resumen_Ejecutivo_Avance_150926.pdf
docs/Estrategia_Procesamiento_IO_Reconciliacion.md
```

### Datos de referencia

```text
L5X_Produccion/                                 10 L5X definitivos (sala limpia)
variables plc programa yanco/                   inventarios online .xlsx (.195, .196, .128, …)
app_etiquetas/backups/                          respaldos verificados de la DB
```

---

## 9. Pendientes abiertos

1. **Decisión del usuario sobre los 9 tags.** La propuesta está lista y verificada, pero **no insertada**. El usuario dijo textualmente: *"Después revisamos esa propuesta antes de insertarla."* → **No insertar sin autorización explícita.**
2. **Revisión independiente del CSV de 9 tags: NO COMPLETADA.** El subagente revisor falló con `HTTP 429` (límite de uso) tras 236 s. Las verificaciones del CSV fueron hechas por el agente principal, no por un revisor independiente. **Declarar esto si el usuario pregunta por la revisión.**
3. **Los 210 controladores incompletos** siguen sin resolver. Mejoras con mayor techo: expansión de `AOI_ENVOLTORIO` (10) y `TAG_INTERMEDIO_SIN_LECTOR` (1).
4. **Numeración masiva pendiente** para los grupos restantes, cuando el usuario lo autorice.

---

## 10. Cómo entregar resultados a este usuario

- **Español**, tono directo, sin relleno.
- Reportar **qué cambió, qué está verificado y qué falta**. No narrar el proceso.
- Enlazar archivos con `MEDIA:C:/ruta/absoluta/archivo` (los CSV/PDF se muestran como tarjeta).
- Cuando pida un informe diario: generar `.md` **y** `.pdf` en `docs/`, verificar página y renderizar la primera página para detectar títulos huérfanos o solapamientos.
- No afirmar verificación independiente si no se ejecutó.
- Distinguir siempre **declaración ≠ invocación ≠ ejecución runtime**.
