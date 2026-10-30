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
import json
import math
import random
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field, replace
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

PLCS: dict[str, str] = {
    "calderas": "192.168.10.195",   # Calderas_8_9_10_Desaireador (1756-L72)
    "cald11": "192.168.10.251",     # CALD_LA_FLORIDA (1756-L72)
}
NOMBRE_PLC = {"calderas": "Calderas 8-9-10", "cald11": "Caldera 11"}
IP_POR_DEFECTO = PLCS["calderas"]
INTERVALO_POR_DEFECTO = 30.0

# El programa de la caldera 11 arma la velocidad con un INT de 16 bits y lo divide
# por 100: cuando el valor supera 327,67 rpm el INT se interpreta con signo y el tag
# queda en negativo. La diferencia exacta es 65536 / 100.
DESFASE_INT16 = 655.36

ESTADO_PATH = DATOS_DIR / "senales_estado.json"


@dataclass(frozen=True)
class Senal:
    """Una señal a monitorear, de qué PLC sale y si está activa o archivada."""

    clave: str          # nombre corto para la tabla y el export
    tag: str            # tag real en el PLC (con ámbito cuando hace falta)
    descripcion: str
    grupo: str          # RPM | CORRIENTE | RTD
    unidad: str
    plc: str = "calderas"
    archivada: bool = False     # archivada: no se lee y no se guarda
    motivo: str = ""            # por qué está archivada / qué falta para activarla
    corregir_signo: bool = False  # el PLC la publica como INT con signo

    @property
    def nombre_plc(self) -> str:
        return NOMBRE_PLC.get(self.plc, self.plc)


SENALES: tuple[Senal, ...] = (
    # ---------------- Calderas 8 / 9 / 10 — 192.168.10.195 ----------------
    Senal("C9_ST_VTI", "Program:C9.C9_ST_VTI", "Velocidad VTI caldera 9", "RPM", "rpm"),
    Senal("C9_IT_VTI", "Program:C9.C9_IT_VTI", "Corriente VTI caldera 9", "CORRIENTE", "A"),
    Senal("C9_IT_VTF", "Program:C9.C9_IT_VTF", "Corriente VTF caldera 9", "CORRIENTE", "A"),
    Senal("C9_TT_ROD_VTI", "BP_ANALOGICA:7:I.Ch[1].Data",
          "Temperatura rodamiento VTI caldera 9", "RTD", "°C"),
    Senal("C9_ST_VTF", "Program:C9.C9_ST_VTF", "Velocidad VTF caldera 9", "RPM", "rpm",
          archivada=True, motivo="Bloque de escalado sin entrada cableada"),
    Senal("C9_TT_ROD_DEL_VTI", "Program:C9.C9_TT_ROD_DEL_VTI",
          "Rodamiento delantero VTI caldera 9 (canal 7:8)", "RTD", "°C",
          archivada=True, motivo="Canal RTD abierto: lee 870 °C, sin sensor"),
    Senal("C9_TT_ROD_TRA_VTI", "Program:C9.C9_TT_ROD_TRA_VTI",
          "Rodamiento trasero VTI caldera 9 (canal 7:9)", "RTD", "°C",
          archivada=True, motivo="Canal RTD abierto: lee 870 °C, sin sensor"),

    # ---------------- Caldera 11 — 192.168.10.251 ----------------
    Senal("CAL11_IDF1_RPM", "ME105_1_RPM", "Exaustor 1 IDF (tiro inducido) caldera 11",
          "RPM", "rpm", plc="cald11", corregir_signo=True),
    Senal("CAL11_IDF2_RPM", "ME105_2_RPM", "Exaustor 2 IDF (tiro inducido) caldera 11",
          "RPM", "rpm", plc="cald11", corregir_signo=True),
    Senal("CAL11_FDF_DER_RPM", "ME101_9D_RPM", "Ventilador primario FDF derecho caldera 11",
          "RPM", "rpm", plc="cald11", corregir_signo=True),
    Senal("CAL11_FDF_IZQ_RPM", "ME101_9E_RPM", "Ventilador primario FDF izquierdo caldera 11",
          "RPM", "rpm", plc="cald11", corregir_signo=True),
    Senal("CAL11_FDT_RPM", "ME101_10_RPM", "Ventilador secundario FDT caldera 11",
          "RPM", "rpm", plc="cald11", corregir_signo=True),
    Senal("CAL11_VTI_NORTE_PCT", "IT_PORCEN_CAL11_VTI_NORTE", "Corriente VTI Norte caldera 11",
          "CORRIENTE", "%", plc="cald11"),
    Senal("CAL11_VTI_SUR_PCT", "IT_PORCEN_CAL11_VTI_SUR", "Corriente VTI Sur caldera 11",
          "CORRIENTE", "%", plc="cald11"),

    # ---------------- Archivadas: caldera 8 ----------------
    Senal("C8_ST_VTF", "Program:C8.C8_ST_VTF", "Velocidad VTF caldera 8", "RPM", "rpm",
          archivada=True, motivo="Caldera 8 sin señal útil: equipo fuera de servicio"),
    Senal("C8_ST_VTI_NORTE", "Program:C8.C8_ST_VTI_NORTE", "Velocidad VTI Norte caldera 8",
          "RPM", "rpm", archivada=True, motivo="Caldera 8 sin señal útil: equipo fuera de servicio"),
    Senal("C8_ST_VTI_SUR", "Program:C8.C8_ST_VTI_SUR", "Velocidad VTI Sur caldera 8",
          "RPM", "rpm", archivada=True, motivo="Caldera 8 sin señal útil: equipo fuera de servicio"),
    Senal("C8_IT_VTI_NORTE", "Program:C8.C8_IT_VTI_NORTE", "Corriente VTI Norte caldera 8",
          "CORRIENTE", "A", archivada=True, motivo="Caldera 8 sin señal útil: equipo fuera de servicio"),
    Senal("C8_IT_VTI_SUR", "Program:C8.C8_IT_VTI_SUR", "Corriente VTI Sur caldera 8",
          "CORRIENTE", "A", archivada=True, motivo="Canal sin cablear y caldera fuera de servicio"),
    Senal("C8_IT_VTF", "Program:C8.C8_IT_VTF", "Corriente VTF caldera 8",
          "CORRIENTE", "A", archivada=True, motivo="Canal sin cablear y caldera fuera de servicio"),

    # ---------------- Archivadas: caldera 10 ----------------
    Senal("C10_ST_VTF", "Program:C10.C10_ST_VTF", "Velocidad VTF caldera 10", "RPM", "rpm",
          archivada=True, motivo="Caldera 10 sin señal útil: equipo fuera de servicio"),
    Senal("C10_ST_VTI_ESTE", "Program:C10.C10_ST_VTI_ESTE", "Velocidad VTI Este caldera 10",
          "RPM", "rpm", archivada=True, motivo="Caldera 10 sin señal útil: VTI saturado en 800 rpm"),
    Senal("C10_ST_VTI_OESTE", "Program:C10.C10_ST_VTI_OESTE", "Velocidad VTI Oeste caldera 10",
          "RPM", "rpm", archivada=True, motivo="Caldera 10 sin señal útil: VTI saturado en 800 rpm"),
    Senal("C10_IT_VTI_ESTE", "Program:C10.C10_IT_VTI_ESTE", "Corriente VTI Este caldera 10",
          "CORRIENTE", "A", archivada=True, motivo="Caldera 10 sin señal útil: equipo fuera de servicio"),
    Senal("C10_IT_VTI_OESTE", "Program:C10.C10_IT_VTI_OESTE", "Corriente VTI Oeste caldera 10",
          "CORRIENTE", "A", archivada=True, motivo="Caldera 10 sin señal útil: equipo fuera de servicio"),
    Senal("C10_IT_VTF", "Program:C10.C10_IT_VTF", "Corriente VTF caldera 10",
          "CORRIENTE", "A", archivada=True, motivo="Caldera 10 sin señal útil: equipo fuera de servicio"),
)


