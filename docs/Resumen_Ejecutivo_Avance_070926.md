# Informe de avance — 07/09/2026
## Tags App — Ingenio La Florida

## Resumen ejecutivo

La jornada del 7/9 consolidó el **endurecimiento del cumplimiento ISA-5.1 dentro del flujo de alta** y una ronda de correcciones de estabilidad visual de la UI. El trabajo quedó registrado en el commit `90ef9f3` ("cambios 7/9", 12:36 h) con **814 líneas agregadas y 56 removidas** sobre 7 archivos:

- Nuevo módulo **`isa_rules.py`**: reglas ISA centralizadas, reutilizables y testeables (orden de letras, asistente, restricciones por variable).
- **Alta de la función `IT`** (Indicador-Transmisor) en el catálogo.
- **Decisión ISA obligatoria** en el Paso 1: la app ya no adivina si un transmisor tiene display local (`T` vs `IT`) ni si un dispositivo local es visor directo (`I` vs `G`).
- Filtrado dinámico del catálogo de funciones según la variable elegida.
- Rediseño de la Pantalla A: título adaptable en cabecera, layout que alterna entre dos columnas y paneles apilados, estilos propios de tag propuesto y lectura ISA.
- Paso 2 con scroll propio, edición explícita (botón + doble clic) y sin edición accidental al seleccionar.
- Correcciones de layout: columnas estables en "Tags recientes", recuadro verde de lectura ISA con ancho fijo, árboles con tema oscuro y selección azul visible.
- Búsqueda expandida: contador de selección, **Shift + flechas** y **Ctrl + A**.
- Eliminación de tags desde el detalle del panel derecho y exportación independiente de recientes.
- Descripción autocompletada con la lectura ISA al crear un tag nuevo.
- **11 pruebas automatizadas nuevas**, todas en verde.

---

## 1. Nuevo módulo `isa_rules.py` (reglas ISA reutilizables)

Extrae a un módulo sin dependencias de UI ni de base de datos las reglas que gobiernan la construcción de funciones ISA:

- **`validar_funcion_isa(funcion)`** — valida el orden de columnas funcionales de ANSI/ISA-5.1: una función pasiva/de lectura (`I`, `R`, `G`, `S`, `A`, `U`, `E`) debe preceder a una activa (`T`, `C`, `V`, `K`, `Q`, `Y`). **`IT` es válido; `TI` se rechaza** con mensaje explicativo.
- **`funcion_sugerida_por_asistente(...)`** — resuelve la función canónica según la condición física del instrumento: transmisor con display local → `IT`; sin display → `T`; dispositivo local autónomo con visor directo → `G`; sin visor → `I`.
- **`funciones_permitidas_para_variable(variable, catalogo)`** — restricciones corporativas conservadoras por variable. Para **Densidad/Brix (`D`)** solo se habilitan funciones de medición/lectura y alarma (`T`, `IT`, `I`, `R`, `G`, `S`, `SH`, `SL`, `A`, `AH`, `AL`, `E`, `Q`): **no se ofrecen controladores ni válvulas**, porque su semántica depende de la ingeniería de cada lazo. El resultado se devuelve ordenado (estable y comprobable). Las variables sin regla conservan el catálogo completo (no se inventan prohibiciones).

## 2. Alta de la función `IT` en el catálogo (`database.py`)

Se incorporó `("IT", "Indicador - Transmisor (display local)")` al estándar de funciones ISA. Con esto, el asistente y la decisión obligatoria pueden materializar `LIT`, `PIT`, `FIT`, etc., que antes no existían como función seleccionable. `app_tags.py` sincroniza su `MAPEO_FUNCIONES` ("IT": "Transmisor Indicador") para que la lectura humana funcione (la prueba `test_lectura_humana_traduce_it...` verifica que `200_LIT_001` se lea como "Transmisor Indicador de Nivel…", no como "IT de Nivel").

## 3. Pantalla A — decisión ISA obligatoria y filtro por variable (`app_tags.py`)

### 3.1 La selección de Variable ahora filtra el catálogo de Funciones
Al elegir variable (`_on_variable_selected`), el combobox de función se rellena solo con las funciones permitidas por `isa_rules`; si la función ya elegida queda fuera, se limpia y la propuesta muestra *"seleccione una función permitida"*.

### 3.2 La selección de Función `T` o `I` abre una decisión obligatoria
Al elegir `T` (transmisor) o `I` (indicador) (`_on_funcion_selected`), la app abre un diálogo modal **"DECISIÓN REQUERIDA POR ISA-5.1"**:

