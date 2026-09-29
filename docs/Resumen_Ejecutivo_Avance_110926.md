# Informe de avance — 11/09/2026 (viernes)
## Preparación de datos y auditoría maestra ISA — Ingenio La Florida

## Resumen ejecutivo

Durante la jornada se completó la preparación del entorno para abandonar los tags históricos generados con numeración autoincremental y comenzar un relevamiento basado en la topología real de los lazos de control.

Se implementaron y verificaron tres herramientas operativas:

1. `src/organizar_l5x.py` — inventario recursivo de fuentes `.L5X` ordenado por fecha de modificación.
2. `src/purgar_db.py` — purga transaccional de los tags históricos, preservando el trabajo manual ya instalado en planta.
3. `src/preparar_y_auditar_planta.py` — orquestador clean-room que copia los diez PLC definitivos y ejecuta la auditoría topológica exclusivamente sobre esas copias.

También se dejó verificado el script anterior `src/migrar_alta_confianza.py`, pero no se aplicó ninguna migración porque los seis tags originales del CSV de propuestas no tenían correspondencia exacta en la base de datos.

---

## 1. Inventario de archivos L5X

### Script creado

```text
src/organizar_l5x.py
```

Características:

- Recorre toda la raíz del proyecto de forma recursiva.
- Detecta extensiones `.L5X` sin depender de mayúsculas/minúsculas.
- Ordena los archivos desde el más reciente hasta el más antiguo.
- Registra fecha de modificación, zona horaria y ruta relativa.
- No mueve ni modifica ningún archivo fuente.

### Resultado

Se encontraron **1.343 archivos `.L5X`** entre fuentes, copias, backups y bibliotecas.

Reporte generado:

```text
exports/reporte_l5x.txt
```

El inventario confirmó que existían numerosos duplicados históricos. Por ese motivo, para el escaneo maestro no se usó la fecha como criterio único: se estableció una lista fija de diez fuentes definitivas.

---

## 2. Purga segura de la base de datos

### Script creado

```text
src/purgar_db.py
```

La purga utiliza:

- `BEGIN IMMEDIATE` y `COMMIT`.
- Backup consistente antes del `DELETE`.
- Rollback automático ante cualquier error.
- Verificación de integridad SQLite.
- Conservación del historial de auditoría sin referencias huérfanas.

### Tags protegidos

Se conservaron los doce tags manuales que ya están en planta:

| Grupo | Tags protegidos |
|---|---|
| Lazo 004 | `200_PT_004`, `200_PIT_004`, `200_PIC_004`, `200_PV_004` |
| Lazo 035 | `200_LT_035`, `200_LIC_035`, `200_LV_035` |
| Lazo 080 | `200_FT_080`, `200_FIC_080`, `200_FV_080` |
| Válvulas manuales | `250_PV_001`, `250_PV_002` |

### Resultado de la purga

```text
Tags eliminados: 681
Tags protegidos conservados: 12
Tags restantes en la base: 12
Integridad SQLite: ok
```

Backup creado antes de la purga:

```text
app_etiquetas/backups/tags_ingenio_antes_purga_20260911_110901_186931.db
```

La bitácora de auditoría, con 3.449 registros, se mantuvo. Las referencias a tags eliminados fueron convertidas en trazabilidad textual para no dejar claves foráneas inválidas.

---

## 3. Preparación clean-room de los PLC definitivos

### Orquestador creado

```text
src/preparar_y_auditar_planta.py
```

El script define estrictamente estos diez archivos:

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

Flujo aplicado:

1. Verificación previa de los diez archivos.
2. Prioridad absoluta a `auto_agustin/L5X_Auditados_Finales/`.
3. Vaciado de `L5X_Produccion`.
4. Copia de los diez archivos.
5. Verificación SHA-256 de cada copia contra su fuente.
6. Auditoría únicamente sobre `L5X_Produccion`.

Resultado:

```text
10/10 archivos copiados correctamente
10/10 hashes coincidentes
L5X_Produccion contiene exactamente 10 archivos
```

