"""
database.py
------------
Capa de acceso a datos del Sistema de Gestión de Tags.
Toda la lógica de negocio (buscar existentes, calcular siguiente
correlativo, evitar duplicados) vive aquí, separada de la interfaz
gráfica. Esto permite, si algún día se quiere migrar de Tkinter a
una app web (Flask), reutilizar este archivo sin cambios.
"""

import sqlite3
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolver_db_path():
    """Ruta de la base de datos, persistente entre ejecuciones.

    En el .exe compilado con PyInstaller database.py vive en una carpeta
    temporal; se busca/crea tags_ingenio.db junto al .exe y, si no existe
    (primer arranque), se copia allí la base incluida para que los guardados
    persistan. En código fuente se usa la base junto a database.py."""
    if getattr(sys, "frozen", False):
        carpeta_exe = os.path.dirname(sys.executable)
        db_persistente = os.path.join(carpeta_exe, "tags_ingenio.db")
        if not os.path.isfile(db_persistente):
            try:
                bundled = os.path.join(BASE_DIR, "tags_ingenio.db")
                if os.path.isfile(bundled):
                    import shutil
                    shutil.copyfile(bundled, db_persistente)
            except OSError:
                pass
        return db_persistente
    return os.path.join(BASE_DIR, "tags_ingenio.db")


DB_PATH = _resolver_db_path()
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