# ----------------------------------------------------------------------
# Estado de las señales (activa / archivada), persistido en datos/
# ----------------------------------------------------------------------
def _leer_estado() -> dict[str, bool]:
    try:
        datos = json.loads(ESTADO_PATH.read_text(encoding="utf-8"))
        return {str(k): bool(v) for k, v in datos.items()}
    except Exception:
        return {}


def fijar_archivada(clave: str, archivada: bool) -> None:
    """Guarda en disco si una señal queda archivada o se vuelve a leer."""
    estado = _leer_estado()
    estado[str(clave)] = bool(archivada)
    ESTADO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ESTADO_PATH.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def senales_con_estado() -> list[Senal]:
    estado = _leer_estado()
    return [replace(s, archivada=estado.get(s.clave, s.archivada)) for s in SENALES]


def senales_activas() -> list[Senal]:
    return [s for s in senales_con_estado() if not s.archivada]


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
    """Lee las señales de UN controlador por CIP. Solo lectura."""

    def __init__(self, plc: str = "calderas", ip: str | None = None, timeout: float = 6.0,
                 senales=None):
        self.plc = plc
        self.ip = ip or PLCS.get(plc, IP_POR_DEFECTO)
        self.timeout = timeout
        self.senales = tuple(senales if senales is not None else
                             [s for s in senales_activas() if s.plc == plc])
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

    def _valor(self, senal, crudo):
        valor = float(crudo)
        if senal.corregir_signo and valor < 0:
            valor += DESFASE_INT16
        return valor

    def leer(self):
        if self._plc is None:
            self.conectar()
        if not self.senales:
            return []
        res = self._plc.read(*[s.tag for s in self.senales])
        if not isinstance(res, list):
            res = [res]
        por_tag = {s.tag: s for s in self.senales}
        salida = []
        for r in res:
            senal = por_tag.get(r.tag) or next((s for s in self.senales if s.clave == r.tag), None)
            if senal is None:
                continue
            if r.error is None and isinstance(r.value, (int, float)) and not math.isnan(float(r.value)):
                salida.append({"clave": senal.clave, "tag": senal.tag, "descripcion": senal.descripcion,
                               "grupo": senal.grupo, "unidad": senal.unidad, "plc": senal.plc,
                               "valor": self._valor(senal, r.value), "calidad": "OK", "error": None})
            else:
                salida.append({"clave": senal.clave, "tag": senal.tag, "descripcion": senal.descripcion,
                               "grupo": senal.grupo, "unidad": senal.unidad, "plc": senal.plc,
                               "valor": None, "calidad": "ERROR", "error": str(r.error or "valor inválido")})
        return salida


