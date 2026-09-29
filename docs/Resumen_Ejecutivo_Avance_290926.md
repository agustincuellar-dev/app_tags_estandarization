# Resumen Ejecutivo de Avance — 29/09/2026

**Proyecto:** Estandarización ISA-5.1 de tags — Ingenio La Florida  
**Directorio de trabajo:** `C:\Users\Administrador\Downloads\AUTOMATISMO_AGUSTIN`  
**Alcance temporal:** martes 29/09/2026, 07:13 a 12:35 (hora estándar de Argentina)

La jornada llevó la base de producción de **196 a 478 tags** en una única transacción autorizada, después de encadenar cuatro planes maestros con nueve auditorías delegadas, y cerró ordenando el desorden físico de archivos de Studio 5000 del proyecto. La base arrancó el día en solo lectura estricta (`mode=ro` + `PRAGMA query_only=ON`, cero escrituras) y la migración se ejecutó recién con la autorización expresa recibida a las 10:31.

| Indicador del día | Valor |
|---|---|
| Base inicial / base final | 196 → **478 tags** |
| Operaciones aplicadas | 349 (294 INSERT · 43 UPDATE · 12 DELETE) |
| SHA-256 de cierre de `tags_ingenio.db` | `601519b9c76d1d78…` |
| Backups y archivos ordenados | 1 línea base de 196 + 1.835 ACD/BAK archivados |
| Estado de la suite de tests | **no ejecutada** (instrucción explícita del usuario) |

---

## 1. Resumen ejecutivo

La jornada llevó la base de producción de **196 a 478 tags** y ordenó el desorden físico del proyecto, en cuatro tramos:

| # | Tramo | Resultado |
|---|---|---|
| 1 | Catalogación y propuestas (07:13–08:24) | `catalogo_candidatos_expansion_280926.csv` (222 filas) → `propuesta_expansion_masiva_290926.csv` (159 filas) → maestro v1 `plan_maestro_consolidado_290926.csv` (150 INSERT / 41 UPDATE / 12 DELETE) |
| 2 | Cadena de planes v2 → v5 con auditorías delegadas (08:30–10:01) | 4 emisiones, 9 subagentes en 3 batches, proyección 334 → 358 → 417 → 465 → **478** |
| 3 | Homologación y migración a producción (10:11–11:05) | 349 operaciones activas aplicadas en **una sola transacción**; base en **478 tags** |
| 4 | Studio 5000, guía de campo y ordenamiento (11:22–12:00) | 3 `.ACD` para revisión + guía de 8 canales; **1.835** ACD/BAK archivados |

Cierre verificado: `tags_ingenio.db` con **478 registros**, `integrity_check = ok`, `foreign_key_check` sin hallazgos, SHA-256 **`601519b9c76d1d789b50d77df613fe642c92531f1cbf7c9259c618fb61c6f92b`**, sin residuos `-wal`/`-journal`.

---

## 2. Punto de partida (07:13)

El usuario autorizó continuar la generación de planes contra la base con SHA-256 `dc4d9c21…`, pidiendo documentar la discrepancia frente al `6f8f9c34…` que figuraba en migraciones previas y verificando que los **196 registros** (claves primarias, nombres de tag, áreas y descripciones) fueran idénticos al estado anterior, ignorando diferencias de metadatos internos de SQLite.

**Veredicto:** conteo 196 e integridad lógica correctos; la diferencia de hash corresponde a páginas internas del archivo, no a contenido de catálogo. La base se mantuvo en `mode=ro` con `query_only=ON` durante todo el tramo.

---

## 3. Catalogación y propuestas (07:22–08:24)

| Artefacto | Filas | SHA-256 (12) | Hora |
|---|---|---|---|
| `exports/catalogo_candidatos_expansion_280926.csv` | 222 | `ac809e320313` | 07:30 |
| `exports/propuesta_expansion_masiva_290926.csv` | 159 | `89cd47e6e8a2` | 08:13 |
| `exports/plan_maestro_consolidado_290926.csv` (maestro v1) | 268 | `754a87f523c7` | 08:24 |

El catálogo clasifica los extremos físicos disponibles (transmisores, válvulas, switches) con su canal exacto, área y variable. La propuesta masiva respeta las reservas de los 208 tags ya planificados y la protección de los 11 tags manuales. El maestro v1 unificó ambas fuentes: **150 INSERT, 41 UPDATE, 12 DELETE, 13 MANTENER** → **334 tags proyectados**.

---

## 4. Cadena v2 → v5 (08:30–10:01)

Cada etapa incorporó únicamente hallazgos sustentados por XML y conservó la anterior como archivo auditable.