# ------------------------------------------------------------------
# Conexión e inicialización
# ------------------------------------------------------------------
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # permite acceder a columnas por nombre
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Crea las tablas si no existen y precarga catálogos base
    (áreas, variables, funciones) solo si la base está vacía.
    Es seguro llamarla cada vez que arranca el programa."""
    conn = get_connection()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()

    _migrar_columnas_faltantes(conn)
    _migrar_nombres_area(conn)
    _seed_if_empty(conn)
    _cargar_funciones_isa_estandar(conn)
    conn.close()


def _migrar_columnas_faltantes(conn):
    """CREATE TABLE IF NOT EXISTS no agrega columnas nuevas a una tabla ya
    existente. Para bases pobladas en versiones anteriores (ej. las 787
    ya cargadas), se agregan aquí las columnas que falten, sin perder
    datos."""
    columnas = {r["name"] for r in conn.execute("PRAGMA table_info(tags)")}
    if "comentarios" not in columnas:
        conn.execute("ALTER TABLE tags ADD COLUMN comentarios TEXT")
        conn.commit()
    # plc_origen: ya existe en la base real (la agrego un cargador externo
    # el 30/07/2026, fuera de este repo) pero no estaba declarada en
    # schema.sql -- se agrega aca para que quede documentada y para que una
    # base nueva (creada solo desde schema.sql) la tenga tambien.
    if "plc_origen" not in columnas:
        conn.execute("ALTER TABLE tags ADD COLUMN plc_origen TEXT")
        conn.commit()
    if "datatype" not in columnas:
        conn.execute("ALTER TABLE tags ADD COLUMN datatype TEXT")
        conn.commit()
    if "alias_for" not in columnas:
        conn.execute("ALTER TABLE tags ADD COLUMN alias_for TEXT")
        conn.commit()
    if "fluido_proceso" not in columnas:
        conn.execute("ALTER TABLE tags ADD COLUMN fluido_proceso TEXT")
        conn.commit()
    # tipo_senal / entrada_salida (28/08/2026): antes se inferían al vuelo
    # (inferir_tipo_senal/inferir_entrada_salida, ya eliminadas); ahora son
    # columnas físicas con control MANUAL en la UI (Paso 3). El DEFAULT
    # rellena las filas históricas con el valor honesto ('Desconocido' /
    # 'N/D': no se sabe), evitando celdas vacías en la grilla general.
    if "tipo_senal" not in columnas:
        conn.execute("ALTER TABLE tags ADD COLUMN tipo_senal TEXT DEFAULT 'Desconocido'")
        conn.commit()
    if "entrada_salida" not in columnas:
        conn.execute("ALTER TABLE tags ADD COLUMN entrada_salida TEXT DEFAULT 'N/D'")
        conn.commit()


def _migrar_nombres_area(conn):
    """Agrega a la etiqueta de area la palabra que realmente usan los
    operarios del Ingenio (aunque no sea el nombre tecnico/formal), para
    que el combobox de la Tags App sea mas amigable. Idempotente: solo
    actualiza si el nombre sigue siendo exactamente el texto viejo, asi
    es seguro correrla en cada arranque sin duplicar ni pisar un nombre
    que alguien ya haya personalizado a mano."""
    # Dos variantes de nombre viejo por fila: la base real de este
    # Ingenio se sembro en algun momento SIN tildes ("Recepcion y
    # Preparacion de Cana"), asi que el match tiene que cubrir ambas
    # formas para no depender de cual haya quedado grabada.
    renombres = [
        ("000", ("Recepción y Preparación de Caña", "Recepcion y Preparacion de Cana"),
                 "Recepción y Preparación de Caña (Desfibrador)"),
        ("950", ("Tratamiento de Agua y Servicios",),
                 "Tratamiento de Agua y Servicios (Ósmosis)"),
    ]
    for codigo, nombres_viejos, nombre_nuevo in renombres:
        for nombre_viejo in nombres_viejos:
            conn.execute(
                "UPDATE areas SET nombre = ? WHERE codigo = ? AND nombre = ?",
                (nombre_nuevo, codigo, nombre_viejo),
            )
    conn.commit()


def _cargar_funciones_isa_estandar(conn):
    """Carga masiva de funciones (letras sucesivas) de ANSI/ISA-5.1-2024,
    anticipando requerimientos del SCADA. A diferencia de _seed_if_empty,
    esta funcion corre SIEMPRE (no solo con la tabla vacia) y usa
    INSERT OR IGNORE: si la letra ya existe (por la carga masiva de tags o
    por una corrida anterior), NO se toca ni se duplica; solo se insertan
    las que faltan. Es seguro llamarla en cada arranque.

    Fuente: ANSI/ISA-5.1-2024, Tabla 1 (Letras de identificacion) y sus
    notas 4.1.5, docs/911795514-NORMA-ISA-5-1-2024-ESPANOL...pdf.
    """
    funciones_isa = [
        # --- Solicitadas explicitamente ---
        ("SV",  "Válvula de Seguridad / Alivio"),        # Nota 12(a): PSV/TSV/FSV
        ("E",   "Elemento Primario / Sensor"),            # Tabla 1, fila E
        ("Y",   "Convertidor / Relé / I-P"),              # Nota 23/24: dispositivos auxiliares
        ("C",   "Controlador"),
        ("Q",   "Totalizador / Integrador"),              # Tabla 1, fila Q, col 3/4
        ("A",   "Alarma"),                                # Tabla 1, fila A, col 3
        ("AH",  "Alarma de Alta"),
        ("AL",  "Alarma de Baja"),
        ("Z",   "Posición (Switch/Indicador)"),           # convencion practica; Z=primera letra en la norma
        ("ZT",  "Transmisor de Posición"),                # Z (variable) + T (funcion)
        ("ZSC", "Interruptor de Posición Cerrada"),       # Z + S + C (Tabla 1: C='Cerrar')
        ("ZSO", "Interruptor de Posición Abierta"),       # Z + S + O (Tabla 1: O='Abierto')

        # --- Agregadas: vistas en la Tabla 1 y de uso probable en el Ingenio ---
        ("G",   "Visor Local / Indicador de Vidrio"),     # Tabla 1 fila G; usado en PG/TG/LG
        ("K",   "Estación de Control"),                   # Tabla 1 fila K, col 4
        ("U",   "Multifunción"),                          # Tabla 1 fila U, col 3/4
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO funciones (letra, nombre) VALUES (?,?)",
        funciones_isa,
    )
    conn.commit()


def _seed_if_empty(conn):
    cur = conn.execute("SELECT COUNT(*) FROM areas")
    if cur.fetchone()[0] == 0:
        # Catálogo oficial de áreas (códigos numéricos de 3 dígitos, según
        # la tabla vigente del Ingenio). Debe coincidir con MAPEO_AREA de
        # src/auditar_l5x.py.
        areas = [
            ("000", "Recepción y Preparación de Caña (Desfibrador)", 0, 99),
            ("100", "Molienda", 100, 199),
            ("200", "Destilería", 200, 299),
            # Bioetanol (alcohol anhidro) es una planta físicamente distinta
            # de Destilería (alcohol 96%): no comparten área.
            ("250", "Biodestilería", 250, 299),
            ("300", "Calderas / Generación de Vapor", 300, 399),
            ("400", "Clarificación y Encalado", 400, 499),
            ("500", "Evaporación", 500, 599),
            ("600", "Cocimiento / Tachos", 600, 699),
            ("700", "Centrifugado / Purga", 700, 799),
            ("800", "Secado y Envase", 800, 899),
            ("900", "Fuerza Motriz / Turbogeneradores", 900, 949),
            ("950", "Tratamiento de Agua y Servicios (Ósmosis)", 950, 999),
        ]
        conn.executemany(
            "INSERT INTO areas (codigo, nombre, rango_inicio, rango_fin) VALUES (?,?,?,?)",
            areas,
        )

    cur = conn.execute("SELECT COUNT(*) FROM variables")
    if cur.fetchone()[0] == 0:
        variables = [
            ("P", "Presión"),
            ("T", "Temperatura"),
            ("L", "Nivel"),
            ("F", "Flujo / Caudal"),
            ("A", "Análisis (pH, Brix, Pol, etc.)"),
            ("S", "Velocidad"),
            ("W", "Peso / Fuerza"),
            ("C", "Conductividad"),
            ("D", "Densidad"),
        ]
        conn.executemany(
            "INSERT INTO variables (letra, nombre) VALUES (?,?)", variables
        )

    cur = conn.execute("SELECT COUNT(*) FROM funciones")
    if cur.fetchone()[0] == 0:
        funciones = [
            ("T",  "Transmisor"),
            ("I",  "Indicador"),
            ("IC", "Indicador - Controlador"),
            ("C",  "Controlador"),
            ("R",  "Registrador"),
            ("SH", "Switch / Interruptor Alto"),
            ("SL", "Switch / Interruptor Bajo"),
            ("AH", "Alarma Alta"),
            ("AL", "Alarma Baja"),
            ("V",  "Válvula de Control"),
            ("E",  "Elemento Primario"),
        ]
        conn.executemany(
            "INSERT INTO funciones (letra, nombre) VALUES (?,?)", funciones
        )

    cur = conn.execute("SELECT COUNT(*) FROM usuarios")
    if cur.fetchone()[0] == 0:
        usuarios = [("ariel",), ("ricardo",), ("yanco",), ("jesus",), ("diego",)]
        conn.executemany(
            "INSERT INTO usuarios (nombre) VALUES (?)", usuarios
        )

    conn.commit()


# ------------------------------------------------------------------
# Catálogos (para llenar los combobox de la UI)
# ------------------------------------------------------------------
def listar_areas():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM areas WHERE activo = 1 ORDER BY codigo"
    ).fetchall()
    conn.close()
    return rows


def listar_variables():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM variables ORDER BY nombre").fetchall()
    conn.close()
    return rows


def listar_funciones():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM funciones ORDER BY nombre").fetchall()
    conn.close()
    return rows


def listar_usuarios():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM usuarios WHERE activo = 1 ORDER BY nombre"
    ).fetchall()
    conn.close()
    return rows


def agregar_usuario(nombre):
    """Agrega un usuario al catálogo. Si ya existe (UNIQUE), no falla:
    simplemente lo deja como estaba. Devuelve True si se insertó uno nuevo."""
    conn = get_connection()
    try:
        conn.execute("INSERT INTO usuarios (nombre) VALUES (?)", (nombre,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


# ------------------------------------------------------------------
# Núcleo: consulta de existentes + generación del siguiente tag
# ------------------------------------------------------------------
def obtener_tags_existentes(area_id, variable_id, funcion_id):
    """Devuelve los tags ya registrados para la combinación
    Área + Variable + Función, ordenados por número de lazo."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT tag_completo, numero_loop, estado, descripcion
        FROM tags
        WHERE area_id = ? AND variable_id = ? AND funcion_id = ?
        ORDER BY numero_loop
        """,
        (area_id, variable_id, funcion_id),
    ).fetchall()
    conn.close()
    return rows


def proponer_siguiente_tag(area_id, variable_id, funcion_id):
    """Calcula el próximo tag disponible siguiendo el estándar corporativo:

        [AREA]_[VARIABLE][FUNCION]_[NUMERO 3 dígitos]      ej. 250_PV_001

    El correlativo es independiente por combinación Área+Variable+Función y
    arranca en 001 (el prefijo numérico del área ya identifica el sector,
    por lo que el número NO debe partir del rango del área).
    """
    conn = get_connection()
    area = conn.execute("SELECT * FROM areas WHERE id = ?", (area_id,)).fetchone()
    variable = conn.execute(
        "SELECT * FROM variables WHERE id = ?", (variable_id,)
    ).fetchone()
    funcion = conn.execute(
        "SELECT * FROM funciones WHERE id = ?", (funcion_id,)
    ).fetchone()

    # (01/09/2026) Sugerencia inteligente ISA-5.1: se extraen TODOS los
    # números de lazo existentes de la combinación y se propone el PRIMER
    # número libre empezando en 001 (rellena huecos), en vez de MAX+1.
    # Ej.: si existen FV_001, FV_002 y FV_050 -> propone FV_003, no FV_051.
    numeros = conn.execute(
        """
        SELECT numero_loop
        FROM tags
        WHERE area_id = ? AND variable_id = ? AND funcion_id = ?
        ORDER BY numero_loop
        """,
        (area_id, variable_id, funcion_id),
    ).fetchall()
    conn.close()

    usados = {n["numero_loop"] for n in numeros}
    siguiente_numero = 1
    while siguiente_numero in usados:
        siguiente_numero += 1

    # El campo rango_inicio/rango_fin del área es vestigial bajo esta
    # convención (el sector lo da el prefijo, no el número), por eso NO se
    # usa como tope: hacerlo dispararía bloqueos falsos. El único límite
    # real es el de 3 dígitos del estándar.
    if siguiente_numero > 999:
        raise ValueError(
            f"Se agotaron los 3 dígitos del correlativo para "
            f"'{area['codigo']}_{variable['letra']}{funcion['letra']}' (999 tags). "
            f"Contacte al administrador para ampliar la numeración."
        )

    tag_completo = (
        f"{area['codigo']}_{variable['letra']}{funcion['letra']}_{siguiente_numero:03d}"
    )
    return tag_completo, siguiente_numero


# ------------------------------------------------------------------
# Lazos ISA: consulta y construcción de identidad
# ------------------------------------------------------------------
def listar_lazos(area_id, variable_id):
    """Devuelve los lazos existentes de una Área + Variable.

    Cada fila contiene ``numero_loop`` y un resumen de sus tags. Un lazo
    agrupa instrumentos de funciones distintas que comparten el mismo
    número ISA, por ejemplo PT/PC/PV con sufijo 001.
    """
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT numero_loop, GROUP_CONCAT(tag_completo, ', ') AS instrumentos
            FROM (
                SELECT t.numero_loop, t.tag_completo
                FROM tags t
                WHERE t.area_id = ? AND t.variable_id = ?
                ORDER BY t.numero_loop, t.tag_completo
            )
            GROUP BY numero_loop
            ORDER BY numero_loop
            """,
            (area_id, variable_id),
        ).fetchall()
    finally:
        conn.close()