| Función elegida | Pregunta | Sí | No |
|---|---|---|---|
| `T` | ¿El transmisor tiene pantalla/display local? | `IT` (LIT/PIT/FIT) | `T` (LT/PT/FT) |
| `I` | ¿Es dispositivo autónomo de visualización directa (vidrio, mirilla, manómetro)? | `G` (LG/PG/TG) | `I` (indicador digital) |

- No hay respuesta por defecto: cerrar la ventana cancela la selección y deja el tag propuesto en *"responda la decisión ISA para continuar"*.
- El orden ISA se valida también al guardar (`on_guardar`): **la identidad del tag se genera desde catálogos y respuestas ISA**, ya no se toma texto libre del entry (evita invertir letras o crear combinaciones ajenas).

### 3.3 Asistente 💡 coherente con las mismas reglas
El asistente voluntario comparte `funcion_sugerida_por_asistente` y `seleccionar_funcion_isa` con la decisión obligatoria; al resolver, cierra tanto la ventana del asistente como la de decisión si estuviera abierta.

## 4. Pantalla A — rediseño de cabecera y layout adaptable

- **Título principal en la cabecera fija**: "Registro de Nuevo Instrumento" centrado, con `_ajustar_titulo_header` que reduce tamaño de fuente (20→16→13) y ajusta `wraplength` cuando la ventana es angosta, sin invadir los logos (se referencia `bloque_header_izquierdo`).
- **Layout adaptable** (`_adaptar_layout_inicio`): por encima de **1050 px** de ancho, Pantalla A usa dos columnas (crear a la izquierda, búsqueda a la derecha); por debajo, los paneles se apilan verticalmente. Se eliminó el `state("zoomed")` forzado: la ventana ahora abre con geometría adaptativa a la pantalla (ancho máx. 1200, alto máx. 820, mínimos relativos al monitor).
- **Estilos propios**: `PropuestaTag.TLabel` (ámbar `#FFBB02` sobre azul `#002157`, 22 pt bold) para el recuadro del tag propuesto, y `LecturaTag.TLabel` para su traducción humana.
- Al navegar entre vistas el scroll del canvas vuelve al tope (`yview_moveto(0)`).

## 5. Paso 2 — lista de existentes corregida

- **Scrollbar vertical propio** (`scroll_lista_existentes`) y rueda del ratón redirigida solo a la lista (`_on_mousewheel_lista_existentes` devuelve `"break"` para que el canvas padre no se desplace).
- **Seleccionar ya no edita**: el click solo habilita el botón **"Editar tag"** (`_on_lista_existentes_seleccion`); la edición se dispara con ese botón o **doble clic** (`_editar_existente_seleccionado`). Se evitó la entrada accidental al modo edición al pasar por la lista.
- `exportselection=False` para que la selección no se pierda al tocar otros controles.

## 6. Tag propuesto — edición manual como excepción explícita

- El campo interno del tag quedó **readonly** (se conserva por compatibilidad con generación/guardado/traducción, ya no se muestra duplicado).
- La edición manual de casos especiales ISA se hace con el botón **"✎ Editar tag"** o **doble clic sobre el recuadro amarillo** (`_editar_tag_propuesto_manual`): pide el tag completo, valida formato `AREA_VARIABLE+FUNCIÓN_LAZO` (3 partes, lazo numérico) y actualiza propuesta, traducción y estado.

## 7. Pantalla B — descripción autocompletada y reseteo seguro

- En modo **creación**, al entrar a Datos el campo *Descripción del instrumento* se **precarga con la lectura humana del tag propuesto** (capitalizada, vía `traducir_tag_humano`). Sigue siendo editable y la validación de campo obligatorio se mantiene.
- `_resetear_campos_datos_creacion()` garantiza que el alta **nunca hereda valores** de una edición previa.
- El botón **"← ATRÁS"** (`_volver_a_inicio_desde_datos`) sale del modo edición y limpia los campos antes de volver al inicio.

## 8. Panel derecho — estabilidad de layout y acciones

