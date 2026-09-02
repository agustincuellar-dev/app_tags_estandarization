# Resumen Ejecutivo de Avance
## Proyecto de Estandarización de Instrumentación y Control — Ingenio La Florida

**Fecha:** 31 de julio de 2026
**Informe anterior:** `Resumen_Ejecutivo_Avance_300726`

---

## 1. Resumen de la jornada

La sesión se centró en una corrección de proceso crítica señalada por el ingeniero de planta, en la reparación de un bug detectado durante una prueba en vivo, y en la incorporación de la funcionalidad de **edición de tags** a **Tags App**, que hasta ahora solo permitía altas.

Se completaron cinco frentes:

1. Corrección de área: separación de Destilería y Bioetanol.
2. Regla de especificidad para resolver ambigüedades de vocabulario.
3. Repetición del escaneo masivo con el área corregida.
4. Hotfix crítico de formato de tag detectado en una demostración.
5. Mejoras de usabilidad y nueva funcionalidad de edición en Tags App.

---

## 2. Corrección de proceso: Destilería y Bioetanol son plantas distintas

El ingeniero de planta advirtió que Destilería (alcohol al 96%) y Bioetanol (alcohol anhidro) son **instalaciones físicamente distintas** y no pueden compartir el área 200.

**Acción tomada:**

- Se creó el área **250 — Biodestilería**, tanto en el motor de auditoría (`src/auditar_l5x.py`) como en el catálogo de la base de datos de Tags App.
- Se corrigió de paso una inconsistencia preexistente: el catálogo semilla de `database.py` conservaba códigos de área alfabéticos antiguos (`RCP`, `MOL`, `CAL`…) en vez de los numéricos vigentes. Cualquier instalación nueva de la aplicación habría nacido con el catálogo desactualizado; ahora coincide con la tabla oficial.
- Se determinó, junto con el ingeniero, que los rangos numéricos de área (`rango_inicio`/`rango_fin`) son vestigiales bajo la convención actual — el sector lo identifica el prefijo, no el rango — por lo que se dejaron sin modificar (200 y 250 siguen superpuestos a propósito, sin que esto cause bloqueos).

### Regla de especificidad

Durante la carga de palabras clave para el área 250 surgió una ambigüedad real: la palabra `ALCOHOL` es genérica de Destilería, pero el alcohol **anhidro** solo se produce en Biodestilería. Un tag como `FT_ALCOHOL_ANHIDRO` quedaba marcado como ambiguo entre ambas áreas.

Se resolvió con una **regla de prioridad absoluta**: un conjunto de palabras exclusivas (`ANHIDRO`, `TAMIZ`, `TAMICES`, `DESHIDRATACION`, `DESHIDRATADOR`, `BIOETANOL`) decide el área sin admitir discusión, ignorando cualquier coincidencia genérica. La regla se implementó de forma general en el motor (no atada al área 250), de modo que sirva para cualquier ambigüedad futura entre áreas.

---

## 3. Escaneo masivo repetido

Se volvió a correr el orquestador sobre los 12 PLCs canónicos con los diccionarios de área actualizados.

| Métrica | Resultado |
|---|---|
| Tags de proceso e instrumentos | 12.505 |
| Estandarizados con éxito | 7.104 |
| **Efectividad ISA global** | **56,81%** (sin cambios respecto al informe anterior) |
| Tags reasignados al área 250 | **11**, distribuidos en 5 PLCs (Destilería ×3, cenizas2020, DIBACCO) |

El porcentaje global no varía porque la corrección de área **reclasifica** tags que ya estaban bien resueltos — no agrega ni quita éxitos, corrige a cuáles corresponde cada uno.

---

## 4. Hotfix crítico: formato de tag propuesto

Durante una prueba en vivo se detectó que, al seleccionar Área 250 / Variable P / Función V, la aplicación proponía `PV-250` — un formato que viola el estándar corporativo (`[AREA]_[VARIABLE][FUNCION]_[NUMERO]`).

**Causa real (en `database.py`, no en la interfaz):** la función que arma el tag tenía dos errores independientes:

1. No incluía el prefijo de área y usaba guion en vez de guion bajo.
2. El primer número de cada correlativo partía del `rango_inicio` del área (250 en este caso) en lugar de arrancar en 1 — por eso el "250" que aparecía no era el área, era el correlativo mal calculado.

**Corrección aplicada:** el tag ahora se arma como `{área}_{variable}{función}_{número:03d}` (ej. `250_PV_001`), y el correlativo consulta `MAX(numero_loop)+1` sobre la combinación área+variable+función, arrancando siempre en 1. Se retiró el control de "rango agotado" basado en `rango_inicio/rango_fin` (coherente con que ese campo es vestigial), reemplazándolo por un límite real de 999 tags por combinación.

Verificado con el caso exacto reportado y con la continuidad del correlativo sobre combinaciones que ya tenían tags cargados.

---

## 5. Tags App: mejoras de usabilidad y edición

### 5.1 Botón de guardado como Call to Action

