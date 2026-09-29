"""Genera la propuesta delta v5 desde v4 y decisiones aprobadas D1-D4.

Solo lee CSV/L5X y SQLite mediante mode=ro a traves de generar_propuesta_masiva.cargar_universos().
No escribe SQLite ni modifica la propuesta v4/canónica.
"""
from __future__ import annotations

import csv
import hashlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
EXPORTS = RAIZ / "exports"
sys.path.insert(0, str(RAIZ / "src"))
import generar_propuesta_masiva as gpm  # noqa: E402

V4 = EXPORTS / "propuesta_numeracion_masiva_v4_210926.csv"
V4_ANALISIS = EXPORTS / "analisis_210_lazos_v4.csv"
DECISIONES = EXPORTS / "decisiones_pendientes_v4.csv"
V5 = EXPORTS / "propuesta_numeracion_masiva_v5_210926.csv"
DIFF = EXPORTS / "diff_propuesta_masiva_v4_v5.csv"
RESUMEN = EXPORTS / "resumen_propuesta_masiva_v5_210926.csv"
FUERA = EXPORTS / "decisiones_fuera_v5_210926.csv"
FUNCIONES = EXPORTS / "funciones_v4_v5_210926.csv"

VALVULA = re.compile(r"(PCV|FCV|LCV|TCV|XV|VLV|VALV|VTI|PV_VALV|CV_)", re.I)
MOTOR = re.compile(r"(PowerFlex|VDF_|IS_BBA|SI_BB|Slot_IS_MOTOR|IS_MOTOR|DOSIFICADOR|MOTOR_|FEEDER|ALIMENTADOR)", re.I)
MORFEMAS = {"PT": "P", "PIT": "P", "PDT": "P", "LT": "L", "LIT": "L", "TT": "T", "TIT": "T",
            "FT": "F", "FIT": "F", "AT": "A", "AIT": "A", "WT": "W", "WIT": "W"}


