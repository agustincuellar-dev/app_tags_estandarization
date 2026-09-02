# Manual de Mantenimiento de Código
## Motor de Auditoría ISA-5.1 + Tags App — Ingenio La Florida

**Fecha:** 28 de agosto de 2026
**Audiencia:** cualquier desarrollador que herede este proyecto sin haber estado en las sesiones de armado.
**Objetivo:** que puedas tocar el motor sin romperlo, y que sepas *dónde* tocar cada tipo de cambio antes de escribir una sola línea.

Este documento asume que ya leíste `docs/Manual_Estandarizacion.md` (la norma de negocio: qué es un tag, qué es `Mundo A`/`Mundo B`) y `docs/Roadmap_Arquitectura_Inteligente.md` (por qué existe el Aprendizaje por Excepción). Acá el foco es **operativo**: qué archivo abrir, qué función editar, qué NO tocar.

---

## 0. Mapa de los 3 sistemas

```
src/auditar_l5x.py          <- EL MOTOR. Lee un .L5X, clasifica cada tag,
                                propone un tag_nuevo. Standalone: no depende
                                de la Tags App ni de ninguna base de datos.

src/procesar_todos_l5x.py   <- Orquesta el motor sobre los 12 PLCs canonicos.
src/cruzar_planta_viva.py   <- Cruza el resultado contra los Excel de Yanco.
src/generar_dashboard_planta.py <- Arma Dashboard_Planta.csv.

src/aprendizaje_motor.py    <- EL PUENTE. Conecta el motor con la base de
                                datos de la Tags App (opcional, con import
                                diferido -- ver Seccion 3).

app_etiquetas/               <- LA TAGS APP. Alta manual de tags nuevos +
  database.py                   Aprendizaje por Excepcion (reglas_aprendidas,
  aprendizaje.py                tags_no_clasificados). Tiene su propia base
  schema.sql                    SQLite (tags_ingenio.db).
  app_tags.py
```

**Regla de oro de esta arquitectura:** `auditar_l5x.py` nunca debe importar nada de `app_etiquetas/`. Si necesitás que el motor sepa algo de la base de datos, el lugar es `aprendizaje_motor.py`, no el motor mismo. Esto es intencional (ver Sección 3) — no lo "arregles" agregando un `import database` arriba de `auditar_l5x.py`, vas a crear un import circular y vas a romper el uso standalone del motor.

---

## 1. Ejemplo crítico: cambiar el prefijo de área de 3 a 4 dígitos

### 1.1 Qué significa el cambio

Hoy un área es un código plano de 3 dígitos (`"200"` = Destilería). Si el Ingenio decide pasar a un esquema de **área + subárea** (`"2001"` = Destilería, subárea 01), hay que distinguir dos cosas que se confunden fácil:

- **A) Alargar el código como string** — trivial, es buscar y reemplazar literales. Cubierto en 1.2.
- **B) Que el sistema DERIVE la subárea automáticamente** (que un tag `CUBA_1` se resuelva solo a `2001` en vez de `2000` porque "cuba" implica fermentación) — esto es lógica nueva, no un find-replace. Cubierto en 1.3.

Si lo único que necesitan es que el número tenga 4 dígitos pero **la subárea la asigna una persona a mano en la Tags App** (no el motor solo), con 1.2 alcanza.

### 1.2 Parte A — Alargar el código (mecánico, bajo riesgo)

Los códigos de área son strings literales en Python — **no hay padding con ceros ni validación de longitud en ningún lado**. Confirmado por búsqueda en todo el repo: el único `:03d` que existe es el del **número de lazo correlativo** (`PT_001`), no del código de área. Esto significa que el cambio es, literalmente, cambiar el valor del string en 4 lugares. No hay trampa oculta.

#### Archivo 1: `src/auditar_l5x.py` — `MAPEO_AREA` (línea ~52)

Diccionario **palabra-clave → código**. Se usa en `detectar_area()` para leer el área desde el propio nombre del tag.

```python
# ANTES
MAPEO_AREA = {
    "RCP":  "000",   # Recepcion y Preparacion de Cana
    "MOL":  "100",   # Molienda
    "DES":  "200",   # Destileria (alcohol 96%)
    ...
}

# DESPUES (Destileria pasa a 2001, subárea "principal" por defecto)
MAPEO_AREA = {
    "RCP":  "0001",
    "MOL":  "1001",
    "DES":  "2001",  # Destileria (alcohol 96%) - subarea 01 = planta principal
    ...
}
```

#### Archivo 1 (continuación): `PALABRAS_CLAVE_AREA` y `PALABRAS_CLAVE_EXCLUSIVAS` (línea ~1092 y ~1144)

