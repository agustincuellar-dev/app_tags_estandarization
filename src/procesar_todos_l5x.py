"""
procesar_todos_l5x.py
=====================
Orquestador MASIVO de respaldos .L5X (una carpeta con ~30 archivos, que en
realidad son ~9-12 PLCs reales + sus backups + AOIs + stubs).

Estrategia (confirmada con el Ingenio): procesar UNA sola version canonica
por PLC, para tener trazabilidad individual y un reporte global real (sin
contar el mismo PLC varias veces por sus backups).

Reglas de seleccion canonica:
  - Se descartan los AOIs (nombre contiene 'AOI'): son Add-On Instructions,
    no controladores.
  - Se descartan los stubs (< 50 KB): exports vacios/fallidos.
  - Se descarta cualquier archivo cuyo TargetType (leido del propio XML,
    atributo del tag <RSLogix5000Content>) no sea "Controller": cubre AOIs
    sin 'AOI' en el nombre, exports de un solo Rung suelto, de un DataType,
    etc. Ej: librerias genericas de Rockwell como
    'raC_Opr_NetModbusTCPClient_Rung.L5X' (TargetType="Rung"), que no son
    PLCs del Ingenio y no deben pisar el conteo global.
  - Los archivos se agrupan por "proyecto" (nombre sin el sufijo de backup
    '.DESKTOP-<host>.PC-<tool>.BAK<nnn>'). Por cada proyecto se elige:
        1) la copia de trabajo (.L5X sin .BAK), si existe;
        2) si solo hay backups, el de numero .BAK mas alto (mas reciente);
        3) a igualdad, el de mayor tamano.

Cada PLC canonico se analiza con el motor completo de auditar_l5x.py
(clasificacion ISA + UDT + cableado FBD + voto por vecindad de rutinas +
palabras clave). Genera, en auto_agustin/resultados/:
    <PROYECTO>_mapeo_exitoso.csv
    <PROYECTO>_sin_clasificar.csv

Al final imprime el Reporte Estadistico Global.

Uso:
    python procesar_todos_l5x.py
"""

import os
import re
import csv

import auditar_l5x as base

# Este script vive en <PROYECTO>/src/. Los respaldos .L5X y sus resultados
# viven en <PROYECTO>/auto_agustin/, es decir un nivel POR ENCIMA de src/.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DIR_L5X = os.path.join(PROJECT_ROOT, "auto_agustin")
DIR_OUT = os.path.join(DIR_L5X, "resultados")

CAMPOS = ["tag_viejo", "clase", "funcion_ISA", "area_detectada", "cod_area",
          "datatype", "alias_for", "tag_nuevo_propuesto", "descripcion", "validacion"]

UMBRAL_STUB_BYTES = 50 * 1024
_RE_TARGET_TYPE = re.compile(r'TargetType="([^"]*)"')


def target_type(ruta_completa):
    """Lee el atributo TargetType del encabezado XML sin parsear todo el
    archivo (los L5X pueden pesar varios MB). None si no se pudo leer."""
    try:
        with open(ruta_completa, "r", encoding="utf-8-sig", errors="replace") as f:
            head = f.read(2000)
        m = _RE_TARGET_TYPE.search(head)
        return m.group(1) if m else None
    except OSError:
        return None


def es_pendiente(fila):
    """Mismo criterio de limpieza que auditar_l5x.main()."""
    return "PENDIENTE" in fila["tag_nuevo_propuesto"] or "???" in fila["tag_nuevo_propuesto"]


# ------------------------------------------------------------------
# Seleccion de la version canonica por PLC
# ------------------------------------------------------------------
_RE_BACKUP = re.compile(r"\.BAK(\d+)\.L5X$", re.IGNORECASE)
_RE_SUFIJO_BACKUP = re.compile(r"(\.DESKTOP-.*?\.BAK\d+)?\.L5X$", re.IGNORECASE)


def nombre_proyecto(fname):
    """Nombre del PLC sin el sufijo de backup/export."""
    return _RE_SUFIJO_BACKUP.sub("", fname)