| Etapa | Filas | INSERT | UPDATE | DELETE | Proyectado | SHA-256 (12) |
|---|---|---|---|---|---|---|
| v2 | 316 | 174 | 43 | 12 | 358 | `f4d49799caf6` |
| v3 | 616 | 233 | 43 | 12 | 417 | `76f2d0e70941` |
| v4 | 707 | 281 | 43 | 12 | 465 | `dae9a6ee1b8d` |
| v5 | 722 | 294 | 43 | 12 | **478** | `b90c0739c831` |

**Auditorías delegadas (9 subagentes en 3 batches):**

| Batch | Hora | Tareas | Veredicto |
|---|---|---|---|
| `deleg_28d01214` | 08:30 | 3 | Completas: funciones finales, PV/MV cruzados, las 3 identidades de PLC faltantes |
| `deleg_5d1b783e` | 08:52 | 3 | Completas: 6 grupos FBD/SEL, 11 controladores de salida cruzada, 222 descartes + USINA/CENTRÍFUGA |
| `deleg_80fe7c87` | 09:28 | 3 | **Una falló** (dictamen de Desaireador_2/Desaireador entregado como `✗ TASK 1/3`); se resolvió con inspección directa del XML |

**Qué aportó cada etapa:** v2 clasificó los 11 elementos finales tentativos (6 como `Y`, 1 como `V`, 4 sin resolver) y rescató 19 tags de PLC con nombres divergentes; v3 sumó 59 filas (lazos de Ingeniería, PLC omitidos, Usina vía `MOV → SCL`, pares Entrada–Controlador) y dejó 222 filas `SIN_LAZO` con estado de auditoría individual; v4 cerró los 3 domos de calderas, el evaporador, las cajas condensadoras, el Desaireador y 13 canales físicos únicos; v5 numeró las 5 corrientes de carga de Centrífuga C2–C6, el par de Caja 11, los canales de `Desaireador:3` y homologó las 3 salidas en revisión.

**Desvíos de numeración declarados (no ocultados):**

- Las 5 corrientes de Centrífuga se autorizaron como `700_IT_005..009`, pero `700_IT_008` y `700_IT_009` pertenecen en producción a los lazos `B_PC_10_5` y `B_PC_20_10` → se numeraron **`700_IT_005/006/007/010/011`**.
- `DES_S1_PT_VALVULA_20_10` quedó **`300_PT_055`** (una de 6 asignaciones del módulo Desaireador).
- `Desaireador:3` dio **6 de 8** canales: `Ch[1]` no lo usa ninguna rutina y `Ch[5]` alimenta dos bloques vivos con magnitudes distintas (velocidad 0–1500 y temperatura 0–150 °C).

---

## 5. Homologación de estados (10:11–10:12)

`exports/plan_maestro_consolidado_v5_homologado_290926.csv` — 722 filas, SHA-256 (12) `dcd12ccb77bb`. Sólo cambiaron etiquetas de estado en 66 filas:

| Verificación | Resultado |
|---|---|
| Operaciones activas | 349 → **332 `NO_INSERTAR_REVISION`** + **17 `UPDATE_METADATOS_NO_RENOMBRAR`** |
| Filas con `REVISAR_ANTES_DE_APLICAR` | **0** (ni en `Estado_Maestro` ni en `Estado_Revision`) |
| Balance | 294 INSERT · 43 UPDATE · 12 DELETE · 13 MANTENER — idéntico |
| Determinismo | dos semillas (`11` y `808`) → mismo SHA-256 |

---

## 6. Migración transaccional a producción (10:31–11:05)

Autorizada expresamente por el usuario (“Opción B”), con backup previo inmutable, una única transacción, candado de los 11 tags manuales dentro de la transacción y verificación posterior.

**Paso 1 — Backup previo:**

```
app_etiquetas/backups/tags_ingenio_pre_v5_196tags_290926.db
SHA-256 = dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522
```

**Paso 2 — Transacción única** (`BEGIN IMMEDIATE` → `COMMIT`, `foreign_keys=ON`): 294 INSERT + 26 renombres + 17 actualizaciones de metadatos + 12 DELETE. Candados dentro de la transacción: conteo exacto 478, los 11 manuales campo a campo, `foreign_key_check` e `integrity_check`; ante cualquier falla, ROLLBACK.

**Defecto encontrado y corregido (declarado):** la primera aplicación escribió el campo `alias_for` truncado en los canales con corchetes (`BP_ANALOGICA:1:I.Ch` en lugar de `…Ch[4].Data`), porque el extractor no contemplaba `[ ]`. Se detectó en la verificación posterior; se **restauró la base desde el backup byte-idéntico** (el SHA volvió a `dc4d9c21…`), se corrigió el extractor y se re-aplicó. Resultado final: 0 canales truncados, verificado contra la dirección cruda del CSV.