**Ojo con estos dos**: acá el código de área es la **CLAVE** del diccionario, no el valor — es la forma inversa de `MAPEO_AREA`. Si solo cambiás `MAPEO_AREA` y te olvidás de re-clavar estos dos, el fallback semántico (`area_por_palabras_clave()`) va a seguir devolviendo códigos de 3 dígitos viejos y vas a tener una planta con área mixta 3/4 dígitos.

```python
# ANTES
PALABRAS_CLAVE_AREA = {
    "100": ["CANA", "TRAPICHE", "MOL", "MOENDA", ...],
    "200": ["DEST", "DESTIL", "DESTILERIA", "CUBA", "CUBAS", "MOSTO", ...],
}
PALABRAS_CLAVE_EXCLUSIVAS = {
    "250": ["ANHIDRO", "TAMIZ", "TAMICES", "DESHIDRATACION", ...],
}

# DESPUES
PALABRAS_CLAVE_AREA = {
    "1001": ["CANA", "TRAPICHE", "MOL", "MOENDA", ...],
    "2001": ["DEST", "DESTIL", "DESTILERIA", "CUBA", "CUBAS", "MOSTO", ...],
}
PALABRAS_CLAVE_EXCLUSIVAS = {
    "2501": ["ANHIDRO", "TAMIZ", "TAMICES", "DESHIDRATACION", ...],
}
```

#### Archivo 1 (continuación): `AREA_DEFECTO_POR_PLC` y `MAPEO_AREA_OVERRIDE_POR_PLC` (línea ~87 y ~132)

Mismo criterio — son overrides scoped por PLC, valor = código de área:

```python
# ANTES
AREA_DEFECTO_POR_PLC = {
    "CALD_LA_FLORIDA":  "300",
    "DESTILERIA":       "200",
    ...
}
MAPEO_AREA_OVERRIDE_POR_PLC = {
    "Calderas_8_9_10_Desaireador": {"DES": "300"},
}

# DESPUES
AREA_DEFECTO_POR_PLC = {
    "CALD_LA_FLORIDA":  "3001",
    "DESTILERIA":       "2001",
    ...
}
MAPEO_AREA_OVERRIDE_POR_PLC = {
    "Calderas_8_9_10_Desaireador": {"DES": "3001"},
}
```

#### Archivo 2: `app_etiquetas/database.py` — `_seed_if_empty()` (línea ~121) y `_migrar_nombres_area()` (línea ~57)

Esto siembra la tabla `areas` de la Tags App **solo en una base nueva y vacía** (ver Sección 1.4 para la base que ya tiene datos):

```python
# ANTES
areas = [
    ("000", "Recepción y Preparación de Caña (Desfibrador)", 0, 99),
    ("200", "Destilería", 200, 299),
    ...
]

# DESPUES
areas = [
    ("0001", "Recepción y Preparación de Caña (Desfibrador)", 0, 99),
    ("2001", "Destilería", 2000, 2099),
    ...
]
```

`rango_inicio`/`rango_fin` son **vestigiales** (ver el propio comentario en `database.py::proponer_siguiente_tag`, línea ~294): no se usan como tope real, el corte real es el de 999 del correlativo. Podés actualizarlos por prolijidad, pero no rompen nada si quedan con el rango viejo.

#### Archivo 3: `app_etiquetas/schema.sql` — tabla `areas`

**No requiere ningún cambio de columna.** `codigo TEXT NOT NULL UNIQUE` — es texto libre, ya acepta cualquier longitud. Esto es deliberado: nunca se validó el ancho del código a nivel de schema, precisamente para no bloquear un cambio como este.

#### Archivo 4: `tags_ingenio.db` — LA BASE QUE YA TIENE DATOS

Este es el paso que más gente se olvida. `_seed_if_empty()` **no toca una tabla que ya tiene filas**. Si simplemente editás el código y volvés a correr `init_db()`, los 12 códigos de área en la base real de producción **van a seguir siendo de 3 dígitos** — el motor va a generar tags nuevos con 4 dígitos que no van a encontrar su fila de área en la Tags App (los combos van a quedar desalineados).

Necesitás una migración explícita, siguiendo el mismo patrón que ya existe en `_migrar_nombres_area()` (agregada 27/08/2026, ver `database.py`):

```python
def _migrar_codigos_area_a_4_digitos(conn):
    """UNA SOLA VEZ: agrega el digito de subarea (00 = planta principal,
    sin desagregar todavia) a los codigos de area de 3 digitos ya
    cargados. Idempotente: el WHERE length()=3 hace que correrla dos
    veces no rompa nada (la segunda vez no encuentra filas de 3 digitos
    para migrar)."""
    conn.execute("UPDATE areas SET codigo = codigo || '01' WHERE length(codigo) = 3")
    conn.commit()
```

