"""Alta de los 9 tags aprobados (083 / 081 / 082) en la base de produccion.

SEGUNDO ENTREGABLE -- LEER ANTES DE EJECUTAR
--------------------------------------------
- Por defecto corre en DRY-RUN: NO abre la base en modo escritura ni toca nada.
- Solo escribe con el flag explicito `--apply`.
- Con `--apply`: hace backup con timestamp, abre UNA transaccion (BEGIN IMMEDIATE), inserta los
  9 tags, verifica dentro de la transaccion y hace COMMIT. Ante error o colision: ROLLBACK total.
- Fuente unica: el CSV final `exports/propuesta_numeracion_3_lazos.csv`. No lee ningun otro
  archivo ni tabla como origen de datos (la base solo se consulta para resolver catalogos y
  detectar colisiones).
- Verificacion post-insercion: conteo de 20 tags, PRAGMA integrity_check y SHA-256 antes/despues.

Uso:
    python src/insertar_9_tags_aprobados.py                    # dry-run
    python src/insertar_9_tags_aprobados.py --apply            # escribe (requiere autorizacion)
    python src/insertar_9_tags_aprobados.py --apply --sin-auditoria

CAMPOS QUE ESCRIBE (espejo de los 11 tags manuales existentes)
-------------------------------------------------------------
tag_completo, area_id, variable_id, funcion_id, numero_loop, descripcion, ubicacion ('') ,
estado 'Planificado', creado_por 'Agustin', plc_origen, comentarios 'Migrado de: <identidad PLC>',
datatype, alias_for ('' -- el alias fisico queda trazado en el CSV, columnas Tag_Intermedio y
Camino_Completo_Lazo), fluido_proceso, tipo_senal, entrada_salida. `fecha_creacion` la pone el
DEFAULT de la tabla (datetime('now','localtime')), igual que en los tags manuales.

Ademas deja una fila en `auditoria` (accion 'CREACION', detalle 'Migrado de <identidad PLC>')
porque es el unico lugar de esta base donde el proyecto registra esa trazabilidad
(precedente: 'Migracion masiva SCADA 28/08/2026: Migrado de LT_CUBA_1'). Se puede omitir con
`--sin-auditoria`.
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
CSV_PROPUESTA = RAIZ / "exports" / "propuesta_numeracion_3_lazos.csv"
DB_PRODUCCION = RAIZ / "app_etiquetas" / "tags_ingenio.db"
DIR_BACKUPS = RAIZ / "app_etiquetas" / "backups"

TAGS_ESPERADOS_ANTES = 11
TAGS_ESPERADOS_DESPUES = 20
USUARIO = "Agustin"
USUARIO_AUDITORIA = "agustin (via Hermes)"

COLUMNAS_REQUERIDAS = (
    "Tag_Propuesto", "Area", "Variable_ISA", "Funcion_ISA", "Numero_Propuesto",
    "Descripcion_Propuesta", "Migrado_De", "Fluido_Proceso", "Tipo_Senal",
    "Entrada_Salida_BD", "DataType_BD", "Estado_BD", "PLC", "Estado_Propuesta", "Escritura_SQLite",
)


def sha256(ruta: Path) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def leer_propuesta(ruta: Path = CSV_PROPUESTA) -> list[dict]:
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    if len(filas) != 9:
        raise SystemExit("El CSV debe tener exactamente 9 filas; tiene %d" % len(filas))
    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in filas[0]]
    if faltantes:
        raise SystemExit("Faltan columnas en el CSV v2: %s" % faltantes)
    tags = [f["Tag_Propuesto"] for f in filas]
    if len(set(tags)) != 9:
        raise SystemExit("Hay Tag_Propuesto repetidos en el CSV")
    for fila in filas:
        if "NO_INSERTAR" not in fila["Estado_Propuesta"]:
            raise SystemExit("La fila %s no esta marcada NO_INSERTAR" % fila["Tag_Propuesto"])
        if fila["Escritura_SQLite"].strip().upper() != "NO":
            raise SystemExit("La fila %s no declara Escritura_SQLite=NO" % fila["Tag_Propuesto"])
    return filas


def abrir_solo_lectura(ruta: Path) -> sqlite3.Connection:
    conexion = sqlite3.connect(Path(ruta).resolve().as_uri() + "?mode=ro", uri=True)
    conexion.execute("PRAGMA query_only=ON")
    return conexion


def cargar_catalogos(conexion: sqlite3.Connection) -> dict:
    areas = {fila[1]: fila[0] for fila in conexion.execute("SELECT id, codigo FROM areas")}
    variables = {fila[1]: fila[0] for fila in conexion.execute("SELECT id, letra FROM variables")}
    funciones = {fila[1]: fila[0] for fila in conexion.execute("SELECT id, letra FROM funciones")}
    return {"areas": areas, "variables": variables, "funciones": funciones}


def planificar(filas: list[dict], catalogos: dict, conexion: sqlite3.Connection) -> tuple[list[dict], list[str], list[str]]:
    """Devuelve (plan, colisiones_duras, avisos). No escribe nada."""
    plan, duras, avisos = [], [], []
    existentes = {fila[0] for fila in conexion.execute("SELECT tag_completo FROM tags")}
    ocupados = {(fila[0], fila[1]) for fila in conexion.execute("SELECT area_id, numero_loop FROM tags")}
    for fila in filas:
        tag = fila["Tag_Propuesto"]
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
                duras.append("%s: no se pudo resolver el id de %s a partir del CSV" % (tag, nombre))
        if area_id is None or variable_id is None or funcion_id is None:
            continue
        if tag in existentes:
            duras.append("%s: ya existe en la base (tag_completo UNIQUE)" % tag)
        if (area_id, numero) in ocupados:
            duras.append("%s: el numero %03d ya esta ocupado en el area %s" % (tag, numero, fila["Area"]))
        if fila.get("Numero_En_Identificadores_Vigentes", "NO").strip().upper() == "SI":
            avisos.append("%s: el numero %03d aparece en identificadores vigentes del area" % (tag, numero))
        plan.append({
            "tag": tag, "area_id": area_id, "variable_id": variable_id, "funcion_id": funcion_id,
            "numero": numero, "descripcion": fila["Descripcion_Propuesta"],
            "estado": fila["Estado_BD"] or "Planificado", "plc_origen": fila["PLC"],
            "comentarios": "Migrado de: %s" % fila["Migrado_De"],
            "datatype": fila["DataType_BD"] or "REAL",
            "fluido": fila["Fluido_Proceso"], "tipo_senal": fila["Tipo_Senal"] or "Analógico",
            "entrada_salida": fila["Entrada_Salida_BD"] or "N/D",
            "rol": fila["Rol"], "migrado_de": fila["Migrado_De"],
        })
    return plan, duras, avisos


SQL_INSERT = """
INSERT INTO tags (tag_completo, area_id, variable_id, funcion_id, numero_loop, descripcion,
                  ubicacion, estado, creado_por, plc_origen, comentarios, datatype, alias_for,
                  fluido_proceso, tipo_senal, entrada_salida)
VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, '', ?, ?, ?)
"""

SQL_AUDITORIA = "INSERT INTO auditoria (tag_id, accion, detalle, usuario) VALUES (?, 'CREACION', ?, ?)"


def fila_insert(ficha: dict) -> tuple:
    return (ficha["tag"], ficha["area_id"], ficha["variable_id"], ficha["funcion_id"], ficha["numero"],
            ficha["descripcion"], ficha["estado"], USUARIO, ficha["plc_origen"], ficha["comentarios"],
            ficha["datatype"], ficha["fluido"], ficha["tipo_senal"], ficha["entrada_salida"])


def contar_tags(ruta: Path) -> int:
    with closing(abrir_solo_lectura(ruta)) as conexion:
        return conexion.execute("SELECT count(*) FROM tags").fetchone()[0]


def integrity(ruta: Path) -> str:
    with closing(abrir_solo_lectura(ruta)) as conexion:
        return conexion.execute("PRAGMA integrity_check").fetchone()[0]


def crear_backup(db: Path = DB_PRODUCCION, dir_backups: Path = DIR_BACKUPS) -> Path:
    """Backup consistente con la API de sqlite3 (no copia de archivo)."""
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino = Path(dir_backups) / ("tags_ingenio_antes_insert_9_tags_%s.db" % marca)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(db))) as origen, closing(sqlite3.connect(str(destino))) as copia:
        origen.backup(copia)
    return destino


def huella_contenido(ruta: Path) -> str:
    """Huella del CONTENIDO de la tabla tags (no del archivo): la API de backup no garantiza
    que el .db resultante sea byte-identico, asi que se compara contenido, no hash de archivo."""
    with closing(abrir_solo_lectura(ruta)) as conexion:
        filas = conexion.execute(
            "SELECT tag_completo, area_id, variable_id, funcion_id, numero_loop, estado "
            "FROM tags ORDER BY tag_completo"
        ).fetchall()
    return hashlib.sha256(repr(filas).encode("utf-8")).hexdigest()


def verificar_backup(backup: Path, db: Path, tags_esperados: int) -> list[str]:
    problemas = []
    if not backup.exists():
        return ["el backup no se creo: %s" % backup]
    total = contar_tags(backup)
    if total != tags_esperados:
        problemas.append("el backup tiene %d tags (se esperaban %d)" % (total, tags_esperados))
    estado_integridad = integrity(backup)
    if estado_integridad != "ok":
        problemas.append("integrity_check del backup = %s" % estado_integridad)
    if huella_contenido(backup) != huella_contenido(db):
        problemas.append("el contenido de la tabla tags del backup no coincide con la base original")
    return problemas


def imprimir_plan(plan: list[dict], duras: list[str], avisos: list[str], con_auditoria: bool, backup: Path,
                  db: Path, hash_db: str, tags_actuales: int) -> None:
    print("=" * 78)
    print("PLAN DE ALTA -- 9 tags aprobados (083 / 081 / 082)")
    print("=" * 78)
    print("Base destino .......: %s" % db)
    print("SHA-256 actual .....: %s" % hash_db)
    print("Tags en la base ....: %d  (esperado antes: %d / despues: %d)"
          % (tags_actuales, TAGS_ESPERADOS_ANTES, TAGS_ESPERADOS_DESPUES))
    print("Backup que se usaria: %s" % backup)
    print("Fila de auditoria ..: %s" % ("SI (detalle 'Migrado de <identidad PLC>')" if con_auditoria else "NO (--sin-auditoria)"))
    print()
    print("CAMPOS DE CADA ALTA (espejo de los 11 tags manuales):")
    for ficha in plan:
        print("-" * 78)
        print("  tag_completo    = %s" % ficha["tag"])
        print("  area_id/variable_id/funcion_id = %s / %s / %s" % (ficha["area_id"], ficha["variable_id"], ficha["funcion_id"]))
        print("  numero_loop     = %d" % ficha["numero"])
        print("  rol             = %s" % ficha["rol"])
        print("  descripcion     = %s" % ficha["descripcion"])
        print("  estado          = %s" % ficha["estado"])
        print("  creado_por      = %s" % USUARIO)
        print("  plc_origen      = %s" % ficha["plc_origen"])
        print("  comentarios     = %s" % ficha["comentarios"])
        print("  datatype        = %s | tipo_senal = %s | entrada_salida = %s"
              % (ficha["datatype"], ficha["tipo_senal"], ficha["entrada_salida"]))
        print("  fluido_proceso  = %s | ubicacion = '' | alias_for = ''" % ficha["fluido"])
        print("  INSERT (parametros exactos) = %r" % (fila_insert(ficha),))
    print()
    print("VALIDACIONES PREVIAS:")
    print("  colisiones duras  : %s" % ("NINGUNA" if not duras else ""))
    for problema in duras:
        print("     - %s" % problema)
    print("  avisos            : %s" % ("NINGUNO" if not avisos else ""))
    for aviso in avisos:
        print("     - %s" % aviso)
    print("=" * 78)


def aplicar(plan: list[dict], con_auditoria: bool, db: Path = DB_PRODUCCION, dir_backups: Path = DIR_BACKUPS) -> int:
    hash_antes = sha256(db)
    tags_antes = contar_tags(db)
    if tags_antes != TAGS_ESPERADOS_ANTES:
        print("[ABORTA] La base tiene %d tags y se esperaban %d." % (tags_antes, TAGS_ESPERADOS_ANTES))
        return 2
    backup = crear_backup(db, dir_backups)
    problemas = verificar_backup(backup, db, tags_antes)
    if problemas:
        print("[ABORTA] Backup no confiable: %s" % "; ".join(problemas))
        return 2
    print("[OK] Backup verificado: %s (%d tags, integrity ok, CONTENIDO de tags identico a la base original; "
          "el .db no es byte-identico porque la API de backup rearma el archivo pagina a pagina)"
          % (backup, tags_antes))

    conexion = sqlite3.connect(str(db), isolation_level=None)
    try:
        conexion.execute("BEGIN IMMEDIATE")
        for ficha in plan:
            cursor = conexion.execute(SQL_INSERT, fila_insert(ficha))
            if con_auditoria:
                conexion.execute(SQL_AUDITORIA, (cursor.lastrowid, "Migrado de %s" % ficha["migrado_de"], USUARIO_AUDITORIA))
        total = conexion.execute("SELECT count(*) FROM tags").fetchone()[0]
        if total != TAGS_ESPERADOS_DESPUES:
            raise RuntimeError("conteo dentro de la transaccion = %d (se esperaban %d)" % (total, TAGS_ESPERADOS_DESPUES))
        faltantes = [f["tag"] for f in plan if conexion.execute(
            "SELECT count(*) FROM tags WHERE tag_completo = ?", (f["tag"],)).fetchone()[0] != 1]
        if faltantes:
            raise RuntimeError("tags no insertados: %s" % faltantes)
        conexion.execute("COMMIT")
        print("[OK] Transaccion COMMIT: 9 tags insertados y verificados dentro de la transaccion.")
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

    hash_despues = sha256(db)
    estado_integridad = integrity(db)
    print("VERIFICACION POST-INSERCION:")
    print("  tags .............: %d -> %d" % (tags_antes, contar_tags(db)))
    print("  integrity_check ..: %s" % estado_integridad)
    print("  SHA-256 antes ....: %s" % hash_antes)
    print("  SHA-256 despues ..: %s" % hash_despues)
    print("  backup ...........: %s" % backup)
    return 0 if (contar_tags(db) == TAGS_ESPERADOS_DESPUES and estado_integridad == "ok") else 4


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Alta de los 9 tags aprobados. Dry-run por defecto.")
    parser.add_argument("--csv", default=str(CSV_PROPUESTA))
    parser.add_argument("--db", default=str(DB_PRODUCCION))
    parser.add_argument("--backup-dir", default=str(DIR_BACKUPS))
    parser.add_argument("--apply", action="store_true", help="Escribe de verdad (requiere autorizacion).")
    parser.add_argument("--sin-auditoria", action="store_true", help="No deja fila en la tabla auditoria.")
    args = parser.parse_args(argv)

    db = Path(args.db)
    filas = leer_propuesta(Path(args.csv))
    with closing(abrir_solo_lectura(db)) as conexion:
        catalogos = cargar_catalogos(conexion)
        plan, duras, avisos = planificar(filas, catalogos, conexion)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_previsto = Path(args.backup_dir) / ("tags_ingenio_antes_insert_9_tags_%s.db" % marca)
    imprimir_plan(plan, duras, avisos, not args.sin_auditoria, backup_previsto, db, sha256(db), contar_tags(db))

    if not args.apply:
        print("MODO DRY-RUN: no se escribio nada. La base de produccion no se abrio en modo escritura.")
        if duras:
            print("[OJO] Hay %d colisiones duras: con --apply la transaccion abortaria y haria ROLLBACK." % len(duras))
        return 0

    if duras:
        print("[ABORTA] No se ejecuta --apply con colisiones duras pendientes.")
        return 2
    print("MODO --apply AUTORIZADO: iniciando backup y transaccion...")
    return aplicar(plan, not args.sin_auditoria, db, Path(args.backup_dir))


if __name__ == "__main__":
    sys.exit(main())