def leer(path: Path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def escribir(path: Path, rows: list[dict], cols: list[str]):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def clave(row):
    return (row["PLC"], row["Program"], row["Routine"], row["Instancia_AOI"])


def morfema(operando: str, fallback: str = "P"):
    for x in re.split(r"[_\W]+", operando or ""):
        if x.upper() in MORFEMAS:
            return MORFEMAS[x.upper()]
    return fallback


def funcion_salida(analisis: dict, decision: dict) -> tuple[str, str]:
    """D4: Y para no-válvulas; V/XV solo cuando XML identifica salida de válvula."""
    evidence = " ".join((analisis.get("Salida_Fisica", ""), analisis.get("Camino_XML", ""),
                          decision.get("Motivo_Regla", ""), decision.get("Observacion", "")))
    if MOTOR.search(evidence) and not VALVULA.search(evidence):
        return "Y", "D4: elemento final no-válvula (VFD/motor/feeder)"
    pin = analisis.get("Pin_Salida", "")
    if "MV_VALV" in pin.upper() or VALVULA.search(evidence):
        return ("XV" if "MV_VALV" in pin.upper() else "V"), "D4: elemento final identificado como válvula"
    # No se inventa que un canal analógico sea una válvula. Para C9, VTI en el camino interno es
    # evidencia nominal de válvula de tiro inducido; otros canales analógicos quedan fuera.
    return "", "D4: salida física sin identidad de válvula ni no-válvula suficiente"


def descripcion(tag, rol, instancia, rutina, area, funcion, migrado, area_nombre=""):
    nombres = {
        "T": "Transmisor", "IC": "Controlador indicador", "V": "Válvula de control",
        "XV": "Válvula todo/nada", "Y": "Relé/Computadora",
    }
    lectura = nombres.get(funcion, "Instrumento")
    if rol == "CONTROLADOR": lectura = "Controlador indicador"
    texto = f"{lectura} — lazo {instancia}; Migrado de: {migrado}; rutina {rutina}; área {area}"
    if area_nombre:
        texto += f" ({area_nombre})"
    return texto


def main() -> int:
    v4 = leer(V4)
    v4_original = [dict(f) for f in v4]
    v3 = leer(EXPORTS / "propuesta_numeracion_masiva_180926.csv")
    analisis = { (f["PLC"], f["Program"], f["Routine"], f["Instancia"]): f for f in leer(V4_ANALISIS) }
    decisiones = leer(DECISIONES)
    cols = list(v4[0])
    rows = [dict(f) for f in v4]
    existing_lazos = {f["Lazo"] for f in rows}
    existing_tags = {f["Tag_Propuesto"] for f in rows}

    u = gpm.cargar_universos()
    used = defaultdict(set)
    # Los 33 lazos de v3 son la línea base congelada. Los dos agregados por v4 no pueden compartir
    # numero/tag entre sí: v4 los dejó en 300_041 y 700_017 respectivamente. Se corrige solo esa
    # colisión interna en v5, sin tocar ningún lazo de v3.
    v3_lazos = {f["Lazo"] for f in v3}
    duplicados = defaultdict(list)
    for f in rows:
        duplicados[f["Tag_Propuesto"]].append(f)
    lazos_a_reasignar = sorted({f["Lazo"] for fs in duplicados.values() if len(fs) > 1 for f in fs
                                if f["Lazo"] not in v3_lazos})
    for lazo in lazos_a_reasignar:
        area = next(f["Area"] for f in rows if f["Lazo"] == lazo)
        n = 1
        while n <= 999 and (n in {int(f["Numero_Propuesto"]) for f in rows if f["Area"] == area}
                            or gpm.numero_ocupado(area, n, u)):
            n += 1
        if n > 999:
            raise RuntimeError("sin numero libre para reparar colision v4: %s" % lazo)
        for f in rows:
            if f["Lazo"] != lazo:
                continue
            old = f["Numero_Propuesto"]
            f["Numero_Propuesto"] = f"{n:03d}"
            f["Tag_Propuesto"] = f["Tag_Propuesto"].rsplit("_", 1)[0] + f"_{n:03d}"
            f["Nota_Convencion"] = (f.get("Nota_Convencion", "") +
                                     f" D4/v5: reparación de colisión interna v4 {old} -> {n:03d}.").strip()
    used = defaultdict(set)
    for f in rows:
        used[f["Area"]].add(int(f["Numero_Propuesto"]))

    def next_free(area):
        n = 1
        while n <= 999:
            if n not in used[area] and not gpm.numero_ocupado(area, n, u):
                used[area].add(n)
                return f"{n:03d}"
            n += 1
        raise RuntimeError(f"no hay numero libre en area {area}")

    fuera = []
    accepted = []
    for d in decisiones:
        if d["Regla"] == "(sin regla aplicable)":
            d = dict(d); d["Motivo_Fuera"] = "sin R-A/R-B/R-C aplicable"
            fuera.append(d); continue
        if not d["Area"]:
            d = dict(d); d["Motivo_Fuera"] = "D3: área no determinable; requiere documentación o MAPEO_AREA_OVERRIDE"
            fuera.append(d); continue
        key = (d["PLC"], d["Program"], d["Routine"], d["Instancia"])
        a = analisis.get(key, {})
        out_func, func_reason = funcion_salida(a, d)
        if not out_func:
            d = dict(d); d["Motivo_Fuera"] = func_reason
            fuera.append(d); continue
        # Los 6 casos sin area y el caso sin regla son las brechas explícitas; los demás tienen
        # entrada/salida física o R-B/R-C/R-A evidence recorded in decisiones_pendientes_v4.csv.
        accepted.append((d, a, out_func, func_reason))

    # Sensor propio: un tag por sensor físico compartido, una sola vez. No se finge controlador ni
    # actuador; se marca Rol=ENTRADA y Lazo=SENSOR_COMPARTIDO para que el delta inserter lo trate
    # como una alta independiente.
    sensors = {}
    for d, a, out_func, reason in accepted:
        if "R-B" not in d["Regla"]:
            continue
        entry = a.get("Entrada_Fisica", "").split(" | ")[0].strip()
        if not entry or entry in sensors:
            continue
        area = d["Area"]
        var = morfema(a.get("Entrada_Operando", ""), "P")
        num = next_free(area)
        tag = f"{area}_{var}T_{num}"
        if tag in existing_tags:
            continue
        sensors[entry] = (d, a, area, var, num, tag)

    # Actualiza los números nuevos para los lazos D1; v4 queda congelada por construcción.
    nuevos = []
    for d, a, out_func, func_reason in accepted:
        lazo = d["Lazo"]
        if lazo in existing_lazos:
            continue
        area, var = d["Area"], d["Variable_ISA"] or morfema(a.get("Entrada_Operando", ""))
        num = next_free(area)
        notes = []
        if "R-B" in d["Regla"]: notes.append(d["Observacion"].split(" | ")[0])
        if "R-C" in d["Regla"]: notes.append("Elementos finales en paralelo")
        nota = " | ".join(notes)
        common = {
            "Lazo": lazo, "PLC": d["PLC"], "Program": d["Program"], "Routine": d["Routine"],
            "Instancia_AOI": d["Instancia"], "Tipo_AOI": a.get("Tipo_AOI", ""),
            "Prioridad_Frontera": a.get("Prioridad", "4"), "Area": area, "Variable_ISA": var,
            "Numero_Propuesto": num, "Fluido_Proceso": "No determinado en la identidad del lazo",
            "Tipo_Senal": "Analógico", "Entrada_Operando": a.get("Entrada_Operando", ""),
            "Area_Criterio": d.get("Criterio_Area", ""), "Area_Confianza": d.get("Area_Confianza", ""),
            "Variable_Criterio": d.get("Criterio_Variable", ""),
            "Numeros_Ocupados_Area_Resumen": "5 universos verificados; línea base v4 + delta asignado",
            "Numero_Libre_En": "U1_DB_produccion | U2_backup_693 | U3_inventario_online | U4_identificadores_L5X | U5_documentacion",
            "Clasificacion_Trazado": "CERRABLE_HOY_D1", "Nota_Trazado": nota,
            "Camino_XML": a.get("Entrada_Camino", "") + " -> " + a.get("Salida_Fisica", ""),
            "Estado_Propuesta": "PROPUESTA_CONCRETA_PARA_REVISION — NO_INSERTAR", "Escritura_SQLite": "NO",
            "Nota_Convencion": "D1 R-A/R-B/R-C aplicada; " + reason,
        }
        for rol, func, tagvar, migrated, io in [
            ("ENTRADA", "T", var + "T", a.get("Entrada_Operando", ""), "Entrada"),
            ("CONTROLADOR", "IC", var + "IC", d["Instancia"], "Memoria / Red"),
            ("SALIDA", out_func, var + out_func, a.get("Salida_Fisica", ""), "Salida"),
        ]:
            f = dict(common)
            f.update({"Rol": rol, "Funcion_ISA": func, "Tag_Propuesto": f"{area}_{tagvar}_{num}",
                      "Migrado_De": migrated, "Nota_Migrado_De": nota,
                      "AliasFor_Direccion_Fisica": a.get("Salida_Fisica", "") if rol == "SALIDA" else "",
                      "Pin_Salida": a.get("Pin_Salida", "") if rol == "SALIDA" else "",
                      "Descripcion_Propuesta": descripcion(f"{area}_{tagvar}_{num}", rol, d["Instancia"], d["Routine"], area, func, migrated),
                      "Entrada_Salida_BD": io, "DataType_BD": "REAL"})
            nuevos.append(f)

    # Agrega sensores propios como filas independientes, sin inventar un controlador/actuador.
    for entry, (d, a, area, var, num, tag) in sensors.items():
        f = {"Lazo": f"{d['Lazo']}/SENSOR_COMPARTIDO", "PLC": d["PLC"], "Program": d["Program"],
             "Routine": d["Routine"], "Instancia_AOI": "SENSOR_COMPARTIDO", "Tipo_AOI": "SENSOR_COMPARTIDO",
             "Prioridad_Frontera": a.get("Prioridad", "4"), "Rol": "ENTRADA", "Area": area,
             "Variable_ISA": var, "Funcion_ISA": "T", "Numero_Propuesto": num, "Tag_Propuesto": tag,
             "Migrado_De": a.get("Entrada_Operando", entry), "Nota_Migrado_De": "R-B: sensor físico propio; no se inventan controlador ni actuador",
             "AliasFor_Direccion_Fisica": entry, "Pin_Salida": "", "Descripcion_Propuesta": descripcion(tag, "ENTRADA", "SENSOR_COMPARTIDO", d["Routine"], area, "T", a.get("Entrada_Operando", entry)),
             "Fluido_Proceso": "No determinado en la identidad del lazo", "Tipo_Senal": "Analógico", "Entrada_Salida_BD": "Entrada", "DataType_BD": "REAL",
             "Nota_Convencion": "D1 R-B: lazo propio del sensor compartido", "Entrada_Operando": a.get("Entrada_Operando", ""),
             "Area_Criterio": d.get("Criterio_Area", ""), "Area_Confianza": d.get("Area_Confianza", ""), "Variable_Criterio": d.get("Criterio_Variable", ""),
             "Numeros_Ocupados_Area_Resumen": "5 universos verificados; delta asignado", "Numero_Libre_En": "U1|U2|U3|U4|U5",
             "Clasificacion_Trazado": "R-B_SENSOR_COMPARTIDO", "Nota_Trazado": f"PV compartido con {a.get('Entrada_Operando', entry)}",
             "Camino_XML": a.get("Entrada_Camino", ""), "Estado_Propuesta": "PROPUESTA_CONCRETA_PARA_REVISION — NO_INSERTAR", "Escritura_SQLite": "NO"}
        nuevos.append(f)

    all_rows = rows + nuevos
    all_rows.sort(key=lambda f: (f["Area"], int(f["Numero_Propuesto"]), {"ENTRADA": 0, "CONTROLADOR": 1, "SALIDA": 2}.get(f["Rol"], 0), f["Tag_Propuesto"]))
    escribir(V5, all_rows, cols)

    # Diff v4 -> v5: solo filas nuevas y no altera v4.
    diff_cols = ["Cambio", "Lazo", "Rol", "Tag_Propuesto", "Numero_Propuesto", "Funcion_ISA", "Regla", "Nota"]
    diff = []
    v5_index = {(f["Lazo"], f["Rol"]): f for f in rows}
    for old in v4_original:
        new = v5_index.get((old["Lazo"], old["Rol"]))
        if new and (old["Tag_Propuesto"], old["Numero_Propuesto"], old["Funcion_ISA"]) != \
                (new["Tag_Propuesto"], new["Numero_Propuesto"], new["Funcion_ISA"]):
            diff.append({"Cambio": "MODIFICADO", "Lazo": new["Lazo"], "Rol": new["Rol"],
                         "Tag_Propuesto": new["Tag_Propuesto"], "Numero_Propuesto": new["Numero_Propuesto"],
                         "Funcion_ISA": new["Funcion_ISA"], "Regla": "D4/v5",
                         "Nota": "v4: %s/%s/%s -> v5: %s/%s/%s" %
                                 (old["Tag_Propuesto"], old["Numero_Propuesto"], old["Funcion_ISA"],
                                  new["Tag_Propuesto"], new["Numero_Propuesto"], new["Funcion_ISA"])})
    for f in nuevos:
        d = next((x for x in decisiones if x["Lazo"] in f["Lazo"]), {})
        diff.append({"Cambio": "AGREGADO", "Lazo": f["Lazo"], "Rol": f["Rol"], "Tag_Propuesto": f["Tag_Propuesto"], "Numero_Propuesto": f["Numero_Propuesto"], "Funcion_ISA": f["Funcion_ISA"], "Regla": d.get("Regla", "R-B_SENSOR"), "Nota": f["Nota_Trazado"]})
    escribir(DIFF, diff, diff_cols)
    escribir(FUERA, fuera, list(fuera[0]) if fuera else ["Lazo", "Motivo_Fuera"])

    summary = [{"Metrica": "Lazos v4", "Valor": len({f["Lazo"] for f in v4})},
               {"Metrica": "Tags v4", "Valor": len(v4)},
               {"Metrica": "Lazos D1 agregados", "Valor": len({f["Lazo"] for f in nuevos if "SENSOR_COMPARTIDO" not in f["Lazo"]})},
               {"Metrica": "Tags D1 agregados", "Valor": len(nuevos)},
               {"Metrica": "Decisiones fuera v5", "Valor": len(fuera)},
               {"Metrica": "Lazos v5", "Valor": len({f["Lazo"] for f in all_rows})},
               {"Metrica": "Tags v5", "Valor": len(all_rows)}]
    escribir(RESUMEN, summary, ["Metrica", "Valor"])

    report = []
    for lazo in ["Calderas_8_9_10_Desaireador/C9/B_C9_PC_HOGAR", "FABRICA/FAB_CCV/B_PC_VG1_TACHOS"]:
        oldfs = [f for f in v4_original if f["Lazo"] == lazo]
        newfs = [f for f in rows if f["Lazo"] == lazo]
        oldout = next(f for f in oldfs if f["Rol"] == "SALIDA")
        newout = next(f for f in newfs if f["Rol"] == "SALIDA")
        report.append({"Lazo": lazo, "Tag_Salida_v4": oldout["Tag_Propuesto"], "Numero_v4": oldout["Numero_Propuesto"],
                       "Tag_Salida_v5": newout["Tag_Propuesto"], "Numero_v5": newout["Numero_Propuesto"],
                       "Funcion": newout["Funcion_ISA"],
                       "Ocupacion_5_universos": "verificado: libre en U1/U2/U3/U4/U5 para v5",
                       "Motivo": "v4 congelado inicialmente; v5 corrige colisión interna entre lazos v4" if oldout["Numero_Propuesto"] != newout["Numero_Propuesto"] else "v4 conservado; salida identificada como válvula"})
    escribir(FUNCIONES, report, ["Lazo", "Tag_Salida_v4", "Numero_v4", "Tag_Salida_v5", "Numero_v5", "Funcion", "Ocupacion_5_universos", "Motivo"])
    print(f"v5: {len({f['Lazo'] for f in all_rows})} lazos / {len(all_rows)} tags; D1 completos: {len(accepted)}; sensores propios: {len(sensors)}; fuera: {len(fuera)}")
    print(f"[OK] {V5}\n[OK] {DIFF}\n[OK] {RESUMEN}\n[OK] {FUERA}\n[OK] {FUNCIONES}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