**Paso 3 — Verificación posterior (solo lectura):**

| Verificación | Resultado |
|---|---|
| Registros | **478** (141 filas intactas + 43 modificadas + 294 altas; 12 bajas exactamente las previstas) |
| `integrity_check` / `foreign_key_check` | `ok` / 0 hallazgos |
| `journal_mode` / residuos | `delete` / sin `-wal` ni `-journal` |
| 11 tags manuales | **11/11** presentes e idénticos al backup, 0 en operaciones |
| SHA-256 final | `601519b9c76d1d789b50d77df613fe642c92531f1cbf7c9259c618fb61c6f92b` |
| Auditoría | **+349 filas** (294 CREACION, 43 MODIFICACION, 12 ELIMINACION), total 4.112, 0 huérfanos |

**Distribución por área de los 478 tags:**

| Área | | Área | |
|---|---|---|---|
| 100 Molienda | 70 | 500 Evaporación | 50 |
| 200 Destilería | 122 | 600 Cocimiento | 15 |
| 250 Biodestilería | 13 | 700 Centrifugado | 55 |
| 300 Calderas | 117 | 900 Fuerza Motriz | 18 |
| 400 Clarificación | 18 | **Total** | **478** |

Todos los tags quedaron en estado `Planificado`. El área 000 quedó en 0 (sus tags migraron a 250 o se dieron de baja).

---

## 7. Studio 5000, guía de campo y ordenamiento (11:22–12:00)

**Selección de `.ACD`** — regla: el `.ACD`/`.BAK` más reciente de cada PLC, sin marca de duplicado y con tamaño de proyecto completo (≥ 2 MB). Se encontraron **1.844** archivos `.ACD`/`.BAK` (no un puñado: el proyecto tenía tres árboles duplicados).

| Copia en `00_REVISION_STUDIO5000_HOY/` | Origen | Fecha | Tamaño |
|---|---|---|---|
| `1_TRAPICHE2022.ACD` | `ACD_Para_Convertir/…/TRAPICHE2022…BAK031.acd` | 30/07 05:40 | 5,10 MB |
| `2_DESTILERIA.ACD` | `ACD_Para_Convertir/…/DESTILERIA_RECUPERADO.ACD` | 05/08 16:27 | 8,58 MB |
| `3_Calderas_8_9_10_Desaireador.ACD` | `data_historica/proyectos_studio5000/Calderas_8_9_10_Desaireador.ACD` | 15/07 07:41 | 4,81 MB |

Las 9 copias (3 de revisión + 6 de catálogo) se verificaron byte a byte contra su original. Advertencias dejadas por escrito en la guía: para TRAPICHE el elegido es un `.BAK031`; para DESTILERIA el elegido es un archivo *recuperado*; y el L5X de producción de Calderas (18/08) es **más nuevo que todos los `.ACD` disponibles** (el más reciente es del 15/07), así que ninguna copia calza exactamente con la versión auditada.

**Guía de los 8 canales** (`GUIA_8_CANALES_A_REVISAR.md` y `.txt`): para cada canal se leyó del XML el programa/rutina FBD, la hoja y el bloque exacto, el canal físico, el alias declarado y el bloque que realmente lo procesa. Resultado de la auditoría de hoy:

- Canales 1, 2, 3, 5, 6 y 7 son **contradicciones reales de identidad** (slots de TRAPICHE, `jw_fermerntacion_2022:2` en DESTILERIA, `Desaireador:3:I.Ch[5]` en Calderas).
- Canal 4 **no** es una contradicción: es el mismo Pt100 de la bobina del motor del rolo con y sin la palabra NORTE en el destino → sólo falta confirmación para crear `100_TT_057`.
- Canal 8 (`Desaireador:3:I.Ch[1]`) es un alias declarado sin ningún bloque cableado.

**Ordenamiento:**

| Destino | Contenido | Operación |
|---|---|---|
| `00_REVISION_STUDIO5000_HOY/` | 3 ACD de producción + guía `.md`/`.txt` | copiado |
| `archivo_ordenado/ACD_Catalogo_Vigentes/` | 6 ACD vigentes (FABRICA, DIBACCO, CALD_LA_FLORIDA, cenizas2020, CENTRIFUGA_DE_PRIMERA, USINA_LA_FLORIDA) | copiado |
| `archivo_ordenado/ACD_Historicos_y_Backups/` | **1.835 archivos, 6,7 GB**, 0 fallos | movido |
| `archivo_ordenado/MAPA_MOVIMIENTOS_290926.csv` | ruta original → ruta nueva de cada archivo (reversible) | generado |
| `exports/historico_iteraciones/` | 16 entradas (logs, JSON de verificación, xlsx, carpetas temporales) | movido |

