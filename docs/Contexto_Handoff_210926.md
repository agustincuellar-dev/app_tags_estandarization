# Contexto de traspaso — Proyecto ISA-5.1 Ingenio La Florida
**Versión:** 21/09/2026 — posterior a las olas masivas y a la re-redacción de procedencia  
**Proyecto:** `C:\Users\Administrador\Downloads\AUTOMATISMO_AGUSTIN`

---

## 1. Reglas permanentes

1. Trabajar únicamente dentro de `C:\Users\Administrador\Downloads\AUTOMATISMO_AGUSTIN`.
2. SQLite se abre en **solo lectura** (`mode=ro` + `PRAGMA query_only=ON`) salvo que exista autorización explícita del usuario que indique la escritura concreta.
3. Ante ambigüedad, bloquear y reportar evidencia; no inventar ni numerar definitivamente.
4. Los 11 tags manuales son inmutables salvo autorización expresa.
5. Declaración ≠ invocación XML ≠ ejecución runtime.
6. El intérprete obligatorio es `C:/Users/Administrador/AppData/Local/Programs/Python/Python313/python.exe`.

---

## 2. Estado de producción a la fecha

| Elemento | Estado |
|---|---|
| `app_etiquetas/tags_ingenio.db` | **119 tags**: 11 manuales + 9 altas aprobadas + 99 altas masivas |
| Hash posterior a la re-redacción | `2c25c9b76df5ce00027e073597ea297d5844970ed1c9936aee411aaa277d501b` |
| Integridad | `PRAGMA integrity_check = ok` |
| Backup histórico | 693 tags, SHA `ee1df1c901f254bd1a97785a709f3ee154c0ac0503657866d536d1325778c440` |
| Olas masivas | ola 1: 20→59; ola 2: 59→119 |
| Función XV | fila preexistente id 2148; `INSERT OR IGNORE` no creó filas |

### Backups relevantes

- Pre-alta 9 tags (11 tags, byte-idéntico): `app_etiquetas/backups/tags_ingenio_antes_insert_9_tags_20260918_102921_064198600_byte_identico.db`.
- Pre-olas (20 tags, byte-idéntico): `app_etiquetas/backups/tags_ingenio_antes_ola1_20260921_080425_058865_byte_identico.db`.
- Pre-ola 2 (59 tags, byte-idéntico): `app_etiquetas/backups/tags_ingenio_antes_ola2_20260921_080527_037480_byte_identico.db`.
- Pre-re-redacción (119 tags, byte-idéntico): `app_etiquetas/backups/tags_ingenio_antes_re_redaccion_20260921_085704_366616_byte_identico.db`.

---

## 3. Propuesta masiva y su ciclo de vida

- Canonical: `exports/propuesta_numeracion_masiva_180926.csv`.
- Estado: **99 tags / 33 lazos, ya insertados en producción**.
- v3 previa a re-redacción: `exports/propuesta_numeracion_masiva_180926_v3_pre_redaccion.csv`, SHA histórico `0729eac90ae46fd55009a7d4ab83b48e4a382381f2a46428cb9e043681c9551b`.
- El CSV canónico conserva números/tags v3 y ahora tiene 99 `Descripcion_Propuesta` con formato:

```text
<lectura> — lazo <instancia>; Migrado de: <identidad>; rutina <rutina>; área <area> (<nombre area>)
```

- Para 12 **salidas** `CANAL_CRUDO`, agrega:

```text
(sin tag de campo en el PLC: la salida escribe directo al canal)
```

- `200_PT_093` es una **entrada** CANAL_CRUDO; conserva `Migrado de: CANAL_CRUDO:<canal>` sin la frase de salida.
- Auditoría de la re-redacción: 99 filas `ACTUALIZACION`, detalle exacto `Re-redaccion de procedencia`.

### Motores

- `src/trazador_lazos_profundo.py`: trazado XML.
- `src/generar_propuesta_masiva.py`: genera solo los artefactos `_v1`.
- `src/corregir_propuesta_masiva.py`: dueño del CSV canónico; R1–R8, decisiones A/B y redacción futura.
- `src/insertar_propuesta_masiva.py`: inserter por olas, actualmente ya ejecutado.
- `src/re_redactar_procedencia_masiva.py`: actualiza solo `tags.descripcion` de los 99 masivos; dry-run por defecto; con `--apply` crea backup byte-idéntico + API, transacción y 99 auditorías.

---

## 4. Guardarraíl permanente de numeración y exports

**La suite y los generadores nunca derivan ocupación para numerar de `app_etiquetas/tags_ingenio.db` (producción viva).**