class FuenteMultiple:
    """Una conexión por controlador; la caída de uno no afecta a los demás."""

    def __init__(self, ips: dict[str, str] | None = None, timeout: float = 6.0):
        self.ips = dict(PLCS)
        self.ips.update({k: v for k, v in (ips or {}).items() if v})
        self.senales = tuple(senales_activas())
        usados = {s.plc for s in self.senales}
        self.fuentes = {plc: FuentePLC(plc, self.ips.get(plc), timeout,
                                       senales=[s for s in self.senales if s.plc == plc])
                        for plc in sorted(usados)}

    @property
    def ip(self) -> str:
        return " / ".join(f"{v}" for v in self.ips.values())

    def leer(self):
        salida = []
        for plc, fuente in self.fuentes.items():
            try:
                salida.extend(fuente.leer())
            except Exception as exc:
                fuente.cerrar()
                salida.extend([{"clave": s.clave, "tag": s.tag, "descripcion": s.descripcion,
                                "grupo": s.grupo, "unidad": s.unidad, "plc": s.plc,
                                "valor": None, "calidad": "SIN_COMUNICACION",
                                "error": f"{type(exc).__name__}: {exc}"} for s in fuente.senales])
        return salida

    def cerrar(self):
        for fuente in self.fuentes.values():
            fuente.cerrar()


class FuenteSimulada:
    """Genera valores plausibles para probar sin PLC."""

    def __init__(self, semilla=7):
        self._rnd = random.Random(semilla)
        self.senales = tuple(senales_activas())
        self._base = {}
        for s in self.senales:
            if s.grupo == "RTD":
                self._base[s.clave] = 45.0
            elif s.unidad == "%":
                self._base[s.clave] = self._rnd.uniform(60, 95)
            elif s.grupo == "CORRIENTE":
                self._base[s.clave] = self._rnd.uniform(200, 600)
            else:
                self._base[s.clave] = self._rnd.uniform(300, 900)
        self.conectada = False

    @property
    def ip(self) -> str:
        return "simulado"

    def conectar(self):
        self.conectada = True

    def cerrar(self):
        self.conectada = False

    def leer(self):
        salida = []
        for s in self.senales:
            v = self._base[s.clave] + self._rnd.uniform(-3, 3)
            self._base[s.clave] = max(0.0, v)
            salida.append({"clave": s.clave, "tag": s.tag, "descripcion": s.descripcion,
                           "grupo": s.grupo, "unidad": s.unidad, "plc": s.plc,
                           "valor": round(v, 2), "calidad": "OK", "error": None})
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
                             "grupo": s.grupo, "unidad": s.unidad, "plc": s.plc, "valor": None,
                             "calidad": "SIN_COMUNICACION", "error": f"{type(exc).__name__}: {exc}"}
                            for s in getattr(fuente, "senales", ())]
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
    for s in senales_activas():
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
    p.add_argument("--ip", default=PLCS["calderas"], help="IP del PLC de calderas 8/9/10")
    p.add_argument("--ip11", default=PLCS["cald11"], help="IP del PLC de la caldera 11")
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

    fuente = FuenteSimulada() if args.simulado else \
        FuenteMultiple({"calderas": args.ip, "cald11": args.ip11})

    def aviso(n, lecturas):
        ok = sum(1 for l in lecturas if l["calidad"] == "OK")
        muestra = "  ".join(f"{l['clave']}={l['valor']}" for l in lecturas[:3])
        print(f"[{_ahora()}] barrido {n}: {ok}/{len(lecturas)} OK  {muestra}", flush=True)

    destino = "SIMULADO" if args.simulado else f"{args.ip} + {args.ip11}"
    print(f"Monitoreando {destino} cada {args.intervalo:g} s "
          f"({len(fuente.senales)} señales activas de {len(SENALES)}). Ctrl+C para salir.")
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