def obtener_instrumentos_lazo(area_id, variable_id, numero_loop):
    """Devuelve todos los instrumentos de un lazo ISA concreto.

    La identidad del lazo es Área + Variable + Número. La función del
    instrumento no participa del filtro porque precisamente es la parte
    que puede variar entre los componentes del mismo lazo.
    """
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT t.tag_completo, t.numero_loop, t.estado, t.descripcion,
                   f.letra AS funcion_letra, f.nombre AS funcion_nombre
            FROM tags t
            JOIN funciones f ON f.id = t.funcion_id
            WHERE t.area_id = ? AND t.variable_id = ? AND t.numero_loop = ?
            ORDER BY t.tag_completo
            """,
            (area_id, variable_id, numero_loop),
        ).fetchall()
    finally:
        conn.close()


def proponer_siguiente_numero_lazo(area_id, variable_id):
    """Devuelve el primer número libre para crear un lazo nuevo.

    Busca en todos los instrumentos de la misma Área + Variable, sin
    separar por función: el número pertenece al lazo completo, no a PT,
    PC, PV u otra función individual.
    """
    conn = get_connection()
    try:
        numeros = conn.execute(
            """
            SELECT DISTINCT numero_loop
            FROM tags
            WHERE area_id = ? AND variable_id = ?
            ORDER BY numero_loop
            """,
            (area_id, variable_id),
        ).fetchall()
    finally:
        conn.close()

    usados = {fila["numero_loop"] for fila in numeros}
    siguiente_numero = 1
    while siguiente_numero in usados:
        siguiente_numero += 1
    if siguiente_numero > 999:
        raise ValueError("Se agotaron los 3 dígitos para este lazo (001-999).")
    return siguiente_numero


def construir_tag(area_id, variable_id, funcion_id, numero_loop):
    """Construye un tag ISA validando sus catálogos y su número de lazo."""
    if not isinstance(numero_loop, int) or isinstance(numero_loop, bool) or not 1 <= numero_loop <= 999:
        raise ValueError("El número de lazo debe ser un entero entre 1 y 999.")

    conn = get_connection()
    try:
        area = conn.execute("SELECT codigo FROM areas WHERE id = ?", (area_id,)).fetchone()
        variable = conn.execute("SELECT letra FROM variables WHERE id = ?", (variable_id,)).fetchone()
        funcion = conn.execute("SELECT letra FROM funciones WHERE id = ?", (funcion_id,)).fetchone()
    finally:
        conn.close()

    if area is None or variable is None or funcion is None:
        raise ValueError("Área, variable o función inválida para construir el tag.")
    return f"{area['codigo']}_{variable['letra']}{funcion['letra']}_{numero_loop:03d}"


# ------------------------------------------------------------------
# Alta de un nuevo tag
# ------------------------------------------------------------------
def crear_tag(
    tag_completo,
    area_id,
    variable_id,
    funcion_id,
    numero_loop,
    descripcion="",
    ubicacion="",
    fabricante="",
    modelo="",
    rango_medicion="",
    unidad="",
    comentarios="",
    estado="Planificado",
    creado_por="",
    datatype="",
    alias_for="",
    tipo_senal="",
    entrada_salida="",
    fluido_proceso="",
):
    """Inserta un nuevo tag. La restricción UNIQUE de la tabla
    garantiza a nivel de base de datos que nunca habrá duplicados,
    incluso si dos personas intentan crear el mismo tag casi
    simultáneamente.

    datatype: opcional, el datatype real del PLC si se conoce (ej. 'BOOL',
    'REAL') -- meramente informativo desde que el Tipo de Señal es un
    control manual (tipo_senal).
    alias_for: opcional, la dirección/alias original del .L5X (ej.
    'Local:2:I.Data.5', 'FIT100_IN') si se conoce -- meramente informativo
    desde que Entrada/Salida es un control manual (entrada_salida).
    tipo_senal: opcional, 'Analógico' / 'Digital' / 'Desconocido' -- valor
    EXPLÍCITO elegido en la UI (Paso 3), guardado en su columna física.
    entrada_salida: opcional, 'Entrada' / 'Salida' / 'Memoria / Red' / 'N/D'
    -- valor EXPLÍCITO elegido en la UI (Paso 3), guardado en su columna
    física.
    fluido_proceso: opcional, qué fluido/producto maneja el instrumento
    (ej. 'Alcohol 90°', 'Flegmasa') -- PURAMENTE INFORMATIVO, nunca entra
    en tag_completo. Ninguno de estos campos es obligatorio para dar de
    alta un tag."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO tags (
                tag_completo, area_id, variable_id, funcion_id, numero_loop,
                descripcion, ubicacion, fabricante, modelo,
                rango_medicion, unidad, comentarios, estado, creado_por,
                datatype, alias_for, tipo_senal, entrada_salida, fluido_proceso
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                tag_completo, area_id, variable_id, funcion_id, numero_loop,
                descripcion, ubicacion, fabricante, modelo,
                rango_medicion, unidad, comentarios, estado, creado_por,
                datatype, alias_for, tipo_senal, entrada_salida, fluido_proceso,
            ),
        )
        tag_id = cur.lastrowid
        conn.execute(
            "INSERT INTO auditoria (tag_id, accion, detalle, usuario) VALUES (?,?,?,?)",
            (tag_id, "CREACION", f"Tag {tag_completo} creado", creado_por),
        )
        conn.commit()
        return tag_id
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise ValueError(
            f"El tag '{tag_completo}' ya existe en la base de datos. "
            f"Refresque la consulta e intente nuevamente."
        ) from e
    finally:
        conn.close()