Motivo: después de una alta, usar producción para U1 renumeraría retrospectivamente la propuesta ya aprobada e insertada. El problema ocurrió el 21/09 cuando una prueba reejecutó el corrector contra producción: el CSV canónico fue pisado y cambió de sus tags v3 a una numeración post-alta.

Regla implementada:

1. U1 usa el snapshot explícito pre-olas (20 tags): `app_etiquetas/backups/tags_ingenio_antes_ola1_20260921_080425_058865_byte_identico.db`.
2. La fixture equivalente de la suite es `tests/fixtures/tags_ingenio_pre_olas.db`, SHA `b91fefe61fd9b1084fcd6fcf14bd5688c5c20e1099ea30c9723a18909c5ba6b6`.
3. `tests/test_guardarrail_pre_alta_exports.py` ejecuta la regeneración pre-alta contra esa fixture y afirma SHA idéntico **para todos** los `exports/*.csv` antes y después.
4. Las pruebas de alta de 9 tags usan el backup explícito de 11 tags; no construyen fixtures borrando datos desde producción.

No eliminar ni debilitar este guardarraíl sin reemplazarlo por otro snapshot explícito y una prueba de no-mutación de exports.

### 4.1 Numeración congelada (21/09)

`exports/numeracion_congelada_180926.csv` (33 lazos) es la **línea base de numeración** de la propuesta ya aprobada e insertada. `src/corregir_propuesta_masiva.py` toma el número de ahí y **solo busca un libre** para un lazo nuevo, sin número congelado.

Motivo: los universos de ocupación incluyen la documentación (U5), así que cualquier informe, handoff o nota nueva que **cite un número candidato** lo volvía "ocupado" y renumeraba el entregable, desalineándolo de la base. Caso real: `docs/Contexto_Handoff_210926.md` cita `200_PXV_093` como ejemplo de salida CANAL_CRUDO → U5 lo contó ocupado → el pase movió 6 tags (094/096) y el CSV dejó de corresponder a producción.

Regla permanente: **una propuesta aprobada e insertada no se renumera**. La documentación no participa en la decisión de numeración; si un número congelado aparece citado en un documento, se conserva el número y se reporta.

---

## 5. Aplicación de escritorio

- `app_etiquetas/app_tags.py` usa `ttkbootstrap` tema `darkly`.
- Lectura humana: `MAPEO_FUNCIONES["XV"] = "Válvula Todo/Nada"`.
- Grilla de **Búsqueda Expandida**: 8 columnas, con `PLC` inmediatamente después de `Estado` (ancho 100).
  - `plc_para_tabla()` resuelve `tags.plc_origen` → IP del inventario → **últimos dos octetos** (`10.195 / 10.196` cuando el PLC tiene dos controladores).
  - `IP_POR_PLC` está verificado contra `data_historica/inventario_plcs_20260722_093248.xlsx - PLCs.csv` y `variables plc programa yanco/inventario_plcs_*.xlsx`.
  - Sin PLC de origen → `—`; PLC sin IP verificable → nombre corto (12 caracteres).
  - Toda fila debe tener **tantas celdas como columnas**: con una celda de menos, la fila se corre y la descripción queda vacía.
- Panel **Detalle del tag seleccionado**: fila visible `Procedencia (Migrado de):`, proveniente de `tags.comentarios`; muestra `—` si está vacío.
- Exportación Excel, tanto búsqueda rápida como expandida: ambas usan `exportar_workbook_tags()`.
  - Banner amarillo combinado en fila 1.
  - Encabezado en fila 3.
  - Datos desde fila 4.
  - `freeze_panes = A4`.
  - Toda la columna `Tag_Studio5000` (encabezado y datos) amarilla.

---

## 6. Sprint de frontera v4 (21/09, mismo día)

Motores nuevos:

- `src/envoltorios_l5x.py` — parsea cada `<AddOnInstructionDefinition>`: parámetros con su `Usage`, hojas FBD, rungs RLL (el texto vive en el CDATA de `<Text>`) y líneas ST. Responde si el camino interno entre dos pines del envoltorio es **único**.
- `src/trazador_lazos_profundo.py` (extendido) — FASE 1: sigue los pines de salida **declarados** (`SALIDA_MV`, `VALOR_SALIDA`) y atraviesa el envoltorio solo con paso interno único o control interno demostrado. FASE 2: indexa escritores en escalera y ST (antes solo se veían hojas FBD) y resuelve cadenas entre rutinas y programas. Acepta **módulos** (PowerFlex 525, adaptadores) como destino físico, porque son dispositivos reales del anillo.
- `src/sprint_frontera_v4.py` — FASE 3: clasifica los bloqueos por R-A (elemento final motriz → función `Y`), R-B (sensor compartido → lazo propio del sensor **una sola vez** + un lazo por controlador con observación) y R-C (salidas en paralelo → un solo lazo con todas las direcciones en `Migrado_De`).