La imagen del dashboard fue usada como contexto de los programas definitivos. El CSV conserva el nombre del archivo como procedencia mediante la columna `PLC_Origen`.

---

## 4. Auditoría topológica maestra

### Salida generada

```text
exports/auditoria_planta_completa.csv
```

Columnas:

```text
PLC_Origen
Tag_Original
Tag_Propuesto_ISA
Bloque_Lógico
Estado
```

La numeración se calcula una sola vez sobre el conjunto completo de los diez PLCs, reservando los números ocupados en memoria y evitando colisiones entre archivos.

El catálogo SQLite se abrió en modo estrictamente solo lectura. No se inicializó la base, no se escribieron tags y no se usaron reglas de aprendizaje durante el escaneo.

### Resultado de la corrida

| Métrica | Resultado |
|---|---:|
| PLCs copiados | 10 |
| Lazos topológicos detectados | 50 |
| Lazos de alta confianza | **3** |
| Lazos protegidos por coincidencia topológica | 0 |
| Tags manuales protegidos por catálogo | **12** |
| Lazos enviados a revisión | 47 |
| Filas del CSV maestro | 114 |

Los tres lazos de alta confianza se encontraron en:

- `DESTILERIA.L5X`: 2 lazos.
- `DIBACCO.L5X`: 1 lazo.

Los demás grupos quedaron como `Revision requerida` debido a señales ambiguas, actuadores no demostrados como válvulas, múltiples escritores, cascadas o falta de evidencia topológica suficiente.

### Verificaciones

- `tags_ingenio.db`: 12 tags.
- `PRAGMA integrity_check`: `ok`.
- Los doce tags manuales permanecen presentes.
- El archivo CSV maestro incluye `PLC_Origen`.
- No se usaron archivos duplicados fuera de la sala limpia.

---

## 5. Migración de alta confianza: estado

Se implementó previamente:

```text
src/migrar_alta_confianza.py
```

El script exige coincidencia exacta del tag original antes de actualizar un registro. También utiliza transacción, rollback y trazabilidad en `alias_for`.

La corrida del CSV anterior fue abortada de forma segura porque los seis tags propuestos no existían en la base purgada o no tenían correspondencia exacta. No se insertaron tags y no se aplicaron renombramientos aproximados.

---

## 6. Pruebas y calidad

Verificación ejecutada con Python 3.13:

```text
Ran 53 tests — OK
compileall — OK
git diff --check — OK
```

Las pruebas cubren:

- Inventario ordenado de `.L5X`.
- Copia clean-room y detección de faltantes.
- Purga y protección de los tags manuales.
- Rollback ante errores de integridad.
- Auditoría sobre los diez archivos exactos.
- Inclusión de `PLC_Origen`.
- Catálogo en modo solo lectura.
- Protección de la base durante el escaneo.

---

## Estado al cierre del viernes 11/09/2026

### Completado

- Inventario completo de fuentes `.L5X`.
- Backup de la base antes de la purga.
- Eliminación de los 681 tags históricos no protegidos.
- Conservación de los 12 tags manuales de planta.
- Preparación clean-room de los diez PLC definitivos.
- Auditoría topológica conjunta de toda la planta.
- CSV maestro con procedencia por PLC.
- Identificación de tres lazos de alta confianza.

### Pendiente

1. Revisar en campo los tres grupos de alta confianza antes de cualquier alta definitiva.
2. Analizar los 47 grupos marcados como `Revision requerida`.
3. Confirmar qué archivos o datos de Yanco corresponden a cada PLC cuando se realice el cruce maestro.
4. Diseñar la etapa de importación posterior, manteniendo la regla de no escribir automáticamente sin validación.

## Conclusión

El proyecto quedó preparado para el escaneo maestro basado en topología real. La base histórica fue depurada sin tocar los doce tags manuales instalados, los diez PLC definitivos quedaron aislados en una sala limpia y la auditoría generó un único CSV trazable. El resultado inicial es de **50 lazos detectados, con 3 familias de alta confianza y 47 pendientes de revisión técnica**.
