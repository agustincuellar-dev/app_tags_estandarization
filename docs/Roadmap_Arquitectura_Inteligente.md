# Roadmap de Arquitectura — Tags App "inteligente" y contextual
## Ingenio La Florida

**Fecha:** 27 de agosto de 2026
**Estado:** diseño, no implementado. Este documento es la base para una
sesión de desarrollo futura — no se tocó código ni la base de datos al
escribirlo.

---

## 1. Por qué

Hoy, tanto el motor de auditoría (`src/auditar_l5x.py`) como la lógica de
excepciones por PLC viven en **constantes Python hardcodeadas**:
`AREA_DEFECTO_POR_PLC`, `MAPEO_AREA_OVERRIDE_POR_PLC`,
`PREFIJOS_FLAG_SETPOINT`, `DATATYPES_INTERNOS`, etc. Funciona, pero tiene
un costo estructural:

- **Cada excepción nueva es una edición de código + redeploy.** El caso de
  hoy mismo (27/08/2026) es el ejemplo perfecto: el prefijo `DES` significa
  *Destilería* (área 200) en toda la planta, excepto en
  `Calderas_8_9_10_Desaireador`, donde significa *Desaireador* (área 300).
  Resolverlo bien —sin pisar el mapeo global— requirió tocar **6 funciones**
  de `auditar_l5x.py` y enhebrar un parámetro nuevo (`mapeo_area`) a través
  de toda la cadena de llamadas (`clasificar()` → `procesar()` →
  `construir_indice_scope()` → `heredar_area_por_scope()` →
  `transformar_interna_a_miembro()`). Es exactamente el tipo de cambio que
  una tabla de excepciones resolvería con un `INSERT`.
- **El conocimiento de "por qué" vive en comentarios de código**, no en un
  lugar que un ingeniero de planta (no programador) pueda consultar o
  editar.
- **Los tags que el motor no reconoce mueren en un CSV** (`_sin_clasificar.csv`)
  que nadie vuelve a abrir salvo que alguien pida explícitamente "mostrame
  el remanente" — como pasó varias veces hoy mismo, a mano, PLC por PLC.

Las tres piezas de este roadmap atacan cada uno de esos tres puntos.

---

## 2. Diccionario Contextual por Excepción de PLC

Reemplaza `MAPEO_AREA_OVERRIDE_POR_PLC` (constante Python) por una tabla:
el prefijo `DES` sigue significando Área 200 (Destilería) en general, pero
se puede anular puntualmente para un PLC específico sin tocar el mapeo
global ni el código.

### 2.1 Tabla `ExcepcionesPrefijoPLC`

Se agrega a `app_etiquetas/schema.sql`, mismo estilo que la tabla `areas`
ya existente:

```sql
-- Excepciones de mapeo prefijo->area, scoped a un PLC especifico.
-- Un prefijo (ej. 'DES') puede significar un area distinta segun el
-- controlador de origen -- esta tabla es la fuente de verdad de esas
-- excepciones, en vez de vivir hardcodeada en auditar_l5x.py.
CREATE TABLE IF NOT EXISTS excepciones_prefijo_plc (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plc_nombre      TEXT NOT NULL,             -- match por prefijo del
                                                -- nombre de archivo .L5X,
                                                -- ej. 'Calderas_8_9_10_Desaireador'
    prefijo         TEXT NOT NULL,             -- ej. 'DES'
    area_id         INTEGER NOT NULL REFERENCES areas(id),
    motivo          TEXT,                      -- ej. 'DES = Desaireador
                                                -- (equipo de calderas) en
                                                -- este PLC, no Destileria'
    activo          INTEGER NOT NULL DEFAULT 1,
    creado_por      TEXT,
    fecha_creacion  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (plc_nombre, prefijo)
);

CREATE INDEX IF NOT EXISTS idx_excepciones_plc ON excepciones_prefijo_plc(plc_nombre, activo);
```

### 2.2 Cómo la consulta el motor (Python)

Versión data-driven de la función `mapeo_area_para_plc()` que ya existe
hoy en `auditar_l5x.py` (hoy lee de la constante `MAPEO_AREA_OVERRIDE_POR_PLC`;
acá lee de la tabla):

