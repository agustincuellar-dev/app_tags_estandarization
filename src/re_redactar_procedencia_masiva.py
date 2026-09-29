"""Re-redacción de procedencia de los 99 tags masivos ya insertados.

Por defecto es DRY-RUN. Con --apply, y solo entonces:
1) copia byte-identica de la base + backup por API;
2) BEGIN IMMEDIATE; UPDATE SOLO de tags.descripcion para los 99 tags del CSV;
3) una auditoria ACTUALIZACION por tag con detalle exacto 'Re-redaccion de procedencia';
4) COMMIT o ROLLBACK total;
5) actualiza Descripcion_Propuesta del CSV canonico y preserva su version previa.

No modifica otra columna, otro tag, catalogos ni el backup historico de 693 tags.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from corregir_propuesta_masiva import describir  # noqa: E402

CSV = RAIZ / "exports" / "propuesta_numeracion_masiva_180926.csv"
DB = RAIZ / "app_etiquetas" / "tags_ingenio.db"
BACKUPS = RAIZ / "app_etiquetas" / "backups"
CSV_PREVIA = RAIZ / "exports" / "propuesta_numeracion_masiva_180926_v3_pre_redaccion.csv"
USUARIO = "agustin (via Hermes)"
DETALLE_AUDITORIA = "Re-redaccion de procedencia"
CAMPOS_REQUERIDOS = {"Tag_Propuesto", "Rol", "Variable_ISA", "Area", "Instancia_AOI", "Migrado_De",
                     "Routine", "Funcion_ISA", "Descripcion_Propuesta"}


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def abrir_ro(ruta: Path) -> sqlite3.Connection:
    c = sqlite3.connect(ruta.resolve().as_uri() + "?mode=ro", uri=True)
    c.execute("PRAGMA query_only=ON")
    return c


def leer_csv(ruta: Path) -> tuple[list[dict], list[str]]:
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f, delimiter=";")
        filas = list(lector)
        campos = lector.fieldnames or []
    faltan = CAMPOS_REQUERIDOS - set(campos)
    if faltan:
        raise SystemExit("CSV sin columnas requeridas: %s" % sorted(faltan))
    if len(filas) != 99 or len({f["Tag_Propuesto"] for f in filas}) != 99:
        raise SystemExit("El CSV debe contener exactamente 99 tags unicos")
    return filas, campos


def descripciones_nuevas(filas: list[dict], db: Path) -> dict[str, str]:
    with closing(abrir_ro(db)) as c:
        variables = {letra: nombre for letra, nombre in c.execute("SELECT letra,nombre FROM variables")}
    return {f["Tag_Propuesto"]: describir(f["Rol"], f["Variable_ISA"], f["Area"], f["Instancia_AOI"],
                                             f["Migrado_De"], f["Routine"], f["Funcion_ISA"], variables)
            for f in filas}


def validar_plan(filas: list[dict], nuevas: dict[str, str], db: Path) -> list[str]:
    problemas = []
    if sum("Migrado de:" in d for d in nuevas.values()) != 99:
        problemas.append("no hay 99 descripciones con 'Migrado de:'")
    if sum("sin tag de campo en el PLC: la salida escribe directo al canal" in d for d in nuevas.values()) != 12:
        problemas.append("no hay exactamente 12 aclaraciones CANAL_CRUDO")
    with closing(abrir_ro(db)) as c:
        existentes = {r[0] for r in c.execute("SELECT tag_completo FROM tags")}
        faltan = sorted(set(nuevas) - existentes)
        if faltan:
            problemas.append("faltan en produccion: %s" % faltan)
    return problemas


def crear_backups(db: Path, backups: Path) -> tuple[Path, Path]:
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups.mkdir(parents=True, exist_ok=True)
    byte = backups / ("tags_ingenio_antes_re_redaccion_%s_byte_identico.db" % marca)
    api = backups / ("tags_ingenio_antes_re_redaccion_%s_api.db" % marca)
    shutil.copy2(db, byte)
    with closing(sqlite3.connect(str(db))) as origen, closing(sqlite3.connect(str(api))) as destino:
        origen.backup(destino)
    return byte, api


def escribir_csv_atomico(ruta: Path, filas: list[dict], campos: list[str]) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", delete=False, dir=str(ruta.parent)) as f:
        temporal = Path(f.name)
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";", lineterminator="\n")
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c, "") for c in campos})
    os.replace(temporal, ruta)


def aplicar(filas: list[dict], campos: list[str], nuevas: dict[str, str], db: Path, backups: Path,
            csv: Path, csv_previa: Path) -> int:
    hash_antes = sha256(db)
    total_antes = contar(db)
    byte, api = crear_backups(db, backups)
    if sha256(byte) != hash_antes or integrity(byte) != "ok" or integrity(api) != "ok":
        print("[ABORTA] Backup no verificable; no se abre transaccion.")
        return 2
    conexion = sqlite3.connect(str(db), isolation_level=None)
    try:
        conexion.execute("BEGIN IMMEDIATE")
        for tag in sorted(nuevas):
            cursor = conexion.execute("UPDATE tags SET descripcion=? WHERE tag_completo=?", (nuevas[tag], tag))
            if cursor.rowcount != 1:
                raise RuntimeError("%s: UPDATE no afecto exactamente una fila" % tag)
            tag_id = conexion.execute("SELECT id FROM tags WHERE tag_completo=?", (tag,)).fetchone()[0]
            conexion.execute("INSERT INTO auditoria (tag_id,accion,detalle,usuario) VALUES (?, 'ACTUALIZACION', ?, ?)",
                             (tag_id, DETALLE_AUDITORIA, USUARIO))
        afectados = conexion.execute("SELECT count(*) FROM tags WHERE tag_completo IN (%s)" % ",".join("?" * len(nuevas)),
                                     sorted(nuevas)).fetchone()[0]
        if afectados != 99:
            raise RuntimeError("solo %d de 99 tags quedaron alcanzables" % afectados)
        conexion.execute("COMMIT")
    except Exception as error:
        conexion.execute("ROLLBACK")
        print("[ABORTA] ROLLBACK ejecutado; base sin cambios. Motivo: %s" % error)
        return 3
    finally:
        conexion.close()

    # El CSV se actualiza solo despues del COMMIT; se preserva la v3 previa antes de reemplazarlo.
    if not csv_previa.exists():
        shutil.copy2(csv, csv_previa)
    filas_actualizadas = [dict(f, Descripcion_Propuesta=nuevas[f["Tag_Propuesto"]]) for f in filas]
    escribir_csv_atomico(csv, filas_actualizadas, campos)
    print("[OK] COMMIT: 99 UPDATE de descripcion y 99 auditorias.")
    print("POST: tags=%d integrity=%s sha_antes=%s sha_despues=%s" %
          (contar(db), integrity(db), hash_antes, sha256(db)))
    print("backups: %s | %s" % (byte, api))
    return 0


def contar(db: Path) -> int:
    with closing(abrir_ro(db)) as c:
        return c.execute("SELECT count(*) FROM tags").fetchone()[0]


def integrity(db: Path) -> str:
    with closing(abrir_ro(db)) as c:
        return c.execute("PRAGMA integrity_check").fetchone()[0]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Re-redacta procedencia de los 99 tags masivos. Dry-run por defecto.")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--csv", default=str(CSV))
    p.add_argument("--db", default=str(DB))
    p.add_argument("--backup-dir", default=str(BACKUPS))
    p.add_argument("--csv-previa", default=str(CSV_PREVIA))
    args = p.parse_args(argv)
    csv_ruta, db, backups, csv_previa = Path(args.csv), Path(args.db), Path(args.backup_dir), Path(args.csv_previa)
    filas, campos = leer_csv(csv_ruta)
    nuevas = descripciones_nuevas(filas, db)
    problemas = validar_plan(filas, nuevas, db)
    print("PLAN: 99 tags | Migrado de: %d | CANAL_CRUDO aclarado: %d | cambios de texto: %d" %
          (sum("Migrado de:" in d for d in nuevas.values()),
           sum("sin tag de campo en el PLC: la salida escribe directo al canal" in d for d in nuevas.values()),
           sum(nuevas[f["Tag_Propuesto"]] != f["Descripcion_Propuesta"] for f in filas)))
    print("colisiones/problemas:", "NINGUNO" if not problemas else " | ".join(problemas))
    if not args.apply:
        print("MODO DRY-RUN: no se escribio nada.")
        return 0 if not problemas else 2
    if problemas:
        print("[ABORTA] No se aplica con problemas pendientes.")
        return 2
    return aplicar(filas, campos, nuevas, db, backups, csv_ruta, csv_previa)


if __name__ == "__main__":
    sys.exit(main())