Y agregarla al `init_db()`, junto a las otras migraciones:

```python
    _migrar_columnas_faltantes(conn)
    _migrar_nombres_area(conn)
    _migrar_codigos_area_a_4_digitos(conn)   # <- nueva
    _seed_if_empty(conn)
```

**Los tags ya emitidos NO se tocan.** Un tag ya creado (`200_PT_001`) queda como está — la migración solo cambia el código de la tabla `areas`, no reescribe el campo `tag_completo` de tags históricos. Eso es correcto: cambiar retroactivamente un tag que ya está pegado en un tablero físico sería un desastre.

### 1.3 Parte B — Si además querés que el motor DERIVE la subárea sola

Esto es lógica nueva, no un cambio de string. El patrón a copiar es el que ya existe para excepciones por PLC (`MAPEO_AREA_OVERRIDE_POR_PLC`, ver `docs/Roadmap_Arquitectura_Inteligente.md` sección 2): un segundo diccionario, más específico, que se consulta ANTES del genérico.

```python
# Nuevo diccionario: palabra-clave -> subarea (2 digitos), solo para
# areas que ya se desagregaron. Se consulta DESPUES de resolver el area
# base por MAPEO_AREA, ANTES de devolver el codigo final.
SUBAREAS_POR_PALABRA_CLAVE = {
    "2001": {  # Destileria: subarea 01 = fermentacion, 02 = destilacion
        "CUBA": "01", "MOSTO": "01", "FERMENT": "01",
        "COLUMNA": "02", "DESTILADORA": "02",
    },
}
```

Esto **no es un cambio de una tarde** — hay que decidir qué pasa cuando un tag no matchea ninguna subárea (¿usa `01` por defecto? ¿queda `SIN_CLASIFICAR`?), y probablemente conviene resolverlo primero con **una regla en `reglas_aprendidas`** (ver Sección 3) antes de codificarlo duro, para no repetir el ciclo de "parche en Python por cada excepción" que motivó construir el Aprendizaje por Excepción.

### 1.4 Checklist de verificación después del cambio

1. `python -c "import ast; ast.parse(open('src/auditar_l5x.py', encoding='utf-8').read())"` — sintaxis.
2. Correr el motor sobre **un solo PLC chico** (`DIBACCO`) antes que sobre los 12: `python -c "import procesar_todos_l5x as o; print(o.procesar_uno('DIBACCO','DIBACCO.L5X'))"`.
3. Revisar que ningún `tag_nuevo_propuesto` haya quedado con un código mezclado (`200_PT_001` conviviendo con `2001_PT_001` para el mismo PLC — señal de que te olvidaste un diccionario).
4. Correr la migración de `tags_ingenio.db` (Sección 1.2, Archivo 4) y confirmar con `SELECT codigo FROM areas` que no queda ningún código de 3 dígitos.
5. Recién ahí, correr el orquestador completo sobre los 12 PLCs.

---

## 2. Gestión de diccionarios y reglas ISA (dónde vive cada cosa)

Todo esto está en `src/auditar_l5x.py`. Es **una sola función larga, `clasificar()`** (línea ~491), que evalúa criterios en cascada — el primero que matchea gana y la función retorna ahí mismo. **El orden importa**: un criterio nuevo agregado al final nunca se va a evaluar si uno de arriba ya devolvió antes.

| Qué querés cambiar | Dónde | Forma |
|---|---|---|
| Un datatype que siempre es lógica interna (nunca instrumento) | `DATATYPES_INTERNOS` (línea 232) | Agregar el string del datatype al `set` |
| Un datatype que es un instrumento analógico válido | `DATATYPES_ANALOGICOS` (línea 262) | Agregar al `set` |
| Un datatype que es una instancia de bloque de escalado (SCP/SCL) | `DATATYPES_INSTANCIA_ESCALADO` (línea 274) | Agregar al `set` |
| Un sufijo de nombre que siempre es interno (`_ALM`, `_RAW`, `_SP`...) | `SUFIJOS_INTERNOS` (línea 224) | Agregar el string a la tupla (con el `_` inicial) |
| Un prefijo de nombre que siempre es interno (`B_`, `SCL_`...) | `PREFIJOS_INTERNOS` (línea 228) | Agregar al `set` (SIN el `_`, se compara el primer token) |
| Un prefijo de flag/consigna suelta (`TRIP_`, `SP_`, `PROTEC_`...) | `PREFIJOS_FLAG_SETPOINT` (línea 532, dentro de `clasificar()`) | Agregar al `set` local |
| Un token que marca un tag derivado/acumulado (`ACUM`, `TURNO`...) | `TOKENS_TAG_DERIVADO` (línea 826) | Agregar al `set` |
| Una palabra en español/portugués que traduce a una letra ISA (`VIBRACAO`→V) | `KEYWORDS_VARIABLE_LOCAL` (línea 187) | Agregar tupla `(palabra, letra)` a la lista — **orden importa**: más específico primero |

