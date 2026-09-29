"""Alta de la propuesta masiva en la base de produccion -- por olas, DRY-RUN por defecto.

LEER ANTES DE EJECUTAR
----------------------
- Por defecto corre en DRY-RUN: NO abre la base en modo escritura ni toca nada.
- Solo escribe con el flag explicito `--apply`.
- Fuente unica: `exports/propuesta_numeracion_masiva_180926.csv` (v3, 99 tags). La base solo se
  consulta para resolver catalogos, detectar colisiones y verificar.
- Con `--apply`: backup byte-identico con timestamp + backup por API, UNA transaccion
  (BEGIN IMMEDIATE) por ola, `INSERT OR IGNORE` de la fila XV del catalogo de funciones DENTRO de
  la transaccion (no antes), alta de los tags + fila de auditoria 'Migrado de <identidad>',
  re-chequeo en el instante de insertar (tag inexistente y numero sin colision contra produccion),
  verificacion dentro de la transaccion y COMMIT. Ante error o colision: ROLLBACK total.

OLAS
----
--ola 1 : areas 200 y 300 -> 13 lazos / 39 tags. Base 20 tags -> 59.
--ola 2 : areas 100, 500, 600 y 700 -> 20 lazos / 60 tags. Requiere la ola 1 aplicada: 59 -> 119.
La ola 2 no se puede aplicar sola (el conteo post es acumulativo); en dry-run avisa y muestra el
plan completo igual.

PUERTA DE CALIDAD ISA (bloquea el paquete si falla)
--------------------------------------------------
Para los 99 tags se corre el validador de la propia app (app_etiquetas/validador_isa.py,
isa_rules.py) y la lectura humana (app_etiquetas/app_tags.py). Cualquier hallazgo duro aborta la
ola antes de la transaccion, tambien en dry-run.

Uso:
    python src/insertar_propuesta_masiva.py --ola 1              # dry-run ola 1
    python src/insertar_propuesta_masiva.py --ola 2              # dry-run ola 2
    python src/insertar_propuesta_masiva.py --ola 1 --apply      # escribe (requiere autorizacion)
    python src/insertar_propuesta_masiva.py --ola 2 --apply
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "app_etiquetas"))

CSV_PROPUESTA = RAIZ / "exports" / "propuesta_numeracion_masiva_180926.csv"
CSV_PROPUESTA_DELTA = RAIZ / "exports" / "propuesta_numeracion_masiva_180926.csv"
DB_PRODUCCION = RAIZ / "app_etiquetas" / "tags_ingenio.db"
DIR_BACKUPS = RAIZ / "app_etiquetas" / "backups"

TAGS_BASE = 20               # produccion hoy: 11 manuales + 9 del alta del 18/09
USUARIO = "Agustin"
USUARIO_AUDITORIA = "agustin (via Hermes)"

OLAS = {
    1: {"areas": ("200", "300"), "lazos": 13, "tags": 39, "total_antes": 20, "total_despues": 59},
    2: {"areas": ("100", "500", "600", "700"), "lazos": 20, "tags": 60, "total_antes": 59, "total_despues": 119},
}

COLUMNAS_REQUERIDAS = (
    "Lazo", "Rol", "PLC", "Program", "Routine", "Instancia_AOI", "Area", "Variable_ISA", "Funcion_ISA",
    "Numero_Propuesto", "Tag_Propuesto", "Migrado_De", "AliasFor_Direccion_Fisica", "Pin_Salida",
    "Descripcion_Propuesta", "Fluido_Proceso", "Tipo_Senal", "Entrada_Salida_BD", "DataType_BD",
    "Estado_Propuesta", "Escritura_SQLite",
)

SQL_XV = "INSERT OR IGNORE INTO funciones (letra, nombre, descripcion) VALUES ('XV', 'Válvula Todo/Nada', 'Válvula todo/nada (on-off) de lazo, convención de casa area+variable+función')"
SQL_INSERT = """
INSERT INTO tags (tag_completo, area_id, variable_id, funcion_id, numero_loop, descripcion,
                  ubicacion, estado, creado_por, plc_origen, comentarios, datatype, alias_for,
                  fluido_proceso, tipo_senal, entrada_salida)
VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
SQL_AUDITORIA = "INSERT INTO auditoria (tag_id, accion, detalle, usuario) VALUES (?, 'CREACION', ?, ?)"


def sha256(ruta: Path) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def abrir_solo_lectura(ruta: Path) -> sqlite3.Connection:
    conexion = sqlite3.connect(Path(ruta).resolve().as_uri() + "?mode=ro", uri=True)
    conexion.execute("PRAGMA query_only=ON")
    return conexion


def leer_propuesta(ruta: Path, ola: int) -> list[dict]:
    """Lee SOLO el CSV final y devuelve las filas de la ola pedida."""
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        todas = list(csv.DictReader(archivo, delimiter=";"))
    faltantes = [c for c in COLUMNAS_REQUERIDAS if not todas or c not in todas[0]]
    if faltantes:
        raise SystemExit("Faltan columnas en el CSV: %s" % faltantes)
    areas = OLAS[ola]["areas"]
    filas = [f for f in todas if f["Area"] in areas]
    if len(todas) != 99:
        raise SystemExit("El CSV debe tener 99 filas (v3); tiene %d" % len(todas))
    if len(filas) != OLAS[ola]["tags"]:
        raise SystemExit("La ola %d debe tener %d filas; tiene %d" % (ola, OLAS[ola]["tags"], len(filas)))
    if len({f["Lazo"] for f in filas}) != OLAS[ola]["lazos"]:
        raise SystemExit("La ola %d debe tener %d lazos; tiene %d"
                         % (ola, OLAS[ola]["lazos"], len({f["Lazo"] for f in filas})))
    tags = [f["Tag_Propuesto"] for f in filas]
    if len(set(tags)) != len(tags):
        raise SystemExit("Hay Tag_Propuesto repetidos en la ola %d" % ola)
    for fila in filas:
        if "NO_INSERTAR" not in fila["Estado_Propuesta"]:
            raise SystemExit("La fila %s no esta marcada NO_INSERTAR" % fila["Tag_Propuesto"])
        if fila["Escritura_SQLite"].strip().upper() != "NO":
            raise SystemExit("La fila %s no declara Escritura_SQLite=NO" % fila["Tag_Propuesto"])
    return filas


def cargar_catalogos(conexion: sqlite3.Connection) -> dict:
    areas = {f[1]: f[0] for f in conexion.execute("SELECT id, codigo FROM areas")}
    variables = {f[1]: f[0] for f in conexion.execute("SELECT id, letra FROM variables")}
    funciones = {f[1]: f[0] for f in conexion.execute("SELECT id, letra FROM funciones")}
    return {"areas": areas, "variables": variables, "funciones": funciones}


def leer_delta(ruta: Path) -> list[dict]:
    """Lee la propuesta delta completa, sin asumir 99 filas ni olas.

    La base se consulta después, siempre en mode=ro, para separar existentes de nuevas.
    """
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    if not filas:
        raise SystemExit("La propuesta delta esta vacia: %s" % ruta)
    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in filas[0]]
    if faltantes:
        raise SystemExit("Faltan columnas en el CSV delta: %s" % faltantes)
    tags = [f["Tag_Propuesto"] for f in filas]
    if len(set(tags)) != len(tags):
        raise SystemExit("Hay Tag_Propuesto repetidos en el CSV delta")
    for fila in filas:
        if "NO_INSERTAR" not in fila["Estado_Propuesta"]:
            raise SystemExit("La fila %s no esta marcada NO_INSERTAR" % fila["Tag_Propuesto"])
        if fila["Escritura_SQLite"].strip().upper() != "NO":
            raise SystemExit("La fila %s no declara Escritura_SQLite=NO" % fila["Tag_Propuesto"])
    return filas


def planificar_delta(filas: list[dict], catalogos: dict, conexion: sqlite3.Connection,
                     con_alias: bool) -> tuple:
    """Consulta existentes con SELECT ro y devuelve (plan_nuevo, existentes, duras, avisos)."""
    existentes = {r[0] for r in conexion.execute("SELECT tag_completo FROM tags")}
    ya = [f for f in filas if f["Tag_Propuesto"] in existentes]
    nuevas = [f for f in filas if f["Tag_Propuesto"] not in existentes]
    plan, duras, avisos = planificar(nuevas, catalogos, conexion, con_alias)
    return plan, ya, duras, avisos