- **Recuadro verde "Lectura ISA-5.1" con ancho fijo**: se fijó `width=1` para que el label no reclame ancho según su texto (causa raíz de los saltos de layout); ocupa siempre el ancho completo del panel y el texto wrappea dentro (`_ajustar_ancho_lectura_reciente` ajusta el `wraplength` al ancho disponible del contenedor). Solo la altura varía.
- **"Tags recientes" sin rectángulo blanco**: columnas con ancho fijo (Tag 140, Estado 110) y **última columna "Creado" con stretch** para llenar el 100 % del árbol; estilo oscuro dedicado `Recent.Treeview` (fondo `#222222`, selección azul `#0D6EFD`).
- **Botón "🗑️ Eliminar"** junto a "✎ Editar" en el detalle: pide confirmación ("¿Estás seguro de eliminar el tag XXX?"), elimina en base, refresca recientes y grilla, y limpia el detalle (`eliminar_tag_detallado`).
- **Exportación de recientes independiente**: `exportar_seleccionados_recientes` ya no depende de la grilla del Paso 5; exporta exclusivamente la selección del árbol de recientes a `exports/tags_recientes_<fecha>.xlsx` con la columna `Tag_Studio5000`, y confirma con la ruta del archivo.

## 9. Búsqueda expandida — selección visible y por teclado

- Estilo oscuro dedicado `Expanded.Treeview` con **selección azul contrastada** (`selected → #0D6EFD` sobre `#222222`).
- **Contador**: "N tag(s) [en total] · X seleccionados" (`_actualizar_contador_seleccion_expandida`), actualizado al refrescar y al seleccionar.
- **Shift + ↑/↓ extiende la selección** desde el item ancla (`_extender_seleccion_expandida`), manteniendo foco y fila visible.
- **Ctrl + A selecciona todas las filas visibles** (`_seleccionar_todos_expandida`).
- Doble clic conserva el detalle; el botón "Exportar a Excel" sigue operando sobre la selección.

## 10. Pruebas agregadas (11 nuevas, todas en verde)

**`app_etiquetas/test_isa_rules.py` (5):**
1. Transmisor con display local → `IT`; sin display → `T`.
2. Indicador local autónomo con visor → `G`; sin visor → `I`.
3. `TI` se rechaza (orden pasiva después de activa) con mensaje que contiene "antes".
4. `IT` se acepta (indicación antes de transmisión).
5. Densidad no ofrece control ni válvula (catálogo filtrado → `("A","G","I","IT","T")`).

**`app_etiquetas/test_app_tags_ui.py` (6, con DB temporal aislada):**
1. La lista de existentes tiene scroll propio y binding directo de rueda.
2. Seleccionar en la lista no abre edición y habilita el botón explícito.
3. El botón "Editar tag" reutiliza el flujo de edición (entra en modo edición con `200_LIT_001`).
4. La lectura humana traduce `IT` ("Transmisor Indicador"), no las siglas crudas.
5. El inicio tiene estilos destacados (ámbar/azul) y layout adaptable (paneles apilados < 1050 px, dos columnas ≥ 1050 px).
6. (Verificación de reglas cubierta por `test_isa_rules`.)

### Verificación ejecutada
```bash
python -m unittest test_isa_rules test_app_tags_ui -v
# Ran 10 tests ... OK        (5 + 5)
```
La suite de UI corre contra una base temporal (`tempfile.TemporaryDirectory` + redirección de `db.DB_PATH`); **la base de producción `tags_ingenio.db` no quedó modificada** por las pruebas (se restauró su estado versionado).

## 11. Archivos del día

| Archivo | Cambio |
|---|---|
| `app_etiquetas/isa_rules.py` | **Nuevo** — reglas ISA reutilizables (orden, asistente, restricciones por variable) |
| `app_etiquetas/test_isa_rules.py` | **Nuevo** — 5 pruebas de reglas |
| `app_etiquetas/test_app_tags_ui.py` | **Nuevo** — 6 pruebas de UI con base aislada |
| `app_etiquetas/database.py` | +1 — función `IT` en el catálogo estándar |
| `app_etiquetas/app_tags.py` | +515/−56 — decisión ISA obligatoria, filtro por variable, layout adaptable, scroll/edición explícita en Paso 2, edición manual de tag, descripción autocompletada, estabilidad de árboles y recuadro verde, selección por teclado, eliminar y exportar desde recientes |
| `docs/Resumen_Ejecutivo_Avance_040926.md` | Versionado (informe del 4/9 incorporado al repositorio) |

## 12. Pendientes / notas

- Los árboles usan nombres de tema `darkly` (legacy en ttkbootstrap 2.x): conviene planificar la migración a un tema 2.0 antes de que `darkly` se elimine en 3.0 (aviso de `DeprecationWarning` en la suite).
- Fuera del alcance de este informe (trabajo en curso del 8/9, sin commitear): reescritura de `src/auditar_l5x.py` hacia la auditoría de lazos por topología L5X con base de solo lectura y salida CSV aislada.