### La categoría `EQUIPOS_LOGICA`

Vive **adentro** de `clasificar()` (línea ~516-522), no en un diccionario aparte — es un `if` explícito porque su condición combina datatype + token de nombre:

```python
if (datatype or "").upper() == "ARRANQUE_MOTOR_2" or "ARRANQUE" in tokens_nombre_full:
    notas.append("EQUIPOS_LOGICA: arranque/logica de motor -- mapeo de equipo de fuerza motriz (Mantenimiento Mecanico), no es un lazo ISA")
    return "EQUIPOS_LOGICA", funcion, area, notas
```

Si necesitás que **otra** clase se comporte igual que `EQUIPOS_LOGICA` (no computa éxito ISA, no entra al denominador), tenés que tocar **3 lugares**, no solo `auditar_l5x.py` — es higiene de reporte, vive fuera del motor:

1. `src/procesar_todos_l5x.py`, variable `CLASES_FUERA_DE_PROCESO` (dentro de `procesar_uno()`).
2. `src/generar_dashboard_planta.py`, variable `CLASES_HIGIENE` (nivel módulo).
3. `app_etiquetas/database.py::_migrar_nombres_area` no aplica acá — pero si la nueva clase también necesita convivir con `reglas_aprendidas`, revisar el `CHECK` de la columna `accion` en `schema.sql` (ver Sección 3.2).

**No hay una lista maestra única de clases** — es una decisión de diseño para no forzar un enum central que después limita, pero significa que agregar una clase nueva de higiene es un cambio en 2-3 archivos, no en uno.

---

## 3. Código vs. Base de datos — cuándo tocar cada uno

Esta es la pregunta que más tiempo ahorra si la respondés bien antes de empezar a escribir.

### 3.1 Regla práctica

> **¿La excepción se puede describir como "todo tag que [empiece con / sea exactamente / matchee este patrón] X, va a la clase Y (o función Z)"?**
> → **Base de datos.** Cargala en `reglas_aprendidas` desde la Tags App (o con `aprendizaje.resolver_pendiente()` por script). No toques `auditar_l5x.py`.

> **¿El cambio altera CÓMO el motor interpreta la estructura del nombre, no QUÉ significa un patrón puntual?** (ej.: nueva regex para códigos ISA pegados al número, nuevo criterio de prioridad, cambio en cómo se arma el string final del tag)
> → **Código.** Eso vive en `auditar_l5x.py`, no hay forma de resolverlo con una fila de base de datos.

### 3.2 Ejemplos concretos de cada lado

| Cambio | Dónde | Por qué |
|---|---|---|
| "`FIT205` es un transmisor de caudal, mandalo a `F`" | Base de datos (`reglas_aprendidas`, `tipo_match='EXACTO'`) | Es un patrón puntual sobre un tag conocido |
| "Todo lo que empiece con `PROTEC_` es lógica interna" | Base de datos (`tipo_match='PREFIJO'`) | Es una familia de tags, mismo patrón simple |
| "`ME101_10_CORRENTE` es corriente, pero `ME101_10_Reference` es un setpoint — mismo prefijo, destino distinto según el sufijo" | Base de datos (`tipo_match='REGEX'`) | Sigue siendo "patrón → clase", solo que el patrón es más fino |
| "El motor no detecta `FIT100` porque no separa letras de números" | **Código** (`RE_ISA_PEGADO`, línea ~421) | No es un tag puntual, es una regla de TOKENIZACIÓN — afecta a miles de tags futuros que ni siquiera existen todavía |
| "Un tag con datatype `DINT` y código ISA en el nombre debe ganarle al datatype" | **Código** (criterio en `clasificar()`, línea ~639) | Es una regla de PRECEDENCIA entre criterios, no un patrón de nombre |
| "Agregar un área nueva (ej. si el Ingenio construye una planta nueva)" | **Código** (`MAPEO_AREA` + `AREA_DEFECTO_POR_PLC`) | Es estructura de negocio nueva, no una excepción sobre la estructura existente |
| "Cambiar de 3 a 4 dígitos el código de área" | **Código + migración de datos** (Sección 1) | Cambia el formato del dato, no es clasificación |