def aplicar_delta(plan: list[dict], total_antes: int, esperado: int,
                  con_auditoria: bool, db: Path = DB_PRODUCCION,
                  dir_backups: Path = DIR_BACKUPS) -> int:
    """Aplica solamente el plan nuevo de delta, con conteo esperado total_antes + N."""
    if contar_tags(db) != total_antes:
        print("[ABORTA] Conteo actual %d distinto al esperado %d antes del delta." % (contar_tags(db), total_antes))
        return 2
    hash_antes = sha256(db)
    byte_identico, por_api = crear_backups(db, dir_backups, 5)
    problemas = verificar_backups(byte_identico, por_api, db, total_antes)
    if problemas:
        print("[ABORTA] Backups no confiables: %s" % "; ".join(problemas))
        return 2
    conexion = sqlite3.connect(str(db), isolation_level=None)
    tags_delta = {f["tag"] for f in plan}
    try:
        conexion.execute("BEGIN IMMEDIATE")
        conexion.execute(SQL_XV)
        for ficha in plan:
            if conexion.execute("SELECT 1 FROM tags WHERE tag_completo = ?", (ficha["tag"],)).fetchone():
                raise RuntimeError("%s aparecio durante el delta" % ficha["tag"])
            intrusos = [r[0] for r in conexion.execute(
                "SELECT tag_completo FROM tags WHERE area_id=? AND numero_loop=?",
                (ficha["area_id"], ficha["numero"])) if r[0] not in tags_delta]
            if intrusos:
                raise RuntimeError("%s: numero ocupado por %s" % (ficha["tag"], intrusos))
            cur = conexion.execute(SQL_INSERT, fila_insert(ficha))
            if con_auditoria:
                conexion.execute(SQL_AUDITORIA, (cur.lastrowid, "Migrado de %s" % ficha["migrado_de"], USUARIO_AUDITORIA))
        total = conexion.execute("SELECT count(*) FROM tags").fetchone()[0]
        if total != esperado:
            raise RuntimeError("conteo delta %d, esperado %d" % (total, esperado))
        conexion.execute("COMMIT")
    except Exception as error:
        conexion.execute("ROLLBACK")
        conexion.close()
        print("[ABORTA] ROLLBACK delta: %s" % error)
        return 3
    finally:
        try: conexion.close()
        except Exception: pass
    print("[OK] Delta aplicado: %d tags nuevos; %d -> %d" % (len(plan), total_antes, contar_tags(db)))
    print("      SHA antes: %s" % hash_antes)
    print("      SHA despues: %s" % sha256(db))
    print("      integrity: %s" % integrity(db))
    return 0


# --------------------------------------------------------------- puerta de calidad ISA
def validar_con_la_app(filas: list[dict], existentes: list[str], catalogo_funciones) -> tuple:
    """Corre el validador ISA y la lectura humana de la app sobre las filas de la ola.

    Devuelve (problemas_duros, sugerencias). Un problema duro bloquea el paquete.
    """
    import isa_rules  # app_etiquetas/isa_rules.py
    import validador_isa  # app_etiquetas/validador_isa.py
    import app_tags  # app_etiquetas/app_tags.py

    problemas, sugerencias = [], []
    # La lectura humana del area consulta db.listar_areas() (conexion de la app, potencialmente
    # read-write). Se precarga el cache del modulo con datos de NUESTRA conexion mode=ro para que
    # la app no abra la base.
    with closing(abrir_solo_lectura(DB_PRODUCCION)) as c:
        app_tags._AREAS_CATALOGO_CACHE = {f[0]: f[1] for f in c.execute("SELECT codigo, nombre FROM areas")}

    universo = list(existentes) + [f["Tag_Propuesto"] for f in filas]
    for fila in filas:
        tag = fila["Tag_Propuesto"]
        ok, mensaje = isa_rules.validar_funcion_isa(fila["Funcion_ISA"])
        if not ok:
            problemas.append("%s: %s" % (tag, mensaje))
        permitidas = isa_rules.funciones_permitidas_para_variable(fila["Variable_ISA"], catalogo_funciones)
        if fila["Funcion_ISA"] not in permitidas:
            problemas.append("%s: la funcion %s no esta permitida para la variable %s"
                             % (tag, fila["Funcion_ISA"], fila["Variable_ISA"]))
        faltantes, sug = validador_isa.auditar_tag_recien_guardado(
            {"tag_completo": tag}, [t for t in universo if t != tag])
        problemas.extend("%s: %s" % (tag, f) for f in faltantes)
        sugerencias.extend("%s: %s" % (tag, s) for s in sug)
        try:
            lectura = app_tags.traducir_tag_humano(tag, app_tags.DICCIONARIOS)
        except Exception as error:  # la lectura humana no puede romper
            problemas.append("%s: la lectura humana fallo (%s)" % (tag, error))
            continue
        if not lectura or "no estándar" in lectura:
            problemas.append("%s: la lectura humana no resolvio el tag (%r)" % (tag, lectura))
    return problemas, sugerencias