El botón de guardado se rediseñó para que resalte: fondo verde de confirmación, texto blanco, negrita, ícono ✔. Técnicamente requirió reemplazar el widget `ttk.Button` por `tk.Button`, ya que el tema nativo de Windows para `ttk` ignora los colores personalizados — el botón anterior nunca podría haber resaltado por más colores que se le asignaran.

### 5.2 Campo Comentarios / Notas

Se agregó un campo de texto libre en el Paso 3 para especificaciones rápidas (ej. "Válvula de 12 pulgadas") que antes forzaban a sobrecargar la Descripción. Requirió tres cambios coordinados: columna nueva en `schema.sql`, migración automática (`ALTER TABLE`) en `database.py` para que la base ya poblada la reciba sin perder datos, y la persistencia en `crear_tag()`.

### 5.3 Descripción ya no bloquea el guardado

Se renombró el campo a "Descripción del elemento / Lazo" y se flexibilizó su validación: si el operador lo deja vacío pero cargó Comentarios / Notas, ese texto se usa como descripción por defecto. Solo se bloquea el guardado si **ambos** campos quedan vacíos.

### 5.4 Edición de tags existentes (funcionalidad nueva)

Hasta ahora Tags App solo permitía dar de alta instrumentos. Se incorporó la capacidad de **editar** un tag ya cargado:

- **Autocompletado por selección:** al hacer clic en un tag de la lista de existentes (Paso 2), el Paso 3 se completa automáticamente con sus datos actuales, consultados en tiempo real desde la base.
- **Botón dinámico:** el botón principal cambia de identidad según el contexto — verde *"Confirmar y Guardar Tag"* para altas, azul *"Actualizar Tag Seleccionado"* cuando hay un tag en edición. Cambiar cualquiera de los combos del Paso 1 cancela la edición en curso y vuelve al flujo de alta, de forma implícita.
- **`database.py`:** nueva función `actualizar_tag()` con `UPDATE` explícito. Por diseño, **no acepta como parámetro** el tag, ni su área, variable, función o número de lazo — la identidad ISA de un instrumento es inmutable una vez asignada; solo se pueden editar los datos complementarios (descripción, ubicación, fabricante, modelo, rango, unidad, comentarios, estado). Cada edición queda registrada en la bitácora de auditoría como `MODIFICACION`, conservando el historial de creación original.

**Verificación de integridad realizada:** se editó un tag real de la base (`300_TT_001`), confirmando que tras la actualización sus campos de identidad (`area_id`, `variable_id`, `funcion_id`, `numero_loop`) permanecieron exactamente iguales, y que la auditoría conserva tanto el registro de `CREACION` original como el nuevo de `MODIFICACION`. Los valores de prueba fueron revertidos a los originales al finalizar.

---

## 6. Hallazgo: dos tags reales cargados durante pruebas de campo

Durante la verificación de integridad de la base se detectaron dos tags que no correspondían a la carga masiva ni a datos de prueba propios:

| Tag | Descripción | Cargado por | Fecha |
|---|---|---|---|
| `250_PV_001` | Válvula de presión de escape 12'' | Agustin | 31/07/2026 |
| `250_PV_002` | Válvula de presión de escape 20'' | Agustin | 31/07/2026 |

Son altas **reales**, cargadas manualmente a través de Tags App durante pruebas de la aplicación — no artefactos de testing que debieran limpiarse. Confirman, además, que el hotfix del formato de tag (Sección 4) y el área 250 recién creada funcionan correctamente en un caso de uso real: ambos tags respetan el formato `250_PV_00X`.

**Estado actual de la base de datos:** **789 tags** (los 787 de la carga masiva + estas 2 altas manuales), con 790 registros de auditoría.

---

## 7. Estado actual y próximos pasos

**Situación:**

- Área 250 (Biodestilería) operativa en motor y aplicación, con regla de especificidad para evitar ambigüedades futuras.
- Escaneo masivo actualizado: 56,81% de efectividad ISA sobre 12 PLCs, con la reclasificación de área ya reflejada en los 24 CSV de resultados.
- Hotfix de formato de tag corregido y verificado.
- Tags App con edición de tags, botón de guardado más visible, y campo de comentarios — todo verificado end-to-end.

**Prioridades sugeridas** (sin cambios respecto al informe anterior, siguen vigentes):

1. Resolver los 1.136 conflictos de numeración entre PLCs, documentados en `conflictos_tags_duplicados.csv`.
2. Revisión de campo de las variables pendientes de los 12 PLCs procesados.
3. Incorporar los respaldos `.L5X` faltantes de la planta.
4. Extraer el dialecto de DIBACCO (27,6% de efectividad, el más bajo del relevamiento).

---

## 8. Nota metodológica

Los indicadores de cobertura de este informe corresponden al escaneo masivo automático sobre archivos `.L5X`, no a la carga manual de Tags App. La base operativa de la aplicación (789 tags) combina ambas fuentes: la carga masiva inicial de los 12 PLCs canónicos y las altas/ediciones manuales realizadas por el equipo desde la interfaz.