### 3.3 Cómo cargar una regla sin tocar código (mecánica)

```python
# Desde un script, o desde el boton "Resolver" de la pantalla de
# pendientes de la Tags App (cuando se construya la UI -- hoy las
# funciones existen, la pantalla todavia no).
import sys, os
sys.path.insert(0, "app_etiquetas")
import aprendizaje as ap, database

conn = database.get_connection()
regla_id, resueltos = ap.resolver_pendiente(
    patron="FIT",                    # o el tag exacto, o un regex
    tipo_match="PREFIJO",            # 'EXACTO' | 'PREFIJO' | 'REGEX'
    accion="FUNCION_ISA",
    funcion_isa="F",
    plc_nombre=None,                 # None = vale para TODOS los PLCs;
                                      # pone un nombre de PLC si la regla
                                      # es scoped (ej. el caso DES/Calderas)
    motivo="FIT = caudal, dialecto del integrador tal",
    usuario="tu_nombre",
    conn=conn,
)
conn.close()
```

Esa regla queda persistida. **La próxima vez que corra `procesar_todos_l5x.py` (con `usar_aprendizaje=True`, que es el default), la aplica sola** — no hace falta reiniciar nada, no hace falta tocar `auditar_l5x.py`. Ver `src/aprendizaje_motor.py::clasificar_con_aprendizaje()` para el mecanismo completo, y `docs/Roadmap_Arquitectura_Inteligente.md` sección 6 para el diseño original.

**Precedencia dentro de `reglas_aprendidas` misma** (por si cargás dos reglas que podrían matchear el mismo tag): `EXACTO` > `REGEX` > `PREFIJO`, y dentro de cada tipo, **scoped a un PLC gana sobre global**, y entre varios `PREFIJO` que matchean, **el patrón más largo gana**. Ver `aprendizaje.py::buscar_regla()` si necesitás la implementación exacta.

### 3.4 Trampa a evitar

**El motor de aprendizaje solo se consulta cuando el código ya devolvió `SIN_CLASIFICAR`.** Si un tag ya cae en `FUNCIONAL_ISA`/`INTERNA`/etc por una regla de código, **una fila en `reglas_aprendidas` con el mismo patrón NUNCA se va a evaluar** — el código siempre tiene prioridad sobre la base de datos, no al revés (ver `clasificar_con_aprendizaje()`: primero llama a `motor.clasificar()`, recién si eso da `SIN_CLASIFICAR` consulta la base). Si cargaste una regla y "no pasa nada", lo primero que hay que revisar es si el código ya estaba resolviendo ese tag de otra forma.

---

## 4. Qué NO tocar sin pensarlo dos veces

- **`auditar_l5x.py` no debe importar `app_etiquetas/`** (Sección 0). Si sentís la tentación, el lugar correcto es `aprendizaje_motor.py`.
- **`MAPEO_AREA_OVERRIDE_POR_PLC` es para homónimos, no para reglas generales.** Si `DES` significa una cosa distinta en un PLC puntual, va ahí. Si es una excepción de clasificación (no de área), va en `reglas_aprendidas`.
- **Los CSV de `resultados_cruzados/` son 100% regenerables.** Nunca los edites a mano — se pisan en cada corrida de `cruzar_planta_viva.py`. Si necesitás corregir un dato, corregí el `.L5X` fuente o cargá una regla, no el CSV.
- **`tags_ingenio.db` es la única fuente de verdad de tags YA EMITIDOS.** El motor de auditoría nunca escribe ahí directamente (solo lee, vía `aprendizaje.buscar_regla()`) — el alta real de un tag definitivo sigue siendo manual, desde la Tags App, con la confirmación de un humano.

---

## 5. Contactos y continuidad

Este proyecto no tiene "dueño de código" formal más allá de quien lo mantenga día a día en el Ingenio. Los tres documentos que hay que leer, en orden, para retomarlo desde cero:

1. `docs/Manual_Estandarizacion.md` — la norma de negocio (qué es un tag, Mundo A/Mundo B, reglas de la norma ISA aplicadas).
2. `docs/Roadmap_Arquitectura_Inteligente.md` — por qué existe el Aprendizaje por Excepción y cómo está diseñado.
3. Este documento — cómo tocar el código sin romperlo.

Los `Resumen_Ejecutivo_Avance_*.md` en `docs/` son la bitácora cronológica de decisiones — útiles para entender *por qué* una regla puntual quedó como quedó (casi todo comentario en el código cita la fecha de la sesión donde se decidió), pero no son documentación de referencia, son historial.