# --------------------------------------------------------------- planificacion
def validar_descripcion_procedencia(fila: dict) -> str | None:
    """Bloquea altas futuras si el CSV no trae la procedencia legible exigida."""
    descripcion = fila.get("Descripcion_Propuesta", "")
    identidad = fila.get("Migrado_De", "")
    esperado = "Migrado de: %s" % identidad
    if esperado not in descripcion:
        return "%s: Descripcion_Propuesta no contiene '%s'" % (fila["Tag_Propuesto"], esperado)
    if (fila.get("Rol") == "SALIDA" and identidad.startswith("CANAL_CRUDO:")
            and "sin tag de campo en el PLC: la salida escribe directo al canal" not in descripcion):
        return "%s: falta la aclaracion CANAL_CRUDO de salida en Descripcion_Propuesta" % fila["Tag_Propuesto"]
    return None


def planificar(filas: list[dict], catalogos: dict, conexion: sqlite3.Connection, con_alias: bool) -> tuple:
    """Devuelve (plan, colisiones_duras, avisos). No escribe nada."""
    plan, duras, avisos = [], [], []
    existentes = {f[0] for f in conexion.execute("SELECT tag_completo FROM tags")}
    ocupados = {(f[0], f[1]) for f in conexion.execute("SELECT area_id, numero_loop FROM tags")}
    for fila in filas:
        tag = fila["Tag_Propuesto"]
        error_procedencia = validar_descripcion_procedencia(fila)
        if error_procedencia:
            duras.append(error_procedencia)
        area_id = catalogos["areas"].get(fila["Area"])
        variable_id = catalogos["variables"].get(fila["Variable_ISA"])
        funcion_id = catalogos["funciones"].get(fila["Funcion_ISA"])
        numero = int(str(fila["Numero_Propuesto"]).zfill(3))
        partes = tag.split("_")
        if len(partes) != 3 or partes[0] != fila["Area"] or partes[1] != fila["Variable_ISA"] + fila["Funcion_ISA"]:
            duras.append("%s: el tag no se compone como Area_VariableFuncion_Numero segun el CSV" % tag)
        if str(fila["Numero_Propuesto"]).zfill(3) != "%03d" % numero:
            duras.append("%s: Numero_Propuesto '%s' no es de 3 digitos" % (tag, fila["Numero_Propuesto"]))
        for nombre, valor in (("area", area_id), ("variable", variable_id), ("funcion", funcion_id)):
            if valor is None:
                duras.append("%s: no se pudo resolver el id de %s desde el CSV" % (tag, nombre))
        if None in (area_id, variable_id, funcion_id):
            continue
        if tag in existentes:
            duras.append("%s: ya existe en la base (tag_completo UNIQUE)" % tag)
        if (area_id, numero) in ocupados:
            duras.append("%s: el numero %03d ya esta ocupado en el area %s" % (tag, numero, fila["Area"]))
        if "%03d" % numero in (fila.get("Numeros_Ocupados_Area_Resumen") or "").split("|"):
            avisos.append("%s: el numero %03d aparece en el resumen de ocupados del area" % (tag, numero))
        plan.append({
            "tag": tag, "area_id": area_id, "variable_id": variable_id, "funcion_id": funcion_id,
            "numero": numero, "lazo": fila["Lazo"], "rol": fila["Rol"],
            "descripcion": fila["Descripcion_Propuesta"], "estado": fila.get("Estado_BD") or "Planificado",
            "plc_origen": fila["PLC"], "datatype": fila["DataType_BD"] or "REAL",
            "alias_for": (fila["AliasFor_Direccion_Fisica"] if con_alias else ""),
            "alias_csv": fila["AliasFor_Direccion_Fisica"],
            "fluido": fila["Fluido_Proceso"], "tipo_senal": fila["Tipo_Senal"] or "Analógico",
            "entrada_salida": fila["Entrada_Salida_BD"] or "N/D", "migrado_de": fila["Migrado_De"],
            "comentarios": "Migrado de: %s" % fila["Migrado_De"],
        })
    return plan, duras, avisos