```python
def mapeo_area_para_plc(nombre_archivo, conn):
    """Devuelve el diccionario {prefijo: cod_area} efectivo para este PLC:
    el mapeo global (tabla `areas`, vía su columna `codigo`) con las
    excepciones activas de `excepciones_prefijo_plc` aplicadas encima.
    Reemplaza la constante Python MAPEO_AREA_OVERRIDE_POR_PLC."""
    base_name = os.path.basename(nombre_archivo).upper()

    # 1. Mapeo global: se arma una sola vez y se puede cachear en memoria
    #    por corrida (no cambia dentro de una misma ejecucion del motor).
    filas_area = conn.execute("SELECT codigo, id FROM areas WHERE activo = 1").fetchall()
    efectivo = {codigo: area_id for codigo, area_id in filas_area}

    # 2. Excepciones para ESTE PLC especificamente (match por prefijo del
    #    nombre de archivo, igual criterio que AREA_DEFECTO_POR_PLC hoy).
    excepciones = conn.execute(
        """
        SELECT prefijo, area_id FROM excepciones_prefijo_plc
        WHERE activo = 1 AND ? LIKE plc_nombre || '%'
        """,
        (base_name,),
    ).fetchall()
    for prefijo, area_id in excepciones:
        efectivo[prefijo] = area_id

    return efectivo
```

Con esto, el caso `DES` de hoy se resuelve con un solo `INSERT`, sin tocar
`auditar_l5x.py`:

```sql
INSERT INTO excepciones_prefijo_plc (plc_nombre, prefijo, area_id, motivo, creado_por)
VALUES ('Calderas_8_9_10_Desaireador', 'DES',
        (SELECT id FROM areas WHERE codigo = '300'),
        'DES = Desaireador (equipo de calderas) en este PLC, no Destileria',
        'ingenieria');
```

---

## 3. Tabla de Aprendizaje / Curaduría (Bandeja de Pendientes)

Reemplaza el flujo actual (`_sin_clasificar.csv`, invisible hasta que
alguien lo pide) por una bandeja consultable y accionable desde la Tags App.

### 3.1 Tabla `TagsNoClasificados`

```sql
-- Bandeja de tags que el motor de auditoria no supo clasificar. En vez
-- de morir en un CSV, quedan aca a la espera de que un usuario les
-- asigne una regla (o los descarte a mano, caso por caso).
CREATE TABLE IF NOT EXISTS tags_no_clasificados (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    plc_nombre              TEXT NOT NULL,
    tag_original            TEXT NOT NULL,
    datatype                TEXT,
    alias_for               TEXT,
    motivo_no_clasificado   TEXT,               -- la nota que el motor ya
                                                 -- genera hoy (columna
                                                 -- 'validacion' del CSV)
    fecha_deteccion         TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    estado                  TEXT NOT NULL DEFAULT 'Pendiente'
                                CHECK (estado IN ('Pendiente','Regla_Creada','Descartado')),
    regla_aplicada          TEXT,                -- que regla lo resolvio
                                                  -- (trazabilidad)
    resuelto_por            TEXT,
    fecha_resolucion        TEXT,
    UNIQUE (plc_nombre, tag_original)
);

CREATE INDEX IF NOT EXISTS idx_no_clasificados_estado ON tags_no_clasificados(plc_nombre, estado);
```

### 3.2 Flujo

1. El motor de auditoría, en cada corrida, hace `INSERT OR IGNORE` de cada
   fila `SIN_CLASIFICAR` en esta tabla (el `UNIQUE(plc_nombre, tag_original)`
   evita duplicar el mismo tag en corridas sucesivas). El CSV puede seguir
   generándose en paralelo como respaldo, o dejar de generarse.
2. En la Tags App, una pantalla nueva ("Pendientes de clasificar") lista
   la bandeja **agrupada por prefijo/datatype** — el mismo análisis que se
   hizo a mano, PLC por PLC, varias veces en esta sesión
   (`SENSOR_*`, `FALLA_*`, `PROTEC_*`, etc.).
3. Un usuario selecciona un grupo y, con un clic, define la regla
   ("mandar a INTERNA" / "mapear a función X") — la app actualiza en lote
   todas las filas de ese grupo a `estado='Regla_Creada'`, guarda
   `regla_aplicada` para trazabilidad, y (en la versión madura) la regla
   misma queda en una tabla de reglas en vez de en una constante Python
   (ver nota de cierre).

---

## 4. Constructor de Tags para Contratistas

Función standalone que expone el estándar hacia afuera (una empresa
contratista que necesita generar tags para un proyecto nuevo) sin exponer
la base de datos completa ni requerir que conozcan los `id` de las tablas.
Reutiliza el mismo patrón que ya implementa
`app_etiquetas/database.py::proponer_siguiente_tag()`
(`[AREA]_[VARIABLE][FUNCION]_[NUMERO]`, ej. `250_PT_001`), pero con firma
pensada para valores discretos, no ids de FK.

