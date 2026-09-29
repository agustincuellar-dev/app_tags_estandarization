"""Sprint de frontera v4 - FASE 3: clasificacion de bloqueos por reglas de gobernanza.

QUE HACE
--------
Toma los bloqueos del sprint v4 (`exports/bloqueos_propuesta_masiva_v4_210926.csv`) y los
clasifica segun las tres reglas que fijo el usuario, SIN aplicar nada:

  R-A  elemento final = arrancador de bomba/motor (no valvula) -> funcion "Y" (Rele/Computadora).
       Evidencia: el lazo cae en REVISION_ELEMENTO_FINAL o su salida alcanza un modulo de tipo
       variador/arrancador (PowerFlex, VDF_*, IS_BBA_*, SI_BB_*, Slot_IS_MOTOR_*).
  R-B  sensor fisico compartido por N controladores -> un lazo propio del sensor + un lazo por
       cada par controlador+elemento final, con la observacion "PV compartido con <tag>".
       Evidencia: la misma direccion fisica de entrada aparece en N lazos del analisis.
  R-C  salida repartida en 2+ direcciones del mismo tipo (bombas Norte/Sur, valvulas en paralelo)
       -> UN solo lazo con todas las direcciones en Migrado_De separadas por " | ".
       Evidencia: la salida del lazo alcanza N direcciones fisicas.

SALIDA
------
`exports/decisiones_pendientes_v4.csv`: una fila por lazo bloqueado con la regla aplicada, el
motivo, la evidencia XML, el numero TENTATIVO (siguiente libre del area, verificado contra los
universos y contra la linea base congelada) y los tags que se insertarian si el usuario autoriza.

NO escribe en SQLite ni aplica ninguna decision.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

import generar_propuesta_masiva as gpm  # noqa: E402

EXPORTS = RAIZ / "exports"
ANALISIS = EXPORTS / "analisis_210_lazos_v4.csv"
BLOQUEOS = EXPORTS / "bloqueos_propuesta_masiva_v4_210926.csv"
REVISION = EXPORTS / "revision_elemento_final_v4_210926.csv"
PROPUESTA = EXPORTS / "propuesta_numeracion_masiva_v4_210926.csv"
SALIDA = EXPORTS / "decisiones_pendientes_v4.csv"
RESUMEN = EXPORTS / "resumen_sprint_v4.csv"

# Causas que este sprint ataco, tal como las declara exports/resumen_frontera_por_causa.csv
# (el techo de FASE 1 son los 10 lazos de AOI_ENVOLTORIO; el de FASE 2, los 11+1 de escalera).
CAUSAS_ATACADAS = ("AOI_ENVOLTORIO", "INSTRUCCION_LADDER_NO_SOPORTADA", "TAG_INTERMEDIO_SIN_ESCRITOR")

COLUMNAS = ["Lazo", "PLC", "Program", "Routine", "Instancia", "Area", "Area_Confianza",
            "Variable_ISA", "Criterio_Area", "Criterio_Variable",
            "Clasificacion_Bloqueo", "Motivo_Bloqueo", "Regla", "Motivo_Regla", "Evidencia_XML",
            "Numero_Tentativo", "Tags_Que_Se_Insertarian", "Observacion",
            "Requiere_Autorizacion", "Escritura_SQLite"]

# Señales de elemento final motriz en este proyecto (nombres reales de los L5X).
MOTOR = re.compile(r"(IS_BBA|SI_BB|Slot_IS_MOTOR|IS_MOTOR|VDF_|PowerFlex|ARRANQUE_MOTOR|"
                   r"DOSIFICADOR|_VFD|MOTOR_)", re.I)
VALVULA = re.compile(r"(VALV|PCV|FCV|LCV|TCV|XV_|VLV|PV_VALV)", re.I)


def leer(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def direcciones(campo: str) -> list[str]:
    return [d.strip() for d in (campo or "").split(" | ") if d.strip()]


def es_motor(*textos) -> bool:
    """True si el texto describe un arrancador/variador y NO una valvula."""
    junto = " ".join(t for t in textos if t)
    return bool(MOTOR.search(junto)) and not VALVULA.search(junto)


# Morfema ISA de la variable a partir del nombre del tag de campo (PT -> P, LT -> L, ...).
MORFEMAS = {"PT": "P", "PIT": "P", "PDT": "P", "PI": "P", "LT": "L", "LIT": "L", "LG": "L",
            "TT": "T", "TIT": "T", "TE": "T", "TI": "T", "FT": "F", "FIT": "F", "FE": "F",
            "FI": "F", "AT": "A", "AI": "A", "AIT": "A", "WT": "W", "WIT": "W", "JT": "J"}


def variable_del_sensor(operando: str) -> str:
    """Variable ISA que corresponde al tag de campo del sensor compartido ('' si no se deduce)."""
    for token in re.split(r"[_\W]+", operando or ""):
        if token.upper() in MORFEMAS:
            return MORFEMAS[token.upper()]
    return ""


def clave_de(lazo: str) -> tuple:
    partes = (lazo.split("/") + ["", "", ""])[:3]
    return tuple(partes)


def escribir_resumen(filas_decisiones: list[dict]) -> Path:
    """Tabla resumen del sprint: que se destrabo, que sigue bloqueado y por que causa.

    Los conteos de la propuesta y de los bloqueos son comparables v3 vs v4 porque salen del mismo
    pase de correccion; los del trazador son los del analisis v4 (el canonico quedo intacto).
    """
    from collections import Counter

    def contar(ruta, campo):
        return Counter(f[campo] for f in leer(ruta))

    v3_prop, v4_prop = leer(EXPORTS / "propuesta_numeracion_masiva_180926.csv"), leer(PROPUESTA)
    bl_v3 = contar(EXPORTS / "bloqueos_propuesta_masiva_180926.csv", "Clasificacion")
    bl_v4 = contar(BLOQUEOS, "Clasificacion")
    an_base, an_v4 = leer(EXPORTS / "analisis_210_lazos.csv"), leer(ANALISIS)
    crudo = EXPORTS / "analisis_210_lazos_v4_trazador.csv"
    traz = Counter(f["Clasificacion"] for f in (leer(crudo) if crudo.exists() else an_v4))
    formas_v4 = Counter(f["Motivo"].split(":")[0].strip() for f in leer(BLOQUEOS))
    reglas = Counter(f["Regla"] for f in filas_decisiones)

    filas = [
        ("LAZOS en la propuesta (post-filtro)", len({f["Lazo"] for f in v3_prop}),
         len({f["Lazo"] for f in v4_prop})),
        ("TAGS propuestos (post-filtro)", len(v3_prop), len(v4_prop)),
        ("lazos CERRABLE_HOY en el analisis (post-filtro)",
         sum(1 for f in an_base if f["Clasificacion"] == "CERRABLE_HOY"),
         sum(1 for f in an_v4 if f["Clasificacion"] == "CERRABLE_HOY")),
        ("lazos CERRABLE_HOY del trazador CRUDO (base no disponible)", "", traz["CERRABLE_HOY"]),
        ("BLOQUEADO_ANALIZADOR", bl_v3["BLOQUEADO_ANALIZADOR"], bl_v4["BLOQUEADO_ANALIZADOR"]),
        ("BLOQUEADO_DOCUMENTAL", bl_v3["BLOQUEADO_DOCUMENTAL"], bl_v4["BLOQUEADO_DOCUMENTAL"]),
        ("BLOQUEADO_EXTREMO_COMPARTIDO", bl_v3["BLOQUEADO_EXTREMO_COMPARTIDO"],
         bl_v4["BLOQUEADO_EXTREMO_COMPARTIDO"]),
        ("BLOQUEADO_VARIABLE_AMBIGUA", bl_v3["BLOQUEADO_VARIABLE_AMBIGUA"],
         bl_v4["BLOQUEADO_VARIABLE_AMBIGUA"]),
        ("BLOQUEADO_AREA_AMBIGUA", bl_v3["BLOQUEADO_AREA_AMBIGUA"], bl_v4["BLOQUEADO_AREA_AMBIGUA"]),
        ("REVISION_ELEMENTO_FINAL", bl_v3["REVISION_ELEMENTO_FINAL"], bl_v4["REVISION_ELEMENTO_FINAL"]),
    ]
    with open(RESUMEN, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["Metrica", "v3", "v4", "Delta"])
        for nombre, a, b in filas:
            delta = (b - a) if isinstance(a, int) and isinstance(b, int) else ""
            w.writerow([nombre, a, b, delta])
        w.writerow([])
        w.writerow(["Decisiones pendientes por regla", "", "", ""])
        for regla, n in sorted(reglas.items(), key=lambda x: (-x[1], x[0])):
            w.writerow(["  %s" % regla, n, "", ""])
        w.writerow([])
        w.writerow(["Bloqueos v4 por forma del motivo (top 15)", "cantidad", "", ""])
        ordenadas = sorted(formas_v4.items(), key=lambda x: (-x[1], x[0]))
        for forma, n in ordenadas[:15]:
            w.writerow(["  %s" % (forma[:90] or "(sin motivo)"), n, "", ""])
        if len(ordenadas) > 15:
            w.writerow(["  (+%d motivos individuales mas, %d bloqueos)"
                        % (len(ordenadas) - 15, sum(n for _, n in ordenadas[15:])), "", "", ""])
        w.writerow([])
        w.writerow(["Causas de frontera atacadas por el sprint (resumen_frontera_por_causa.csv)",
                    "controladores", "", ""])
        causas_front = {r["Motivo_Bloqueo"]: r["Controladores_Afectados"]
                        for r in leer(EXPORTS / "resumen_frontera_v4_por_causa.csv")}
        for causa in CAUSAS_ATACADAS:
            w.writerow(["  %s" % causa, causas_front.get(causa, ""), "", ""])
    return RESUMEN


def main() -> int:
    analisis = leer(ANALISIS)
    bloqueos = leer(BLOQUEOS)
    revision = leer(REVISION)
    propuesta = leer(PROPUESTA)
    indice = {(f["PLC"], f["Program"], f["Routine"], f["Instancia"]): f for f in analisis}

    # --- evidencia global: que direccion fisica de ENTRADA comparten los lazos (R-B) ---
    comparten: dict[str, list[tuple]] = defaultdict(list)
    for f in analisis:
        for direccion in direcciones(f.get("Entrada_Fisica", "")):
            clave = (f["PLC"], f["Program"], f["Routine"], f["Instancia"])
            if clave not in comparten[direccion]:
                comparten[direccion].append(clave)

    # --- numeros ya comprometidos: los del v4 + la linea base congelada ---
    u = gpm.cargar_universos()
    congelada = {}
    ruta_congelada = EXPORTS / "numeracion_congelada_180926.csv"
    if ruta_congelada.exists():
        with open(ruta_congelada, encoding="utf-8-sig", newline="") as f:
            congelada = {(r["PLC"], r["Program"], r["Routine"], r["Instancia"]): int(r["Numero"])
                         for r in csv.DictReader(f, delimiter=";")}
    usados = defaultdict(set)
    for f in propuesta:
        if f["Area"] and f["Numero_Propuesto"]:
            usados[f["Area"]].add(int(f["Numero_Propuesto"]))

    def siguiente_libre(area: str) -> str:
        libres = [n for n in gpm.numeros_libres(area, u, 60) if n not in usados[area]]
        if not libres:
            return ""
        numero = libres[0]
        usados[area].add(numero)
        return "%03d" % numero

    filas = []
    sensor_propuesto: dict[str, str] = {}
    for b in bloqueos:
        if b["Clasificacion"] not in ("BLOQUEADO_EXTREMO_COMPARTIDO", "REVISION_ELEMENTO_FINAL"):
            continue
        plc, programa, instancia = clave_de(b["Lazo"])
        rutina = next((f["Routine"] for f in analisis
                       if (f["PLC"], f["Program"], f["Instancia"]) == (plc, programa, instancia)), "")
        a = indice.get((plc, programa, rutina, instancia), {})
        motivo = b["Motivo"]
        entradas, salidas = direcciones(a.get("Entrada_Fisica", "")), direcciones(a.get("Salida_Fisica", ""))

        # --- señales para elegir la regla ---
        motor_final = es_motor(b["Lazo"], a.get("Entrada_Operando", ""), a.get("Salida_Fisica", ""),
                               a.get("Nota", "")) or b["Clasificacion"] == "REVISION_ELEMENTO_FINAL"
        compartido_en = []
        for direccion in entradas:
            otros = [k for k in comparten.get(direccion, []) if k != (plc, programa, rutina, instancia)]
            if otros:
                compartido_en.append((direccion, len(otros) + 1))
        salida_multiple = len(salidas) > 1
        salida_misma_clase = salida_multiple and len({d.split("(")[0].split(":")[0].strip() for d in salidas}) <= len(salidas)

        reglas, motivos, evidencias, observaciones = [], [], [], []
        if motor_final:
            reglas.append("R-A")
            motivos.append("elemento final motriz (arrancador/variador), no valvula")
            evidencias.append("salida: %s" % (a.get("Salida_Fisica", "")[:90] or motivo[:90]))
            observaciones.append("Arrancador de bomba como elemento final (on/off)")
        if compartido_en:
            reglas.append("R-B")
            for direccion, n in compartido_en:
                motivos.append("sensor compartido: %s alimenta %d lazos" % (direccion[:52], n))
            evidencias.append("entrada: %s" % "; ".join(d for d, _ in compartido_en)[:90])
            observaciones.append("PV compartido con %s" % "; ".join(d for d, _ in compartido_en)[:80])
        if salida_multiple:
            reglas.append("R-C")
            tipo_salidas = "motores/arrancadores" if motor_final else "direcciones fisicas"
            motivos.append("la salida alcanza %d %s del mismo tipo" % (len(salidas), tipo_salidas))
            evidencias.append("salida: %s" % a.get("Salida_Fisica", "")[:110])
            observaciones.append("Elementos finales en paralelo")
        if not reglas:
            reglas, motivos = ["(sin regla aplicable)"], ["el bloqueo no cae en R-A, R-B ni R-C"]

        area, criterio_area, confianza_area = gpm.area_del_lazo(
            dict(a, PLC=plc, Program=programa, Routine=rutina, Instancia=instancia))
        variable, criterio_variable = gpm.variable_del_lazo(
            dict(a, PLC=plc, Program=programa, Routine=rutina, Instancia=instancia))
        if confianza_area and confianza_area != "ALTA":
            observaciones.append("area por defecto del PLC (%s): revisar prefijo ISA" % confianza_area)
        numero = siguiente_libre(area) if area else ""
        funcion_salida = "Y" if motor_final else "XV"
        tags = []
        if numero and area and variable:
            tags.append("%s_%sT_%s" % (area, variable, numero))
            tags.append("%s_%sIC_%s" % (area, variable, numero))
            tags.append("%s_%s%s_%s" % (area, variable, funcion_salida, numero))
        if "R-B" in reglas:
            # El lazo propio del sensor se propone UNA vez, aunque N controladores lo compartan.
            for direccion, _n in compartido_en:
                if direccion not in sensor_propuesto:
                    area_sensor = area or "700"
                    variable_sensor = variable_del_sensor(a.get("Entrada_Operando", "")) or "P"
                    sensor_propuesto[direccion] = "%s_%sT_%s" % (
                        area_sensor, variable_sensor, siguiente_libre(area_sensor))
                    tags.insert(0, "%s (lazo propio del sensor compartido)"
                                % sensor_propuesto[direccion])
                else:
                    tags.insert(0, "lazo del sensor ya propuesto: %s" % sensor_propuesto[direccion])

        filas.append({
            "Lazo": b["Lazo"], "PLC": plc, "Program": programa, "Routine": rutina, "Instancia": instancia,
            "Area": area, "Area_Confianza": confianza_area, "Variable_ISA": variable,
            "Criterio_Area": criterio_area, "Criterio_Variable": criterio_variable,
            "Clasificacion_Bloqueo": b["Clasificacion"],
            "Motivo_Bloqueo": motivo, "Regla": " + ".join(reglas), "Motivo_Regla": " | ".join(motivos),
            "Evidencia_XML": " | ".join(e for e in evidencias if e),
            "Numero_Tentativo": numero, "Tags_Que_Se_Insertarian": " | ".join(tags),
            "Observacion": " | ".join(observaciones), "Requiere_Autorizacion": "SI",
            "Escritura_SQLite": "NO",
        })

    filas.sort(key=lambda f: (f["Regla"], f["PLC"], f["Program"], f["Instancia"]))
    with open(SALIDA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", lineterminator="\n")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)

    conteo = defaultdict(int)
    for f in filas:
        conteo[f["Regla"]] += 1
    resumen = escribir_resumen(filas)
    print("Decisiones pendientes: %d lazos bloqueados clasificados" % len(filas))
    for regla, n in sorted(conteo.items(), key=lambda x: (-x[1], x[0])):
        print("   %-26s %d" % (regla, n))
    print("[OK] %s" % SALIDA)
    print("[OK] %s" % resumen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