def fila_insert(ficha: dict) -> tuple:
    return (ficha["tag"], ficha["area_id"], ficha["variable_id"], ficha["funcion_id"], ficha["numero"],
            ficha["descripcion"], ficha["estado"], USUARIO, ficha["plc_origen"], ficha["comentarios"],
            ficha["datatype"], ficha["alias_for"], ficha["fluido"], ficha["tipo_senal"],
            ficha["entrada_salida"])


def contar_tags(ruta: Path) -> int:
    with closing(abrir_solo_lectura(ruta)) as conexion:
        return conexion.execute("SELECT count(*) FROM tags").fetchone()[0]


def integrity(ruta: Path) -> str:
    with closing(abrir_solo_lectura(ruta)) as conexion:
        return conexion.execute("PRAGMA integrity_check").fetchone()[0]


def huella_contenido(ruta: Path) -> str:
    with closing(abrir_solo_lectura(ruta)) as conexion:
        filas = conexion.execute(
            "SELECT tag_completo, area_id, variable_id, funcion_id, numero_loop, estado, comentarios "
            "FROM tags ORDER BY tag_completo").fetchall()
    return hashlib.sha256(repr(filas).encode("utf-8")).hexdigest()


def crear_backups(db: Path, dir_backups: Path, ola: int) -> tuple:
    """Devuelve (backup byte-identico, backup por API)."""
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    Path(dir_backups).mkdir(parents=True, exist_ok=True)
    byte_identico = Path(dir_backups) / ("tags_ingenio_antes_ola%d_%s_byte_identico.db" % (ola, marca))
    shutil.copy2(db, byte_identico)
    por_api = Path(dir_backups) / ("tags_ingenio_antes_ola%d_%s_api.db" % (ola, marca))
    with closing(sqlite3.connect(str(db))) as origen, closing(sqlite3.connect(str(por_api))) as copia:
        origen.backup(copia)
    return byte_identico, por_api


def verificar_backups(byte_identico: Path, por_api: Path, db: Path, tags_esperados: int) -> list[str]:
    problemas = []
    if not byte_identico.exists() or not por_api.exists():
        return ["no se crearon los dos backups"]
    if sha256(byte_identico) != sha256(db):
        problemas.append("el backup byte-identico no coincide con la base (hash distinto)")
    for etiqueta, ruta in (("byte-identico", byte_identico), ("api", por_api)):
        if contar_tags(ruta) != tags_esperados:
            problemas.append("el backup %s tiene %d tags (se esperaban %d)"
                             % (etiqueta, contar_tags(ruta), tags_esperados))
        if integrity(ruta) != "ok":
            problemas.append("integrity_check del backup %s = %s" % (etiqueta, integrity(ruta)))
        if huella_contenido(ruta) != huella_contenido(db):
            problemas.append("el contenido de tags del backup %s no coincide con la base" % etiqueta)
    return problemas