Entregables: `exports/propuesta_numeracion_masiva_v4_210926.csv`, `analisis_210_lazos_v4_trazador.csv` (crudo) y `analisis_210_lazos_v4.csv` (post-filtro), `frontera_210_controladores_v4.csv`, `bloqueos_…_v4_210926.csv`, `resumen_propuesta_masiva_v4_210926.csv`, `revision_elemento_final_v4_210926.csv`, `diff_propuesta_masiva_v3_v4.csv`, `decisiones_pendientes_v4.csv`, `resumen_sprint_v4.csv`.

Reglas del sprint:

1. El generador y el corrector tienen `modo_v4()` + `--v4`: escriben con nombres v4 y **no tocan los canónicos** (verificado por hash).
2. Los lazos nuevos toman el **siguiente libre** del área; los ya aprobados e insertados conservan su número congelado.
3. `decisiones_pendientes_v4.csv` es una propuesta: `Requiere_Autorizacion=SI` y `Escritura_SQLite=NO` en todas las filas. No se aplica nada.
4. No citar números ISA nuevos en la documentación: `docs/` alimenta el universo U5 y podría correr la numeración de lazos aún no aprobados.

---

## 7. Verificaciones al cierre

- Suite: **211 tests OK** en `tests/` + 16 en `app_etiquetas/`.
- Determinismo: `PYTHONHASHSEED` 11 y 97 → los artefactos del sprint byte-idénticos.
- Canónicos v3 intactos tras correr el pipeline v4 (7/7 hash igual).
- Producción `2c25c9b7…` y backup de 693 `ee1df1c9…` sin cambio; sin `-wal`/`-journal` (cero escrituras SQLite).
- Los 20 tags previos permanecen intactos, verificados campo a campo contra backup pre-olas.
- 99/99 CSV↔DB: tag presente, número igual y descripción byte a byte.
- 99/99 descripciones contienen `Migrado de:`; 12 tienen la aclaración de salida CANAL_CRUDO.

---

## 8. Pendientes

1. Opcional: decidir si se quieren crear alias de Studio 5000 para las 12 salidas sin tag de campo (`exports/salidas_canal_crudo_pendientes.csv`).
2. `exports/decisiones_pendientes_v4.csv`: 32 lazos bloqueados con regla aplicada y número tentativo, a la espera de autorización explícita (R-A 2, R-A+R-C 7, R-B 11, R-B+R-C 1, R-C 10, sin regla 1).
3. No renumerar ni regenerar la propuesta desde producción viva.

---

## 9. Decisión de área — Mieles (23/09/2026)

Decisión explícita del usuario: **Mieles (TK_MIEL*, *MIEL_CENT*, *MIEL_RICA*, canales FLEX5000_MIELES) = área 700** (`Centrifugado / Purga`). Registrar y aplicar como regla de mapeo por identidad/prefijo, sin asignar numeración definitiva ni escribir en SQLite.

> Mieles (TK_MIEL*, *MIEL_CENT*, *MIEL_RICA*, canales FLEX5000_MIELES) = área 700, decisión de usuario 23/09

Mapeo implementado y acotado al PLC FABRICA: las identidades/prefijos TK_MIEL, MIEL_CENT, MIEL_RICA y FLEX5000_MIELES resuelven área 700. Se mantienen sin área ni número SULFO_ENCALADO, COC_LC_MELADO_T, CONTROL_PRESION_BIO y CONTROL_CAUDAL_JUGO_DEST hasta completar la evidencia. Las salidas son propuestas NO_INSERTAR y Escritura_SQLite=NO.

El registro durable está en `docs/Log_Decisiones_Usuario.md`. El re-trazado y la emisión quedaron completados sin escrituras SQLite: el addendum contiene una propuesta cerrable y deja `CONTROL_NIVEL_TK_MIEL1` sin número por la mezcla de terminales; las demás invocaciones de arranque y los limitadores quedaron identificados como no-lazos instrumentales. Se emitieron cuatro fichas pendientes con área y número vacíos. La base de producción y el respaldo conservaron sus hashes e integridad. La suite de la app pasó; la suite principal completa sigue fallando por expectativas históricas incompatibles y por un regenerador que modifica exports; el canonical previo se restauró desde su copia pre-v5.1.
