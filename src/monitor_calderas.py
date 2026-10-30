"""Monitor de RPM, corrientes y RTD de los ventiladores de tiro (VTI/VTF) — Calderas.

Lee por EtherNet/IP (CIP) las señales de los programas C8, C9 y C10 del
controlador de Calderas, guarda cada barrido en SQLite y permite exportar
a CSV y XLSX.

Uso por consola:
    python monitor_calderas.py --ip 192.168.10.195 --intervalo 30
    python monitor_calderas.py --simulado --ciclos 3 --intervalo 2   (sin PLC)
    python monitor_calderas.py --exportar                  (exporta lo guardado)

El barrido es de SOLO LECTURA: nunca escribe en el PLC.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import random
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _raiz_datos() -> Path:
    """Con el programa empaquetado como .exe, los datos viven junto al ejecutable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return BASE_DIR.parent


DATOS_DIR = _raiz_datos() / "datos"
DB_PATH = DATOS_DIR / "monitor_calderas.db"
EXPORT_DIR = DATOS_DIR / "exportaciones"

IP_POR_DEFECTO = "192.168.10.195"   # Calderas_8_9_10_Desaireador (1756-L72)
INTERVALO_POR_DEFECTO = 30.0


@dataclass(frozen=True)
class Senal:
    """Una señal a monitorear y cómo mostrarla."""

    clave: str          # nombre corto para la tabla y el export
    tag: str            # tag real en el PLC (con ámbito de programa)
    descripcion: str
    grupo: str          # RPM | CORRIENTE | RTD
    unidad: str
    sin_cablear: bool = False   # bloque de escalado sin entrada en el FBD


SENALES: tuple[Senal, ...] = (
    # --- velocidad de los ventiladores (RPM) ---
    Senal("C8_ST_VTF", "Program:C8.C8_ST_VTF", "Velocidad VTF caldera 8", "RPM", "rpm"),
    Senal("C8_ST_VTI_NORTE", "Program:C8.C8_ST_VTI_NORTE", "Velocidad VTI Norte caldera 8", "RPM", "rpm"),
    Senal("C8_ST_VTI_SUR", "Program:C8.C8_ST_VTI_SUR", "Velocidad VTI Sur caldera 8", "RPM", "rpm"),
    Senal("C9_ST_VTI", "Program:C9.C9_ST_VTI", "Velocidad VTI caldera 9", "RPM", "rpm"),
    Senal("C9_ST_VTF", "Program:C9.C9_ST_VTF", "Velocidad VTF caldera 9", "RPM", "rpm",
          sin_cablear=True),
    Senal("C10_ST_VTF", "Program:C10.C10_ST_VTF", "Velocidad VTF caldera 10", "RPM", "rpm"),
    Senal("C10_ST_VTI_ESTE", "Program:C10.C10_ST_VTI_ESTE", "Velocidad VTI Este caldera 10", "RPM", "rpm"),
    Senal("C10_ST_VTI_OESTE", "Program:C10.C10_ST_VTI_OESTE", "Velocidad VTI Oeste caldera 10", "RPM", "rpm"),
    # --- corriente de los motores (A) ---
    Senal("C8_IT_VTI_NORTE", "Program:C8.C8_IT_VTI_NORTE", "Corriente VTI Norte caldera 8", "CORRIENTE", "A"),
    Senal("C8_IT_VTI_SUR", "Program:C8.C8_IT_VTI_SUR", "Corriente VTI Sur caldera 8", "CORRIENTE", "A",
          sin_cablear=True),
    Senal("C8_IT_VTF", "Program:C8.C8_IT_VTF", "Corriente VTF caldera 8", "CORRIENTE", "A",
          sin_cablear=True),
    Senal("C9_IT_VTI", "Program:C9.C9_IT_VTI", "Corriente VTI caldera 9", "CORRIENTE", "A"),
    Senal("C9_IT_VTF", "Program:C9.C9_IT_VTF", "Corriente VTF caldera 9", "CORRIENTE", "A"),
    Senal("C10_IT_VTI_ESTE", "Program:C10.C10_IT_VTI_ESTE", "Corriente VTI Este caldera 10", "CORRIENTE", "A"),
    Senal("C10_IT_VTI_OESTE", "Program:C10.C10_IT_VTI_OESTE", "Corriente VTI Oeste caldera 10", "CORRIENTE", "A"),
    Senal("C10_IT_VTF", "Program:C10.C10_IT_VTF", "Corriente VTF caldera 10", "CORRIENTE", "A"),
    # --- RTD de rodamientos del VTI (solo delantero y trasero) ---
    Senal("C9_TT_ROD_DEL_VTI", "Program:C9.C9_TT_ROD_DEL_VTI", "Rodamiento delantero VTI caldera 9", "RTD", "°C"),
    Senal("C9_TT_ROD_TRA_VTI", "Program:C9.C9_TT_ROD_TRA_VTI", "Rodamiento trasero VTI caldera 9", "RTD", "°C"),
)