def imprimir_plan(ola: int, plan: list[dict], duras: list[str], avisos: list[str], problemas_isa: list[str],
                  sugerencias: list[str], con_auditoria: bool, db: Path, hash_db: str, tags_actuales: int,
                  backups: tuple) -> None:
    info = OLAS[ola]
    print("=" * 90)
    print("PLAN DE ALTA POR OLAS -- ola %d (areas %s)" % (ola, ", ".join(info["areas"])))
    print("=" * 90)
    print("Base destino .......: %s" % db)
    print("SHA-256 actual .....: %s" % hash_db)
    print("Tags en la base ....: %d  (esperado antes: %d / despues: %d)"
          % (tags_actuales, info["total_antes"], info["total_despues"]))
    print("Filas de la ola ....: %d tags / %d lazos" % (len(plan), len({f["lazo"] for f in plan})))
    print("Backups previstos ..: %s" % backups[0].name)
    print("                      %s" % backups[1].name)
    print("Fila de auditoria ..: %s" % ("SI (detalle 'Migrado de <identidad>' por alta)"
                                        if con_auditoria else "NO (--sin-auditoria)"))
    print("Catalogo funciones .: INSERT OR IGNORE de XV dentro de la transaccion de esta ola")
    print()
    print("CAMPOS DE CADA ALTA (espejo de los 20 tags ya existentes):")
    for ficha in plan:
        print("-" * 90)
        print("  tag_completo    = %s   [%s / %s]" % (ficha["tag"], ficha["lazo"].split("/")[0], ficha["rol"]))
        print("  area_id/variable_id/funcion_id = %s / %s / %s" % (ficha["area_id"], ficha["variable_id"], ficha["funcion_id"]))
        print("  numero_loop     = %d" % ficha["numero"])
        print("  descripcion     = %s" % ficha["descripcion"])
        print("  estado          = %s | creado_por = %s | plc_origen = %s" % (ficha["estado"], USUARIO, ficha["plc_origen"]))
        print("  comentarios     = %s" % ficha["comentarios"])
        print("  datatype        = %s | tipo_senal = %s | entrada_salida = %s" % (ficha["datatype"], ficha["tipo_senal"], ficha["entrada_salida"]))
        print("  fluido_proceso  = %s | alias_for = %r | ubicacion = ''" % (ficha["fluido"], ficha["alias_for"]))
        print("  INSERT (parametros exactos) = %r" % (fila_insert(ficha),))
    print()
    print("PUERTA DE CALIDAD ISA (validador y lectura humana de la app):")
    print("  problemas duros   : %s" % ("NINGUNO" if not problemas_isa else ""))
    for problema in problemas_isa:
        print("     - %s" % problema)
    print("  sugerencias de la app: %d (no bloquean: la app siempre sugiere un indicador local)"
          % len(sugerencias))
    print("VALIDACIONES PREVIAS:")
    print("  colisiones duras  : %s" % ("NINGUNA" if not duras else ""))
    for problema in duras:
        print("     - %s" % problema)
    print("  avisos            : %s" % ("NINGUNO" if not avisos else ""))
    for aviso in avisos:
        print("     - %s" % aviso)
    print("=" * 90)


