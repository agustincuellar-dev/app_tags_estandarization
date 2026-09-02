# Manual de Herramientas de Recolección y Filtrado
## Ingenio La Florida — segunda parte del Manual de Mantenimiento de Código

**Fecha:** 28 de agosto de 2026
**Complementa a:** `docs/Manual_Mantenimiento_Codigo.md` (que cubre el motor de clasificación y la Tags App). Este documento cubre los **5 scripts que quedaron fuera** de ese manual porque no se tocan en el día a día — se usan solo cuando hace falta **traer código nuevo a la planta** (un PLC que se reprograma, un `.ACD` que nadie había exportado, o un volcado masivo de tags que no viene de un `.L5X`).

Si nunca vas a recolectar fuentes nuevas de un PLC, no necesitás este documento. Si algún día alguien dice *"tengo un .ACD nuevo, ¿cómo lo meto al sistema?"*, empezá acá.

---

## 0. Los 5 scripts y en qué orden se usan

Son **tres etapas secuenciales** de recolección (1→2→3) más **dos herramientas independientes** que se usan en otros momentos del flujo:

```
ETAPA 1  src/recolector_fuentes_plc.py
         Corre en CADA PC de ingeniería. Barre el disco entero, copia todo
         .ACD/.L5X que encuentra a una carpeta central, sin tocar el
         original. Standalone (no importa nada del proyecto).
              |
              v  (fusión MANUAL de las 5 carpetas de salida en una sola "dist")
              |
ETAPA 2  src/analizar_dist_recolectado.py
         Agrupa esa carpeta fusionada por equipo real (ignora duplicados,
         backups, sufijos de PC) y responde: "¿cuál es la versión MÁS
         RECIENTE de cada PLC, y ya la tenemos auditada o no?"
              |
              v
ETAPA 3  src/filtrar_acd_para_convertir.py
         De esa lista, arma UNA carpeta con SOLO los archivos realmente
         nuevos (ventana de fecha) listos para abrir en Studio 5000 y
         exportar a .L5X a mano. Lo viejo queda en cuarentena, documentado,
         sin auditarse a ciegas.
              |
              v  (exportación MANUAL a .L5X en Studio 5000 -- fuera del alcance
              |   de estos scripts)
              |
         ---- A PARTIR DE ACÁ empieza el pipeline principal ----
         ---- (src/auditar_l5x.py, procesar_todos_l5x.py, etc. --
         ----  ver Manual_Mantenimiento_Codigo.md) ----


HERRAMIENTAS INDEPENDIENTES (no forman parte de la cadena 1→2→3):

  src/auditar_masivo.py
         Entrada alternativa al MISMO motor de clasificación, pero para
         cuando lo que hay es un volcado tabular (CSV/XLSX de ~25.000
         tags) en vez de un .L5X. Se usa una sola vez por volcado masivo,
         no por cada PLC.

  src/escanear_referencias_logica.py
         Corre DESPUÉS de auditar_l5x.py + cruzar_planta_viva.py (no
         antes, no en paralelo). Agrega una columna extra a los CSV ya
         cruzados: si un tag "vivo" en la tabla de memoria también está
         REFERENCIADO por algún rung o diagrama FBD activo -- detecta
         tags "zombi" (viven en memoria pero nadie los usa en lógica).
```

---

## 1. `recolector_fuentes_plc.py` — Etapa 1: barrido en cada PC