POR_TAG = {s.tag: s for s in SENALES}


# ----------------------------------------------------------------------
# Almacenamiento
# ----------------------------------------------------------------------
ESQUEMA = """
CREATE TABLE IF NOT EXISTS lecturas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    clave       TEXT    NOT NULL,
    tag         TEXT    NOT NULL,
    descripcion TEXT,
    grupo       TEXT,
    valor       REAL,
    unidad      TEXT,
    calidad     TEXT    NOT NULL,
    error       TEXT,
    corrida_id  INTEGER
);
CREATE INDEX IF NOT EXISTS ix_lecturas_ts ON lecturas(ts);
CREATE INDEX IF NOT EXISTS ix_lecturas_clave ON lecturas(clave, ts);

CREATE TABLE IF NOT EXISTS corridas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio      TEXT NOT NULL,
    fin         TEXT,
    ip          TEXT,
    intervalo_s REAL,
    origen      TEXT
);
"""


class Almacen:
    """Persistencia en SQLite: una fila por señal y por barrido."""

    def __init__(self, ruta=None):
        self.ruta = Path(ruta) if ruta else DB_PATH
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._con() as con:
            con.executescript(ESQUEMA)
            columnas = [r[1] for r in con.execute("PRAGMA table_info(lecturas)")]
            if "corrida_id" not in columnas:      # bases creadas antes del agregado
                con.execute("ALTER TABLE lecturas ADD COLUMN corrida_id INTEGER")

    def _con(self):
        con = sqlite3.connect(self.ruta, timeout=15)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def abrir_corrida(self, ip, intervalo, origen):
        with self._lock, self._con() as con:
            # Cierra corridas que quedaron abiertas por un corte de luz o un apagado:
            # el fin real es el último barrido que alcanzó a guardar.
            con.execute(
                "UPDATE corridas SET fin = coalesce("
                "(SELECT MAX(ts) FROM lecturas WHERE corrida_id = corridas.id),"
                "(SELECT MAX(ts) FROM lecturas WHERE corrida_id IS NULL), fin) "
                "WHERE fin IS NULL")
            cur = con.execute(
                "INSERT INTO corridas (inicio, ip, intervalo_s, origen) VALUES (?,?,?,?)",
                (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ip, intervalo, origen),
            )
            return cur.lastrowid

    def cerrar_corrida(self, corrida_id):
        with self._lock, self._con() as con:
            con.execute("UPDATE corridas SET fin=? WHERE id=?",
                        (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), corrida_id))

    def guardar_barrido(self, ts, lecturas, corrida_id=None):
        """lecturas: lista de dicts con clave/tag/descripcion/grupo/valor/unidad/calidad/error."""
        filas = [
            (ts, l["clave"], l["tag"], l.get("descripcion"), l.get("grupo"),
             l.get("valor"), l.get("unidad"), l.get("calidad", "OK"), l.get("error"), corrida_id)
            for l in lecturas
        ]
        with self._lock, self._con() as con:
            con.executemany(
                "INSERT INTO lecturas (ts, clave, tag, descripcion, grupo, valor, unidad, calidad, error, corrida_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", filas)

    def resumen(self):
        with self._con() as con:
            return con.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts), COUNT(DISTINCT ts) FROM lecturas").fetchone()