def obtener_tag_completo(tag_completo):
    """Devuelve un tag con TODOS sus campos, más los datos de sus
    catálogos (código/nombre de área, letra/nombre de variable y función),
    para poblar el formulario de edición. None si no existe."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT t.*, a.codigo AS area_codigo, a.nombre AS area_nombre,
               v.letra AS variable_letra, v.nombre AS variable_nombre,
               f.letra AS funcion_letra, f.nombre AS funcion_nombre
        FROM tags t
        JOIN areas a ON a.id = t.area_id
        JOIN variables v ON v.id = t.variable_id
        JOIN funciones f ON f.id = t.funcion_id
        WHERE t.tag_completo = ?
        """,
        (tag_completo,),
    ).fetchone()
    conn.close()
    return row


# ------------------------------------------------------------------
# Actualización de un tag existente
# ------------------------------------------------------------------
def actualizar_tag(
    tag_completo,
    descripcion="",
    ubicacion="",
    fabricante="",
    modelo="",
    rango_medicion="",
    unidad="",
    comentarios="",
    estado="Planificado",
    modificado_por="",
    datatype="",
    alias_for="",
    tipo_senal="",
    entrada_salida="",
    fluido_proceso="",
):
    """Actualiza los datos editables de un tag YA EXISTENTE.

    Deliberadamente NO permite tocar tag_completo, area_id, variable_id,
    funcion_id ni numero_loop: la identidad ISA del tag (su número de lazo)
    es inmutable una vez asignada — lo que se edita es la información
    complementaria (descripción, ubicación, estado, etc.), nunca el
    número. Lanza ValueError si el tag no existe.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM tags WHERE tag_completo = ?", (tag_completo,)
        ).fetchone()
        if row is None:
            raise ValueError(f"El tag '{tag_completo}' no existe en la base de datos.")
        tag_id = row["id"]

        conn.execute(
            """
            UPDATE tags SET
                descripcion = ?, ubicacion = ?, fabricante = ?, modelo = ?,
                rango_medicion = ?, unidad = ?, comentarios = ?, estado = ?,
                datatype = ?, alias_for = ?, tipo_senal = ?, entrada_salida = ?,
                fluido_proceso = ?, fecha_modificacion = ?
            WHERE id = ?
            """,
            (
                descripcion, ubicacion, fabricante, modelo,
                rango_medicion, unidad, comentarios, estado, datatype, alias_for,
                tipo_senal, entrada_salida, fluido_proceso,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tag_id,
            ),
        )
        conn.execute(
            "INSERT INTO auditoria (tag_id, accion, detalle, usuario) VALUES (?,?,?,?)",
            (tag_id, "MODIFICACION", f"Tag {tag_completo} actualizado", modificado_por),
        )
        conn.commit()
        return tag_id
    finally:
        conn.close()


def buscar_tags(texto=""):
    """Búsqueda libre por texto en tag, descripción, ubicación, alias
    (comentarios / 'Migrado de <alias>' en descripción), PLC de origen o
    fluido/producto. Alimenta la grilla de consulta general de la Tags
    App."""
    conn = get_connection()
    patron = f"%{texto}%"
    rows = conn.execute(
        """
        SELECT t.tag_completo, a.nombre AS area, v.nombre AS variable,
               f.nombre AS funcion, t.descripcion, t.ubicacion,
               t.estado, t.fecha_creacion, t.datatype, t.alias_for,
               t.tipo_senal, t.entrada_salida,
               t.fluido_proceso, t.comentarios, t.plc_origen
        FROM tags t
        JOIN areas a ON a.id = t.area_id
        JOIN variables v ON v.id = t.variable_id
        JOIN funciones f ON f.id = t.funcion_id
        WHERE t.tag_completo LIKE ? OR t.descripcion LIKE ?
           OR t.ubicacion LIKE ? OR t.comentarios LIKE ?
           OR t.plc_origen LIKE ? OR t.fluido_proceso LIKE ?
        ORDER BY t.fecha_creacion DESC
        """,
        (patron, patron, patron, patron, patron, patron),
    ).fetchall()
    conn.close()
    return rows

# ------------------------------------------------------------------
# Eliminación de un tag
# ------------------------------------------------------------------
def eliminar_tag(tag_completo):
    """Elimina DEFINITIVAMENTE un tag de la base de datos (y su historial
    de auditoría asociado). Lanza ValueError si el tag no existe.

    FIX (28/08/2026): la version anterior hacia solo
    'DELETE FROM tags WHERE tag_completo = ?', que SIEMPRE fallaba con
    sqlite3.IntegrityError en cualquier tag creado normalmente -- la
    tabla `auditoria` tiene una FK a tags(id) sin ON DELETE CASCADE, y
    cada alta via crear_tag() ya inserta una fila de auditoria. El boton
    "Eliminar" de la UI estaba roto de fabrica para todo tag real; esta
    version borra primero las filas de auditoria que referencian al tag
    (se pierde esa traza, es el costo de una eliminacion definitiva -- si
    se quiere conservar traza, usar actualizar_tag(estado='Retirado') en
    vez de eliminar_tag())."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM tags WHERE tag_completo = ?", (tag_completo,)
        ).fetchone()
        if row is None:
            raise ValueError(f"El tag '{tag_completo}' no existe en la base de datos.")
        tag_id = row["id"]
        conn.execute("DELETE FROM auditoria WHERE tag_id = ?", (tag_id,))
        conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        conn.commit()
    finally:
        conn.close()


def eliminar_tags_masivos(lista_tags):
    """Elimina DEFINITIVAMENTE una lista de tags y su historial de auditoría.

    Devuelve la cantidad de tags efectivamente eliminados. Los tags de la
    lista que no existan se ignoran. Igual que eliminar_tag(), borra antes
    las filas de auditoria (FK sin ON DELETE CASCADE) para evitar el
    IntegrityError."""
    if not lista_tags:
        return 0
    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(lista_tags))
        filas = conn.execute(
            f"SELECT id FROM tags WHERE tag_completo IN ({placeholders})",
            list(lista_tags),
        ).fetchall()
        ids = [fila["id"] for fila in filas]
        if ids:
            id_ph = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM auditoria WHERE tag_id IN ({id_ph})", ids)
            conn.execute(f"DELETE FROM tags WHERE id IN ({id_ph})", ids)
            conn.commit()
        return len(ids)
    finally:
        conn.close()