def es_backup(fname):
    return _RE_BACKUP.search(fname) is not None


def num_backup(fname):
    m = _RE_BACKUP.search(fname)
    return int(m.group(1)) if m else -1


def seleccionar_canonicos(directorio):
    """Devuelve (canonicos: {proyecto: filename}, excluidos: [(filename, motivo)])."""
    archivos = [f for f in os.listdir(directorio) if f.lower().endswith(".l5x")]
    excluidos = []
    grupos = {}
    for f in sorted(archivos):
        full = os.path.join(directorio, f)
        size = os.path.getsize(full)
        if "AOI" in f.upper():
            excluidos.append((f, "AOI (no es un PLC)"))
            continue
        if size < UMBRAL_STUB_BYTES:
            excluidos.append((f, f"stub/vacio ({size // 1024} KB)"))
            continue
        tt = target_type(full)
        if tt is not None and tt != "Controller":
            excluidos.append((f, f"TargetType={tt} (no es un PLC completo)"))
            continue
        grupos.setdefault(nombre_proyecto(f), []).append((f, size))

    canonicos = {}
    for proyecto, lst in grupos.items():
        # Orden: copia de trabajo antes que backup; mayor BAK antes que menor;
        # mayor tamano antes que menor.
        elegido = sorted(lst, key=lambda it: (
            0 if not es_backup(it[0]) else 1,
            -num_backup(it[0]),
            -it[1],
        ))[0][0]
        canonicos[proyecto] = elegido
        for f, _ in lst:
            if f != elegido:
                excluidos.append((f, f"backup/duplicado de '{proyecto}' (canonico: {elegido})"))

    return canonicos, excluidos


# ------------------------------------------------------------------
def procesar_uno(proyecto, filename, usar_aprendizaje=True):
    """Analiza un PLC y escribe sus dos CSV. Devuelve un dict de metricas.

    usar_aprendizaje: si es True (default), conecta con la Aprendizaje por
    Excepcion de la Tags App -- antes de dar un tag por SIN_CLASIFICAR,
    se consulta reglas_aprendidas (tags_ingenio.db); si tampoco hay nada
    ahi, el tag se archiva solo en la bandeja de pendientes
    (tags_no_clasificados) para revision humana futura. Pasar False
    corre el motor 100% standalone, igual que antes de esta integracion
    (por ejemplo, para no ensuciar la base con una corrida de prueba)."""
    ruta = os.path.join(DIR_L5X, filename)
    # Area por defecto del controlador (solo para PLCs mono-area; None si no aplica)
    area_def = base.area_defecto_para(filename)

    conn_aprendizaje = None
    if usar_aprendizaje:
        import aprendizaje_motor
        conn_aprendizaje = aprendizaje_motor.abrir_conexion()
    try:
        filas, _resumen = base.procesar(
            ruta, area_defecto=area_def, plc_nombre=proyecto,
            conn_aprendizaje=conn_aprendizaje,
        )
    finally:
        if conn_aprendizaje is not None:
            conn_aprendizaje.close()

    # Higiene de sistema (R1 bloques Logix/diagnostico + R2 canales libres)
    # + EQUIPOS_LOGICA (arranque/logica de motores, bolsa propia para
    # Mantenimiento Mecanico, correccion de Ingenieria 27/08/2026): NO son
    # tags de proceso, por lo que se excluyen del denominador de la
    # metrica de exito ISA para que el porcentaje siga siendo transparente.
    CLASES_FUERA_DE_PROCESO = ("INTERNA_SISTEMA", "RESERVADO", "EQUIPOS_LOGICA")
    higiene = [f for f in filas if f["clase"] in CLASES_FUERA_DE_PROCESO]
    proceso = [f for f in filas if f["clase"] not in CLASES_FUERA_DE_PROCESO]

    limpias = [f for f in filas if not es_pendiente(f)]
    pendientes = [f for f in filas if es_pendiente(f)]

    # Exito ISA: solo dentro del universo de proceso/instrumentos.
    exitos_proc = [f for f in proceso if not es_pendiente(f)]
    pend_proc = [f for f in proceso if es_pendiente(f)]

    for sufijo, datos in (("mapeo_exitoso", limpias), ("sin_clasificar", pendientes)):
        salida = os.path.join(DIR_OUT, f"{proyecto}_{sufijo}.csv")
        with open(salida, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=CAMPOS, delimiter=";")
            w.writeheader()
            w.writerows(datos)

    total = len(filas)
    n_proc = len(proceso)
    return {
        "proyecto": proyecto, "archivo": filename, "area_defecto": area_def,
        "total": total, "exitos": len(limpias), "pendientes": len(pendientes),
        "higiene": len(higiene), "proceso": n_proc,
        "exitos_isa": len(exitos_proc), "pend_isa": len(pend_proc),
        "efectividad": (100 * len(exitos_proc) / n_proc) if n_proc else 0.0,
    }