def aplicar(ola: int, plan: list[dict], con_auditoria: bool, db: Path = DB_PRODUCCION,
            dir_backups: Path = DIR_BACKUPS) -> int:
    info = OLAS[ola]
    hash_antes = sha256(db)
    tags_antes = contar_tags(db)
    if tags_antes != info["total_antes"]:
        print("[ABORTA] La base tiene %d tags y la ola %d espera %d antes." % (tags_antes, ola, info["total_antes"]))
        if ola == 2:
            print("         Corra y aplique primero la ola 1 (areas 200 y 300).")
        return 2
    byte_identico, por_api = crear_backups(db, dir_backups, ola)
    problemas = verificar_backups(byte_identico, por_api, db, tags_antes)
    if problemas:
        print("[ABORTA] Backups no confiables: %s" % "; ".join(problemas))
        return 2
    print("[OK] Backups verificados: %s (byte-identico, SHA-256 identico a la base)" % byte_identico.name)
    print("                          %s (API, mismo contenido de tags, integrity ok)" % por_api.name)

    conexion = sqlite3.connect(str(db), isolation_level=None)
    tags_de_la_ola = {f["tag"] for f in plan}
    try:
        conexion.execute("BEGIN IMMEDIATE")
        # El catalogo de funciones se completa DENTRO de la transaccion (nunca antes).
        cursor_xv = conexion.execute(SQL_XV)
        print("[OK] Catalogo XV: INSERT OR IGNORE ejecutado dentro de la transaccion (filas nuevas: %d)"
              % cursor_xv.rowcount)
        for ficha in plan:
            # re-chequeo en el instante de insertar (contra ocupantes AJENOS a esta ola: los 3 tags
            # de un lazo comparten numero a proposito)
            if conexion.execute("SELECT count(*) FROM tags WHERE tag_completo = ?", (ficha["tag"],)).fetchone()[0]:
                raise RuntimeError("%s: ya existe al momento de insertar" % ficha["tag"])
            ajenos = [fila[0] for fila in conexion.execute(
                "SELECT tag_completo FROM tags WHERE area_id = ? AND numero_loop = ?",
                (ficha["area_id"], ficha["numero"]))]
            intrusos = [t for t in ajenos if t not in tags_de_la_ola]
            if intrusos:
                raise RuntimeError("%s: el numero %03d esta ocupado en el area por %s (fuera de esta ola)"
                                   % (ficha["tag"], ficha["numero"], intrusos))
            cursor = conexion.execute(SQL_INSERT, fila_insert(ficha))
            if con_auditoria:
                conexion.execute(SQL_AUDITORIA,
                                 (cursor.lastrowid, "Migrado de %s" % ficha["migrado_de"], USUARIO_AUDITORIA))
        total = conexion.execute("SELECT count(*) FROM tags").fetchone()[0]
        if total != info["total_despues"]:
            raise RuntimeError("conteo dentro de la transaccion = %d (se esperaban %d)" % (total, info["total_despues"]))
        faltantes = [f["tag"] for f in plan if conexion.execute(
            "SELECT count(*) FROM tags WHERE tag_completo = ?", (f["tag"],)).fetchone()[0] != 1]
        if faltantes:
            raise RuntimeError("tags no insertados: %s" % faltantes)
        conexion.execute("COMMIT")
        print("[OK] Transaccion COMMIT: %d tags insertados y verificados dentro de la transaccion." % len(plan))
    except Exception as error:  # colision, error de integridad o cualquier fallo
        conexion.execute("ROLLBACK")
        conexion.close()
        print("[ABORTA] ROLLBACK ejecutado, la base quedo sin cambios. Motivo: %s" % error)
        return 3
    finally:
        try:
            conexion.close()
        except Exception:
            pass

    estado_integridad = integrity(db)
    with closing(abrir_solo_lectura(db)) as c:
        auditorias = c.execute("SELECT count(*) FROM auditoria WHERE accion = 'CREACION' AND detalle LIKE 'Migrado de %'").fetchone()[0]
        xv = c.execute("SELECT id, letra, nombre FROM funciones WHERE letra = 'XV'").fetchone()
    print("VERIFICACION POST-INSERCION:")
    print("  tags .............: %d -> %d (esperado %d)" % (tags_antes, contar_tags(db), info["total_despues"]))
    print("  integrity_check ..: %s" % estado_integridad)
    print("  SHA-256 antes ....: %s" % hash_antes)
    print("  SHA-256 despues ..: %s" % sha256(db))
    print("  auditoria 'Migrado de' acumulada: %d filas" % auditorias)
    print("  catalogo XV ......: %s" % (xv,))
    print("  backups ..........: %s | %s" % (byte_identico.name, por_api.name))
    return 0 if (contar_tags(db) == info["total_despues"] and estado_integridad == "ok") else 4


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Alta de propuesta masiva por olas o delta. Dry-run por defecto.")
    parser.add_argument("--ola", type=int, choices=sorted(OLAS), required=False)
    parser.add_argument("--delta", action="store_true", help="Consulta SELECT ro, saltea tags existentes y planifica solo nuevos.")
    parser.add_argument("--csv", default=None)
    parser.add_argument("--db", default=str(DB_PRODUCCION))
    parser.add_argument("--backup-dir", default=str(DIR_BACKUPS))
    parser.add_argument("--apply", action="store_true", help="Escribe de verdad (requiere autorizacion).")
    parser.add_argument("--sin-auditoria", action="store_true", help="No deja fila en auditoria.")
    parser.add_argument("--con-alias-for", action="store_true",
                        help="Escribe el AliasFor del CSV en tags.alias_for (por defecto '' como en el alta de 9).")
    args = parser.parse_args(argv)
    if bool(args.delta) == bool(args.ola):
        parser.error("use exactamente una modalidad: --ola 1|2 o --delta")

    db = Path(args.db)
    if args.delta:
        ruta = Path(args.csv) if args.csv else CSV_PROPUESTA_DELTA
        filas = leer_delta(ruta)
        with closing(abrir_solo_lectura(db)) as conexion:
            catalogos = cargar_catalogos(conexion)
            existentes_db = [f[0] for f in conexion.execute("SELECT tag_completo FROM tags")]
            plan, ya, duras, avisos = planificar_delta(filas, catalogos, conexion, args.con_alias_for)
        candidatos_delta = [f for f in filas if f["Tag_Propuesto"] not in {x["Tag_Propuesto"] for x in ya}
                           and "SENSOR_COMPARTIDO" not in f["Lazo"]]
        problemas_isa, sugerencias = validar_con_la_app(candidatos_delta, existentes_db, set(catalogos["funciones"]))
        print("=" * 90)
        print("PLAN DELTA (SELECT en mode=ro; dry-run por defecto)")
        print("CSV ...............: %s" % ruta)
        print("Base ..............: %s" % db)
        print("SHA actual ........: %s" % sha256(db))
        print("Tags en producción : %d" % len(existentes_db))
        print("Filas CSV ..........: %d" % len(filas))
        print("Ya existentes .....: %d (se saltean)" % len(ya))
        print("Nuevos planificados: %d" % len(plan))
        print("Conteo esperado ...: %d + %d = %d" % (len(existentes_db), len(plan), len(existentes_db) + len(plan)))
        print("Colisiones duras ..: %s" % ("NINGUNA" if not duras else "; ".join(duras)))
        print("Problemas ISA .....: %s" % ("NINGUNO" if not problemas_isa else "; ".join(problemas_isa)))
        print("Auditoria por alta : %s" % ("SI" if not args.sin_auditoria else "NO"))
        print("=" * 90)
        if not args.apply:
            print("MODO DRY-RUN: no se escribio nada y la base solo se abrio mode=ro.")
            return 0
        if duras or problemas_isa:
            print("[ABORTA] El delta tiene validaciones bloqueantes pendientes.")
            return 2
        return aplicar_delta(plan, len(existentes_db), len(existentes_db) + len(plan),
                             not args.sin_auditoria, db, Path(args.backup_dir))

    ruta = Path(args.csv) if args.csv else CSV_PROPUESTA
    filas = leer_propuesta(ruta, args.ola)
    with closing(abrir_solo_lectura(db)) as conexion:
        catalogos = cargar_catalogos(conexion)
        existentes = [f[0] for f in conexion.execute("SELECT tag_completo FROM tags")]
        plan, duras, avisos = planificar(filas, catalogos, conexion, args.con_alias_for)
    sugerencias = []
    problemas_isa, sugerencias = validar_con_la_app(filas, existentes, set(catalogos["funciones"]))
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups_previstos = (Path(args.backup_dir) / ("tags_ingenio_antes_ola%d_%s_byte_identico.db" % (args.ola, marca)),
                         Path(args.backup_dir) / ("tags_ingenio_antes_ola%d_%s_api.db" % (args.ola, marca)))
    imprimir_plan(args.ola, plan, duras, avisos, problemas_isa, sugerencias, not args.sin_auditoria,
                  db, sha256(db), contar_tags(db), backups_previstos)

    if not args.apply:
        print("MODO DRY-RUN: no se escribio nada. La base de produccion no se abrio en modo escritura.")
        if problemas_isa:
            print("[OJO] %d problemas duros del validador ISA: el paquete esta BLOQUEADO." % len(problemas_isa))
        if duras:
            print("[OJO] Hay %d colisiones duras: con --apply la transaccion abortaria y haria ROLLBACK." % len(duras))
        if args.ola == 2:
            print("[OJO] La ola 2 espera %d tags antes (hoy hay %d): con --apply abortaria hasta aplicar la ola 1."
                  % (OLAS[2]["total_antes"], contar_tags(db)))
        return 0

    if problemas_isa:
        print("[ABORTA] El validador ISA de la app reporto problemas duros: el paquete esta bloqueado.")
        return 2
    if duras:
        print("[ABORTA] No se ejecuta --apply con colisiones duras pendientes.")
        return 2
    print("MODO --apply AUTORIZADO: iniciando backups y transaccion de la ola %d..." % args.ola)
    return aplicar(args.ola, plan, not args.sin_auditoria, db, Path(args.backup_dir))


if __name__ == "__main__":
    sys.exit(main())