# ----------------------------------------------------------------------
# Fuentes de datos
# ----------------------------------------------------------------------
class FuentePLC:
    """Lee los tags del controlador por CIP. Solo lectura."""

    def __init__(self, ip, timeout=6.0):
        self.ip = ip
        self.timeout = timeout
        self._plc = None

    def conectar(self):
        from pycomm3 import LogixDriver

        self.cerrar()
        self._plc = LogixDriver(self.ip, init_tags=True, timeout=self.timeout)
        self._plc.open()

    def cerrar(self):
        if self._plc is not None:
            try:
                self._plc.close()
            except Exception:
                pass
            self._plc = None

    def leer(self):
        if self._plc is None:
            self.conectar()
        res = self._plc.read(*[s.tag for s in SENALES])
        if not isinstance(res, list):
            res = [res]
        salida = []
        for r in res:
            senal = POR_TAG.get(r.tag) or next((s for s in SENALES if s.clave == r.tag), None)
            if senal is None:
                continue
            if r.error is None and isinstance(r.value, (int, float)) and not math.isnan(float(r.value)):
                salida.append({"clave": senal.clave, "tag": senal.tag, "descripcion": senal.descripcion,
                               "grupo": senal.grupo, "unidad": senal.unidad,
                               "valor": float(r.value),
                               "calidad": "SIN_CABLEAR" if senal.sin_cablear else "OK",
                               "error": None})
            else:
                salida.append({"clave": senal.clave, "tag": senal.tag, "descripcion": senal.descripcion,
                               "grupo": senal.grupo, "unidad": senal.unidad,
                               "valor": None, "calidad": "ERROR", "error": str(r.error or "valor inválido")})
        return salida


class FuenteSimulada:
    """Genera valores plausibles para probar sin PLC."""

    def __init__(self, semilla=7):
        self._rnd = random.Random(semilla)
        self._base = {s.clave: (0.0 if s.grupo == "RTD" else self._rnd.uniform(300, 900))
                      for s in SENALES}
        self.conectada = False

    def conectar(self):
        self.conectada = True

    def cerrar(self):
        self.conectada = False

    def leer(self):
        salida = []
        for s in SENALES:
            v = self._base[s.clave] + self._rnd.uniform(-3, 3)
            if s.grupo == "RTD":
                v = 55 + self._rnd.uniform(-4, 4)
            self._base[s.clave] = max(0.0, v)
            salida.append({"clave": s.clave, "tag": s.tag, "descripcion": s.descripcion,
                           "grupo": s.grupo, "unidad": s.unidad,
                           "valor": round(v, 2),
                           "calidad": "SIN_CABLEAR" if s.sin_cablear else "OK", "error": None})
        return salida


# ----------------------------------------------------------------------
# Barrido
# ----------------------------------------------------------------------
def _ahora():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def bucle_monitoreo(fuente, almacen, intervalo=INTERVALO_POR_DEFECTO, ciclos=None,
                    parar: threading.Event | None = None, al_terminar_barrido=None,
                    dormir=time.sleep):
    """Barre cada `intervalo` segundos. `ciclos=None` = hasta que se pida parar."""
    parar = parar or threading.Event()
    corrida = almacen.abrir_corrida(getattr(fuente, "ip", "simulado"), intervalo,
                                    "simulado" if isinstance(fuente, FuenteSimulada) else "plc")
    n = 0
    try:
        while not parar.is_set():
            inicio = time.time()
            try:
                lecturas = fuente.leer()
            except Exception as exc:                      # caída de comunicación
                fuente.cerrar()
                lecturas = [{"clave": s.clave, "tag": s.tag, "descripcion": s.descripcion,
                             "grupo": s.grupo, "unidad": s.unidad, "valor": None,
                             "calidad": "SIN_COMUNICACION", "error": f"{type(exc).__name__}: {exc}"}
                            for s in SENALES]
            almacen.guardar_barrido(_ahora(), lecturas, corrida)
            n += 1
            if al_terminar_barrido:
                al_terminar_barrido(n, lecturas)
            if ciclos is not None and n >= ciclos:
                break
            restante = intervalo - (time.time() - inicio)
            if parar.wait(max(0.0, restante)):
                break
    finally:
        almacen.cerrar_corrida(corrida)
        fuente.cerrar()
    return n


# ----------------------------------------------------------------------
# Exportación
# ----------------------------------------------------------------------
COLUMNAS = ("ts", "clave", "tag", "descripcion", "grupo", "valor", "unidad", "calidad", "error")


def _filas_para_exportar(almacen, desde=None, hasta=None):
    sql = f"SELECT {', '.join(COLUMNAS)} FROM lecturas"
    cond, params = [], []
    if desde:
        cond.append("ts >= ?")
        params.append(desde)
    if hasta:
        cond.append("ts <= ?")
        params.append(hasta)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY ts, grupo, clave"
    with almacen._con() as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, params)]


def exportar_csv(almacen, destino=None, desde=None, hasta=None):
    destino = Path(destino) if destino else EXPORT_DIR / f"calderas_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
    destino.parent.mkdir(parents=True, exist_ok=True)
    filas = _filas_para_exportar(almacen, desde, hasta)
    with destino.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    return destino, len(filas)