**Qué hace:** recorre recursivamente un directorio (típicamente `C:\` o `D:\` completo) buscando archivos `.acd`/`.l5x`, y los copia — **nunca mueve, nunca borra** — a una carpeta destino, agrupados por el nombre de equipo real (limpia sufijos como `_DUP3`, `.BAK000`, fechas, "final", "viejo").

**Por qué existe:** el código fuente de los PLCs está disperso en 5 PCs de ingeniería distintas, cada una con su propio historial de backups. Este script es el primer paso para centralizarlo.

**Cómo correrlo:**
```bash
python recolector_fuentes_plc.py
```
Es **interactivo** (pide el directorio origen y el destino por consola — default `C:\Repositorio_Ingenio_Temp` si no se especifica). Es **standalone**: solo usa librería estándar de Python (`os`, `re`, `shutil`, `csv`, `sys`, `datetime`), pensado para copiarlo a cualquier PC sin instalar nada.

**Salida:**
- La carpeta destino, con una subcarpeta por equipo.
- `trazabilidad_extraccion.csv` — una fila por archivo copiado, con nombre destino, equipo clasificado, fecha de modificación original, y ruta absoluta de origen.
- `errores_extraccion.log` — archivos que no se pudieron copiar (permisos, en uso por Studio 5000). **Un error acá nunca frena el barrido completo** — es una decisión de diseño explícita.

**Configuración que podés necesitar tocar:**
- `CARPETAS_SISTEMA_IGNORAR` (línea ~53) — carpetas que el barrido se salta (`Windows`, `Program Files`, etc.). Si el barrido tarda demasiado o trae ruido de una carpeta nueva del sistema, es acá.
- `EXTENSIONES_VALIDAS = (".acd", ".l5x")` (línea ~67) — si algún día hace falta recolectar también `.L5K` o algo similar, es acá.
- `limpiar_nombre_equipo()` (línea ~114) — la lógica que decide que `FABRICA.WIN-J5VK3AMRJJD.Administrador.BAK097.L5X` y `FABRICA_DUP1.L5X` son "el mismo equipo". Si aparece un PLC nuevo cuyo nombre de archivo no se agrupa bien, revisar acá.

**Después de correrlo en las 5 PCs:** las 5 carpetas resultado se fusionan **a mano** (copiar todo a una sola carpeta "dist") antes de pasar a la Etapa 2. El propio `analizar_dist_recolectado.py` explica por qué no puede automatizar esa fusión (el CSV de trazabilidad de cada corrida se pisa si dos corridas escriben en la misma carpeta).

---

## 2. `analizar_dist_recolectado.py` — Etapa 2: cuál es la versión más nueva

**Qué hace:** toma la carpeta "dist" ya fusionada y responde la pregunta operativa real: *de todas las copias de cada PLC, ¿cuál es la más reciente, y coincide con lo que ya tenemos auditado en `auto_agustin/`?*

**Por qué no usa el CSV de trazabilidad de la Etapa 1:** porque se pisa al fusionar corridas. En cambio, confía directamente en la **fecha de modificación real de cada archivo en disco** (`shutil.copy2` la preservó desde el origen).

**Cómo correrlo:**
```bash
python analizar_dist_recolectado.py "<ruta a la carpeta dist>"
```

**Salida:** `<dist>/ANALISIS_mas_recientes.csv` — una fila por familia de equipo real, con su archivo más reciente (cualquier extensión), su `.L5X` más reciente (el único auditable), y una acción sugerida comparando contra el canónico vigente.

**Configuración que vas a necesitar tocar seguido — esta es la que más mantenimiento pide:**

- **`PALABRAS_CLAVE_PLANTA`** (línea 54) — lista curada de nombres reales de la planta, para filtrar el ruido de instalaciones de ejemplo de Rockwell que un barrido de `C:\` completo arrastra (AOIs de muestra, DriveLogix samples, etc.). Lo que no matchea ninguna palabra clave **se cuenta aparte, nunca se descarta en silencio** — revisá el conteo de "no reconocidos" cada vez que corras esto.

  ```python
  # Agregar un PLC nuevo a la planta (ej. si se instala un equipo nuevo):
  PALABRAS_CLAVE_PLANTA = [
      "DIBACCO", "CALD_LA_FLORIDA", ..., "DESTILERIA", "JW2013", ...,
      "PLC_NUEVO_A_AGREGAR",   # <- agregar acá
  ]
  ```

- **`FAMILIA_A_CANONICO`** (línea ~64) — mapea el nombre de familia detectado al nombre del `.L5X` canónico vigente en `auto_agustin/`, para poder comparar "¿esto que encontré es más nuevo que lo que ya tenemos?".

> **⚠️ Encontrado desactualizado al escribir este manual (28/08/2026), no corregido todavía:** tras el cambio de ayer (`jw2013` → `DESTILERIA`, ver `Resumen_Ejecutivo_Avance_280826` si existe, o el historial de sesión), estas dos tablas quedaron con datos viejos:
> - `PALABRAS_CLAVE_PLANTA` todavía tiene `"JW2013"` (ya no es el nombre de ningún canónico — inofensivo dejarlo, pero es ruido).
> - `FAMILIA_A_CANONICO["DESTILERIA"] = "DESTILERIA_RECUPERADO"` — esto es **ahora ambiguo**: hay DOS proyectos que empiezan con "DESTILERIA" (`DESTILERIA`, el nuevo canónico, y `DESTILERIA_RECUPERADO`, que es OTRO equipo físico distinto, congelado). Antes de la próxima corrida de este script, hay que decidir si la familia "DESTILERIA" del disco recolectado debe mapear a uno, al otro, o si hace falta separar la keyword en dos variantes más específicas.

---

## 3. `filtrar_acd_para_convertir.py` — Etapa 3: separar lo fresco de lo viejo

**Qué hace:** con la lista de la Etapa 2, copia a una carpeta de trabajo (`ACD_Para_Convertir/`) **solo** los archivos individuales con fecha de modificación entre el 01/07/2026 y hoy — listos para que alguien los abra en Studio 5000 y los exporte a `.L5X`. Las familias cuyo archivo más reciente es de 2023-2025 quedan en cuarentena, **sin copiarse**, listadas aparte.

**Regla de negocio (decidida explícitamente por Ingeniería, 13/08/2026) — no es un criterio técnico, es una decisión de proceso:**
1. El filtro de fecha es **por archivo individual, no por familia**: si una familia tiene 3 backups de 2025 y 1 de agosto 2026, se copia SOLO el de agosto.
2. Una familia entera cae en cuarentena si **ninguno** de sus archivos cae en la ventana Jul/Ago 2026.
3. Lo que cae en cuarentena **no se tagea directo** — el paso siguiente es exportar ese `.ACD` a `.L5X` a mano y correr `cruzar_planta_viva.py` contra los Excel de Yanco para confirmar que las variables siguen vivas en el PLC real, antes de re-evaluar si se incorpora.

**Cómo correrlo:**
```bash
python filtrar_acd_para_convertir.py "<ruta a la carpeta dist>" "<ruta ACD_Para_Convertir>"
```

**Salida:**
- `ACD_Para_Convertir/` poblada con lo fresco (copiado, no movido — el original de "dist" queda intacto).
- `REQUIEREN_VALIDACION_YANCO.csv` — una fila por familia en cuarentena, con su archivo más reciente y la ruta de origen.

**Configuración que podés necesitar tocar:** la ventana de fecha (01/07/2026 en adelante) está escrita como constante cerca del `def main()` (línea ~133) — si la regla de negocio cambia (ej. "todo lo posterior a tal fecha"), es el único lugar a tocar.

---

## 4. `auditar_masivo.py` — entrada alternativa: volcado tabular en vez de `.L5X`

**Cuándo se usa:** cuando lo que llega no es un `.L5X` (con toda su estructura de programa) sino un **volcado plano** — un CSV o Excel con una fila por tag, típicamente exportado desde una herramienta de inventario o desde RSLogix. Se usó para el volcado de ~25.000 tags / ~27 PLCs (`docs/`, archivo `25k_mapeo_exitoso.csv`).

**Reutiliza el motor entero de `auditar_l5x.py`** (`import auditar_l5x as base`) — misma clasificación ISA-5.1, mismas validaciones, mismo mapeo a miembros de UDT. **No es un motor distinto, es una entrada de datos distinta.**

**Limitaciones honestas en modo tabular** (documentadas en el propio script, no es un secreto):
- No hay trazado de cableado FBD — un bloque de escalado sin nombre de instrumento propio solo se puede enlazar por coincidencia de nombre, no por el cable que lo alimenta.
- No hay votación por vecinos de rutina — la herencia de área por Scope se limita a la columna de Programa si el archivo la trae.
- `FISICO_ISA` (alias a I/O físico) solo se detecta si el archivo trae una columna de Alias — una lista plana de NAME+DATATYPE no puede probar el aliasing físico.

**Cómo correrlo:**
```bash
python auditar_masivo.py "inventario_tags.csv"
python auditar_masivo.py "volcado_25k.xlsx"            # requiere openpyxl instalado
python auditar_masivo.py "volcado_25k.xlsx" "Hoja2"    # hoja especifica del Excel
```

**Detección de columnas — no exige nombres exactos.** El script prueba una lista de alias por cada dato que necesita (case-insensitive), y toma el primero que encuentre en el archivo:

| Dato | Nombres de columna aceptados |
|---|---|
| Nombre del tag | `NAME`, `NOMBRE`, `TAG`, `TAG_VIEJO`, `NOMBRE DE TAG`, `TAGNAME` |
| Datatype | `DATATYPE`, `DATA TYPE`, `TIPO`, `TIPO DE DATO`, `DATA_TYPE` |
| Descripción | `DESCRIPTION`, `DESCRIPCION`, `DESC`, `COMENTARIO` |
| Scope/Programa | `SCOPE`, `ALCANCE`, `PROGRAMA`, `NOMBRE DE PROGRAMA`, `PROGRAM` |
| Alias de | `ALIASFOR`, `ALIAS FOR`, `ALIAS`, `ALIAS_DE` |
| PLC | `PLC`, `PLC (PATH)`, `IP`, `CONTROLADOR`, `CONTROLLER` |

Si el Excel que llega tiene un encabezado que no está en ninguna de estas listas (`_detectar_columna()`, línea ~68), la columna correspondiente simplemente no se detecta — no tira error, pero el motor va a trabajar con menos información de la que el archivo realmente tiene. **Si un volcado nuevo usa nombres de columna raros, agregarlos a la lista correspondiente (`COLS_NOMBRE`, `COLS_DATATYPE`, etc., línea ~52) antes de correr, no después de revisar por qué salió mal.**

**Salida:** `25k_mapeo_exitoso.csv` / `25k_sin_clasificar.csv` en `resultados/` (nivel raíz del proyecto, no `auto_agustin/resultados/` — es una carpeta separada a propósito, para no mezclarse con las corridas del pipeline principal).

---

## 5. `escanear_referencias_logica.py` — detección de tags "zombi"

**Cuándo se usa:** DESPUÉS de correr `auditar_l5x.py`/`procesar_todos_l5x.py` Y `cruzar_planta_viva.py` sobre los 12 PLCs — no antes, no en paralelo. Si `auto_agustin/resultados_cruzados/` no existe todavía, el script se niega a correr y te lo dice.

**Qué problema resuelve:** que un tag esté vivo en la tabla de memoria del PLC (lo que ya confirma `Estado_Planta='En Uso'` vía el Excel de Yanco) **no prueba que algo lo use**. Este script escanea toda la lógica de programa real (texto de rungs RLL, diagramas FBD — `Sheet`/`IRef`/`ORef`/`Block`/`Wire`) y arma el "vocabulario de lógica" del controlador: el set de identificadores que efectivamente aparecen en algún rung o diagrama activo.

**Reutiliza `extraer_tags_referenciados()` de `auditar_l5x.py`** — la misma función que el motor principal ya usa (validada) para la herencia de área por Scope. No duplica el parseo RLL/FBD.

**Detalle técnico importante si tocás este script:** los sufijos de miembro de UDT se resuelven distinto según la fuente. En texto RLL, `extraer_tags_referenciados()` ya separa `XIC(Bomba_Agua.Cmd_Run)` en los tokens `BOMBA_AGUA` y `CMD_RUN` (la raíz queda sola). En operandos FBD, el atributo `Operand` viene **completo** como un solo token (`"BOMBA_AGUA.CMD_RUN"`) — este script agrega, además, la porción antes del primer separador como token propio, para que la raíz también cuente y no genere un falso "zombi".

**Cómo correrlo:**
```bash
python escanear_referencias_logica.py
```
Sin argumentos — descubre solos los proyectos ya cruzados en `auto_agustin/resultados_cruzados/`.

**Salida:** no genera un CSV nuevo — **escribe una columna nueva, `Referenciado_En_Logica` ('Si'/'No'), directamente en los mismos CSV** que ya tienen `Estado_Planta`/`IP_Fisica` del cruce con Yanco. Es un enriquecimiento in-place, no un reporte aparte.

---

## 6. Resumen: qué tocar si...

| Situación | Script | Qué tocar |
|---|---|---|
| Llegó un PLC nuevo a la planta | `analizar_dist_recolectado.py` | Agregar su nombre a `PALABRAS_CLAVE_PLANTA` y `FAMILIA_A_CANONICO` |
| Un volcado tabular nuevo usa nombres de columna raros | `auditar_masivo.py` | Agregar el nombre a la lista `COLS_*` correspondiente (línea ~52) |
| Cambió la ventana de fecha "código fresco" | `filtrar_acd_para_convertir.py` | La constante de fecha cerca de `main()` |
| El barrido de una PC nueva trae carpetas de ruido distintas | `recolector_fuentes_plc.py` | `CARPETAS_SISTEMA_IGNORAR` |
| Hace falta re-agrupar equipos con un patrón de sufijo nuevo | `recolector_fuentes_plc.py` / `analizar_dist_recolectado.py` | `limpiar_nombre_equipo()` / lógica de agrupamiento por familia |
| Un PLC cambió de nombre canónico (como `jw2013`→`DESTILERIA`) | `analizar_dist_recolectado.py` | `FAMILIA_A_CANONICO` — **ver la advertencia de la Sección 2, todavía pendiente** |