def main():
    if not os.path.isdir(DIR_L5X):
        print(f"No existe el directorio: {DIR_L5X}")
        return
    os.makedirs(DIR_OUT, exist_ok=True)

    canonicos, excluidos = seleccionar_canonicos(DIR_L5X)

    print("=" * 66)
    print("  ORQUESTADOR MASIVO L5X - Ingenio La Florida")
    print("=" * 66)
    print(f"Directorio: {DIR_L5X}")
    print(f"PLCs canonicos a procesar: {len(canonicos)}")
    print(f"Archivos excluidos (backups/AOIs/stubs): {len(excluidos)}")
    print("-" * 66)

    metricas = []
    for proyecto in sorted(canonicos):
        filename = canonicos[proyecto]
        try:
            m = procesar_uno(proyecto, filename)
            metricas.append(m)
            marca = f"  [def:{m['area_defecto']}]" if m["area_defecto"] else ""
            print(f"  [OK] {proyecto:30} tot {m['total']:5} | hig {m['higiene']:4} | "
                  f"proc {m['proceso']:5} -> exito {m['exitos_isa']:5} "
                  f"pend {m['pend_isa']:5}  ({m['efectividad']:5.1f}%){marca}")
        except Exception as e:
            print(f"  [ERROR] {proyecto:30} {filename}: {e}")

    # ---- Reporte Estadistico Global ----
    total_tags = sum(m["total"] for m in metricas)
    total_hig = sum(m["higiene"] for m in metricas)
    total_proc = sum(m["proceso"] for m in metricas)
    total_exitos_isa = sum(m["exitos_isa"] for m in metricas)
    total_pend_isa = sum(m["pend_isa"] for m in metricas)
    efectividad = (100 * total_exitos_isa / total_proc) if total_proc else 0.0
    pct_hig = (100 * total_hig / total_tags) if total_tags else 0.0

    print("=" * 66)
    print("  REPORTE ESTADISTICO GLOBAL")
    print("=" * 66)
    print(f"  PLCs procesados                   : {len(metricas)}")
    print(f"  Sumatoria total de tags           : {total_tags}")
    print("-" * 66)
    print("  [A] HIGIENE DE SISTEMA (no son tags de proceso)")
    print(f"      Bloques Logix + canales libres: {total_hig}  ({pct_hig:.1f}% del total)")
    print("-" * 66)
    print("  [B] UNIVERSO ISA / PROCESO (denominador de la efectividad)")
    print(f"      Tags de proceso e instrumentos: {total_proc}")
    print(f"      Exito ISA (mapeados)          : {total_exitos_isa}")
    print(f"      Pendientes (revision de campo): {total_pend_isa}")
    print("-" * 66)
    print(f"  >> EFECTIVIDAD ISA GLOBAL         : {efectividad:.2f}%   "
          f"({total_exitos_isa}/{total_proc})")
    print("=" * 66)
    print(f"  Resultados en: {DIR_OUT}")
    print(f"  ({len(metricas) * 2} archivos CSV generados)")

    if excluidos:
        print("\n  --- Archivos excluidos (no procesados) ---")
        for f, motivo in sorted(excluidos):
            print(f"    - {f}: {motivo}")


if __name__ == "__main__":
    main()