def exportar_xlsx(almacen, destino=None, desde=None, hasta=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    destino = Path(destino) if destino else EXPORT_DIR / f"calderas_{dt.datetime.now():%Y%m%d_%H%M%S}.xlsx"
    destino.parent.mkdir(parents=True, exist_ok=True)
    filas = _filas_para_exportar(almacen, desde, hasta)

    wb = Workbook()
    hoja = wb.active
    hoja.title = "Lecturas"
    encabezados = ("Fecha y hora", "Señal", "Tag PLC", "Descripción", "Grupo", "Valor", "Unidad", "Calidad", "Error")
    hoja.append(encabezados)
    for f in filas:
        hoja.append([f["ts"], f["clave"], f["tag"], f["descripcion"], f["grupo"],
                     f["valor"], f["unidad"], f["calidad"], f["error"]])
    estilo_h = Font(bold=True, color="FFFFFF")
    fondo_h = PatternFill("solid", fgColor="002157")
    for c in hoja[1]:
        c.font = estilo_h
        c.fill = fondo_h
        c.alignment = Alignment(horizontal="center")
    hoja.freeze_panes = "A2"
    hoja.auto_filter.ref = hoja.dimensions
    for i, ancho in enumerate((19, 20, 34, 34, 12, 10, 8, 16, 30), start=1):
        hoja.column_dimensions[get_column_letter(i)].width = ancho

    # hoja de resumen por señal
    resumen = wb.create_sheet("Resumen")
    resumen.append(("Señal", "Descripción", "Unidad", "Lecturas", "Mínimo", "Máximo", "Promedio", "Última"))
    for s in SENALES:
        vals = [f["valor"] for f in filas if f["clave"] == s.clave and f["valor"] is not None]
        ultima = next((f["ts"] for f in reversed(filas) if f["clave"] == s.clave and f["valor"] is not None), "")
        resumen.append((s.clave, s.descripcion, s.unidad, len(vals),
                        min(vals) if vals else None, max(vals) if vals else None,
                        round(sum(vals) / len(vals), 2) if vals else None, ultima))
    for c in resumen[1]:
        c.font = estilo_h
        c.fill = fondo_h
    resumen.freeze_panes = "A2"
    for i, ancho in enumerate((22, 36, 8, 10, 10, 10, 12, 19), start=1):
        resumen.column_dimensions[get_column_letter(i)].width = ancho

    wb.save(destino)
    return destino, len(filas)


# ----------------------------------------------------------------------
# Consola
# ----------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description="Monitor de VTI/VTF de Calderas (solo lectura)")
    p.add_argument("--ip", default=IP_POR_DEFECTO)
    p.add_argument("--intervalo", type=float, default=INTERVALO_POR_DEFECTO)
    p.add_argument("--ciclos", type=int, default=None, help="cantidad de barridos y salir")
    p.add_argument("--db", default=None)
    p.add_argument("--simulado", action="store_true")
    p.add_argument("--exportar", action="store_true", help="exporta lo guardado y sale")
    p.add_argument("--desde"), p.add_argument("--hasta")
    args = p.parse_args(argv)

    almacen = Almacen(args.db)
    if args.exportar:
        csv_path, n = exportar_csv(almacen, desde=args.desde, hasta=args.hasta)
        xlsx_path, _ = exportar_xlsx(almacen, desde=args.desde, hasta=args.hasta)
        print(f"{n} filas exportadas\n  {csv_path}\n  {xlsx_path}")
        return 0

    fuente = FuenteSimulada() if args.simulado else FuentePLC(args.ip)

    def aviso(n, lecturas):
        ok = sum(1 for l in lecturas if l["calidad"] == "OK")
        muestra = "  ".join(f"{l['clave']}={l['valor']}" for l in lecturas[:3])
        print(f"[{_ahora()}] barrido {n}: {ok}/{len(lecturas)} OK  {muestra}", flush=True)

    print(f"Monitoreando {'SIMULADO' if args.simulado else args.ip} cada {args.intervalo:g} s "
          f"({len(SENALES)} señales). Ctrl+C para salir.")
    try:
        n = bucle_monitoreo(fuente, almacen, args.intervalo, args.ciclos, al_terminar_barrido=aviso)
    except KeyboardInterrupt:
        n = -1
    total, primero, ultimo, barridos = almacen.resumen()
    print(f"\nbarridos: {n if n >= 0 else 'interrumpido'} | filas en base: {total} | "
          f"desde {primero} hasta {ultimo} | {barridos} instantes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