```python
CATALOGO_TIPO_EQUIPO = {
    "TRANSMISOR_PRESION": "PT",
    "TRANSMISOR_NIVEL": "LT",
    "TRANSMISOR_TEMPERATURA": "TT",
    "TRANSMISOR_CAUDAL": "FT",
    "VALVULA_CONTROL": "PCV",   # o el sufijo que corresponda segun la variable
    "VALVULA_SEGURIDAD": "PSV",
    "DAMPER": "D",
}

CATALOGO_AREA = {
    "MOLIENDA": "100",
    "DESTILERIA": "200",
    "CALDERAS": "300",
    "CLARIFICACION": "400",
    "EVAPORACION": "500",
    "COCIMIENTO": "600",
    "CENTRIFUGADO": "700",
    "SECADO_ENVASE": "800",
    "FUERZA_MOTRIZ": "900",
}


def construir_tag(area: str, tipo_equipo: str, correlativo: int, fluido: str = "") -> str:
    """Genera el tag normalizado [AREA]_[FUNCION]_[NUMERO] a partir de
    parametros discretos, pensado para que lo llame un contratista externo
    sin conocer la base de datos ni los ids de las tablas.

    area          : clave de CATALOGO_AREA (ej. 'CALDERAS') o codigo directo ('300')
    tipo_equipo   : clave de CATALOGO_TIPO_EQUIPO (ej. 'TRANSMISOR_PRESION')
    correlativo   : numero de lazo (entero positivo). NO se valida contra
                    la base de datos aca -- esa validacion (evitar
                    duplicados, respetar el rango del area) la hace
                    database.py::proponer_siguiente_tag() al momento de
                    guardar. Esta funcion solo arma el string.
    fluido        : opcional, informativo (queda en el campo Comentarios,
                    no en el tag) -- ej. 'vapor', 'agua de imbibicion'.

    Devuelve el tag completo (str) o lanza ValueError con un mensaje
    describible si el area o el tipo de equipo no estan en el catalogo.
    """
    cod_area = CATALOGO_AREA.get(area.upper(), area if area in CATALOGO_AREA.values() else None)
    if not cod_area:
        raise ValueError(
            f"Area '{area}' no reconocida. Opciones: {sorted(CATALOGO_AREA)} "
            f"o un codigo numerico directo ({sorted(CATALOGO_AREA.values())})."
        )

    funcion = CATALOGO_TIPO_EQUIPO.get(tipo_equipo.upper())
    if not funcion:
        raise ValueError(
            f"Tipo de equipo '{tipo_equipo}' no reconocido. "
            f"Opciones: {sorted(CATALOGO_TIPO_EQUIPO)}."
        )

    if not isinstance(correlativo, int) or correlativo <= 0:
        raise ValueError(f"Correlativo debe ser un entero positivo, recibido: {correlativo!r}")

    tag = f"{cod_area}_{funcion}_{correlativo:03d}"
    return tag


# Ejemplos de uso:
construir_tag("CALDERAS", "TRANSMISOR_PRESION", 12)
# -> '300_PT_012'

construir_tag("DESTILERIA", "VALVULA_CONTROL", 3, fluido="vapor")
# -> '200_PCV_003'   (el fluido no entra al tag, queda como dato aparte
#                      para el campo Comentarios/Descripcion en Tags App)

construir_tag("MOLIENDA", "SENSOR_DE_HUMO", 1)
# -> ValueError: Tipo de equipo 'SENSOR_DE_HUMO' no reconocido. Opciones: [...]
```

---

## 5. Nota de cierre

Las tres piezas son complementarias, no independientes:

- **§2 (excepciones)** y **§3 (curaduría)** son los dos lugares donde hoy
  vive **código Python que debería ser datos** — cada uno resuelve un tipo
  distinto de parche (mapeo de área vs. clasificación de tag).
- **§4 (constructor)** es la pieza que faltaba para exponer el estándar
  **hacia afuera** (contratistas, integradores) sin darles acceso a la
  base de datos ni pedirles que entiendan el esquema relacional.
- Un paso natural más allá de este roadmap (no incluido aquí, para no
  mezclar diseño con ejecución): las reglas que hoy resuelven la bandeja
  de §3 (ej. "todo `PROTEC_*` → INTERNA") también podrían migrar a una
  tabla `ReglasClasificacion` en vez de constantes Python — mismo
  argumento que §2, aplicado a `clasificar()` en vez de a `mapeo_area_para_plc()`.

**Nada de esto está implementado.** Es la base para una sesión de
desarrollo futura sobre `app_etiquetas/schema.sql`, `app_etiquetas/database.py`
y `src/auditar_l5x.py`.