No se tocaron `app_etiquetas/` (71 archivos), `src/` (111), `tests/` (96), `L5X_Produccion/` (10) ni `docs/` (63).

---

## 8. Lo que no se hizo y decisiones que esperan al usuario

**Ausencias declaradas:**

1. **No se corrió la suite completa de tests** (229 pruebas): instrucción explícita del usuario. No hay veredicto de suite en esta jornada; la verificación se hizo con candados dentro de la transacción y con verificación independiente posterior contra el backup.
2. **Una tarea del batch de 09:28 falló** (dictamen de Desaireador_2/Desaireador). Se cubrió con inspección propia del XML, no por dictamen independiente.
3. **El ordenamiento de `exports/` quedó incompleto a propósito**: se movieron 16 entradas, no 74. Los otros **71 CSV** son entradas que `src/` y `tests/` leen por nombre de archivo (26 de ellos desde `tests/`, o sea guardarraíles ejecutables). Moverlos rompe rutas de código —lo que la propia regla prohibía—. Para dejar sólo los 3 maestros hay que parametrizar antes esa ruta en los scripts.

**No resuelto, sin acción tomada:**

| Tema | Estado |
|---|---|
| 8 canales con contradicción de cableado | Sin definir; requieren respuesta de planta (guía entregada) |
| 2 salidas con alias cruzado (`700_PV_002`, `400_PV_004`) | Numeradas, con advertencia de discrepancia de alias para verificación física |
| 43 filas heredadas sin operación | Siguen fuera del plan; no generan tags |
| 12 altas sin `plc_origen` | El lazo entero carece de canal físico del que heredarlo |
| 49 filas de controlador | Sin canal de campo (esperado: son controladores) |
| `p pasar/` | **30.097 archivos, 3,7 GB** de una instalación de Studio 5000/FactoryTalk dentro del proyecto; no se tocó |
| `ACD_Para_Convertir/` y `archivos ACD y L5X auditados/` | Ya sin ACD, quedaron con `.L5X` y subcarpetas vacías |

---

## 9. Disciplina de verificación aplicada hoy

- Toda cifra de este informe fue **releída hoy desde el artefacto en disco** (CSV, SQLite en `mode=ro`, o el árbol de archivos), no heredada de resúmenes.
- La base de producción se abrió siempre en `mode=ro` + `PRAGMA query_only=ON` fuera de la ventana de escritura autorizada.
- La verificación posterior a la migración se hizo **contra el backup**, no contra el propio resultado: 141 filas intactas campo a campo, 43 modificadas, 294 altas, 12 bajas.
- Las copias de los 9 `.ACD` se validaron con SHA-256 contra su original.
- Los movimientos de archivos quedaron registrados con mapa reversible.

---

## 10. Archivos creados o modificados hoy

**Motores y scripts (`src/`):** `catalogar_candidatos_expansion_280926.py`, `generar_propuesta_expansion_masiva_290926.py`, `generar_plan_maestro_consolidado_290926.py`, `…_v2_290926.py`, `…_v3_290926.py`, `…_v4_290926.py`, `…_v5_290926.py`, `homologar_estados_plan_v5_290926.py`, `migrar_plan_v5_a_produccion_290926.py`, `ordenar_proyecto_acd_290926.py`.

**Artefactos (`exports/`):** `catalogo_candidatos_expansion_280926.csv`, `propuesta_expansion_masiva_290926.csv`, `plan_maestro_consolidado_290926.csv`, `…_v2_290926.csv`, `…_v3_290926.csv`, `…_v4_290926.csv`, `…_v5_290926.csv`, `plan_maestro_consolidado_v5_homologado_290926.csv`.

**Base de datos:** `app_etiquetas/tags_ingenio.db` (478 tags) y `app_etiquetas/backups/tags_ingenio_pre_v5_196tags_290926.db` (línea base de 196).

**Organización:** `00_REVISION_STUDIO5000_HOY/` (3 ACD + guía `.md`/`.txt`), `archivo_ordenado/ACD_Catalogo_Vigentes/` (6 ACD), `archivo_ordenado/ACD_Historicos_y_Backups/` (1.835 archivos), `archivo_ordenado/MAPA_MOVIMIENTOS_290926.csv`, `archivo_ordenado/inventario_acd_y_exports_290926.json`.

**Documentación:** este informe, `docs/Resumen_Ejecutivo_Avance_290926.md` y su PDF.

---

**Estado de cierre:** producción con 478 tags, integridad verificada, 11 tags manuales intactos y sin residuos de journal. El único bloqueo real que queda es de planta, no de software: definir la identidad de los 8 canales para convertirlos en tags.
