"""
cruzar_planta_viva.py
======================
Cruce de validacion entre los resultados de la auditoria ISA-5.1 (generados
EXCLUSIVAMENTE desde los .L5X, en auto_agustin/resultados/) y los inventarios
de variables vivas relevados por Yanco directamente de los PLCs fisicos
(carpeta "variables plc programa yanco/", archivos .xlsx).

Reglas de diseno (confirmadas con el Ingenio, 06/08/2026):
  - Los .xlsx NUNCA se usan para proponer/generar tags nuevos. Son solo una
    tabla de validacion cruzada de "esto sigue vivo en el PLC real?".
  - Los CSV originales de resultados/ NO se tocan (son la fuente de verdad).
    Este script escribe copias enriquecidas en resultados_cruzados/.
  - Un PLC canonico sin Excel de Yanco NO se marca como obsoleto (seria un
    error grave: puede estar perfectamente vivo, solo que Yanco no lo relevo
    todavia). Se usa un tercer estado explicito: "Sin_Relevamiento_Vivo".

Logica de emparejamiento Excel <-> proyecto CSV:
  Cada .xlsx tiene una hoja "PLCs" con 1 fila: IP ("PLC (path)") y el nombre
  real del controlador ("Nombre de programa"). Se compara ese nombre
  (case-insensitive, exacto primero y por prefijo como fallback -- cubre
  casos como el Excel "DESTILERIA" contra el proyecto "DESTILERIA_RECUPERADO")
  contra los nombres de proyecto que ya tiene resultados/ (derivados de los
  nombres de los .L5X canonicos). Si matchea, el Excel queda asociado a ese
  proyecto. Si un Excel no matchea ningun proyecto (ej. PLCs vivos que
  todavia no tienen .L5X exportado), se reporta aparte como hallazgo
  informativo, sin generar CSV para el.

  Un mismo proyecto puede recibir MAS DE UN Excel: pares redundantes
  primario/secundario (ej. Calderas_8_9_10_Desaireador en .195 y .196, o
  CALD_LA_FLORIDA en .251 y .252 -- controladores con modulo de redundancia
  1756-RM2, confirmado en el backplane) o relevamientos repetidos del mismo
  PLC. En esos casos se fusiona (union) el set de tags vivos de todas las
  fuentes: si el tag vive en CUALQUIERA de los controladores del par cuenta
  como "En Uso", y la columna IP_Fisica lista todas las IPs involucradas.

Topologia del complejo Destileria (reestructurado 06/08/2026, revision de
red con el ingeniero de planta -- ver MANUAL_IP_OVERRIDES y
PROYECTOS_CONGELADOS mas abajo):
  El area "Destileria" NO es un solo controlador: es un complejo de varios
  equipos fisicos separados en la red:
    - JW                        -> 192.168.10.128
    - Fermentacion Analogica    -> 192.168.10.131  (Excel pendiente)
    - Fermentacion Digital      -> 192.168.10.132  (Excel pendiente)
    - Evaporacion / Vinaza      -> IP a confirmar   (Excel pendiente)
  El Excel "PLC_Destileria.xlsx" que se habia asociado antes a
  DESTILERIA_RECUPERADO por su 'Nombre de programa' ("DESTILERIA") en
  realidad corresponde al equipo JW (IP .128) -- el nombre de programa
  reportado por el Excel es enganoso, la IP es la que manda. Por eso la
  IP .128 tiene una reasignacion manual explicita (MANUAL_IP_OVERRIDES)
  que gana por sobre el matching por nombre. DESTILERIA_RECUPERADO y
  vinaza quedan congelados (PROYECTOS_CONGELADOS): no se cruzan con NINGUN
  Excel hasta que se consigan los relevamientos correctos de .131 y .132.

Logica de matching de tags (arquitectura Rockwell):
  - Tags de alcance "Controller": el Excel los guarda con su nombre tal cual
    (ej. "SP_CALCULADO1"). Match directo, exacto (case-insensitive).
  - Tags de alcance "Program": el Excel los guarda ya calificados como
    "PROGRAM:<programa>.<tag>" (ej. "PROGRAM:MAINPROGRAM.MOTORB1C"). Nuestros
    CSV (extraidos del .L5X) guardan el nombre pelado, sin el prefijo. Por
    eso el set de tags vivos se arma con AMBAS formas: el texto completo y,
    para los calificados, el texto despues del primer '.'.
  Validado con DIBACCO: 568/568 filas del CSV (100%) encontraron su par en
  el Excel usando esta logica combinada.

Uso:
    python cruzar_planta_viva.py
"""

import os
import re
import csv
import glob

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DIR_L5X = os.path.join(PROJECT_ROOT, "auto_agustin")
DIR_RESULTADOS = os.path.join(DIR_L5X, "resultados")
DIR_SALIDA = os.path.join(DIR_L5X, "resultados_cruzados")
DIR_YANCO = os.path.join(PROJECT_ROOT, "variables plc programa yanco")

CAMPOS_ORIG = ["tag_viejo", "clase", "funcion_ISA", "area_detectada", "cod_area",
               "datatype", "alias_for", "tag_nuevo_propuesto", "descripcion", "validacion"]
CAMPOS_SALIDA = CAMPOS_ORIG + ["Estado_Planta", "IP_Fisica"]

EN_USO = "En Uso"
OBSOLETO = "Obsoleto/Desconectado"
SIN_RELEVAMIENTO = "Sin_Relevamiento_Vivo"

_RE_PROGRAM_TAG = re.compile(r"^PROGRAM:[^.]+\.(.+)$", re.IGNORECASE)
_RE_SUFIJO_CSV = re.compile(r"_(mapeo_exitoso|sin_clasificar)\.csv$", re.IGNORECASE)

# --------------------------------------------------------------------
# Reasignacion manual de IP (06/08/2026, revision de topologia de red con
# el ingeniero de planta). Tiene PRIORIDAD ABSOLUTA sobre el matching por
# 'Nombre de programa': si la IP de un Excel esta en este diccionario, se
# asocia al proyecto indicado sin importar que programa reporte el Excel.
#
# CIERRE 28/08/2026: la entrada de la IP .128 -> 'jw2013' se RETIRA.
# Estaba justificada por sospechar que el Excel "PLC_Destileria.xlsx"
# (IP .128, 'Nombre de programa'='DESTILERIA') no correspondia al equipo
# fisico real ("el equipo fisico en esa IP es JW"). Confirmado con
# Ingenieria: el Excel tenia razon desde el principio -- esa IP es el PLC
# principal de Destileria; "jw" era solo el nombre de un tacho viejo, no
# el equipo. El canonico ahora se llama 'DESTILERIA' (ver
# AREA_DEFECTO_POR_PLC en auditar_l5x.py), por lo que el matching NATURAL
# por nombre de programa ya resuelve esta IP correctamente sin necesitar
# override.
MANUAL_IP_OVERRIDES = {}

# Proyectos que NO deben cruzarse con NINGUN Excel por ahora, aunque algun
# Excel matchee su nombre. Se fuerzan a Sin_Relevamiento_Vivo hasta que se
# levante el freeze explicitamente. Motivo (06/08/2026): el complejo
# Destileria se reestructuro en varios equipos fisicos separados (PLC
# principal DESTILERIA .128 -- ya resuelto, ver MANUAL_IP_OVERRIDES arriba --
# Fermentacion Analogica .131, Fermentacion Digital .132, Evaporacion/Vinaza)
# y todavia no llegaron los relevamientos correctos de .131 / .132 --
# hasta entonces, ni DESTILERIA_RECUPERADO ni vinaza deben quedar
# validados con datos que en realidad son de otro equipo.
PROYECTOS_CONGELADOS = {
    "DESTILERIA_RECUPERADO": "complejo Destileria en reestructuracion; esperando Excels de .131 (Ferm. Analogica) y .132 (Ferm. Digital)",
    "vinaza": "complejo Destileria en reestructuracion; esperando Excel de Evaporacion/Vinaza con IP confirmada",
}


# ------------------------------------------------------------------
def descubrir_proyectos(dir_resultados):
    """Nombres de proyecto (PLC canonico) a partir de los CSV existentes."""
    proyectos = set()
    for f in os.listdir(dir_resultados):
        m = _RE_SUFIJO_CSV.search(f)
        if m:
            proyectos.add(f[: m.start()])
    return proyectos


def _emparejar_proyecto(programa, proyectos):
    """Encuentra el proyecto CSV correspondiente a un 'Nombre de programa'
    de Excel. Primero intenta match exacto (case-insensitive). Si no hay,
    prueba match por prefijo en cualquier sentido (cubre casos como el
    Excel 'DESTILERIA' contra el proyecto 'DESTILERIA_RECUPERADO', que no
    son iguales pero claramente el mismo controlador). Si el prefijo es
    ambiguo (matchea mas de un proyecto), no arriesga: lo deja huerfano."""
    p_low = programa.lower()
    exactos = [p for p in proyectos if p.lower() == p_low]
    if len(exactos) == 1:
        return exactos[0]
    prefijos = [p for p in proyectos
                if p.lower().startswith(p_low) or p_low.startswith(p.lower())]
    if len(prefijos) == 1:
        return prefijos[0]
    return None


def cargar_excels_yanco(dir_yanco, proyectos):
    """Lee cada .xlsx, arma el set de tags vivos (con el fallback de
    PROGRAM:) y lo asocia al proyecto CSV cuyo nombre coincide (exacto o
    por prefijo) con el 'Nombre de programa' del PLC.

    Un mismo proyecto puede tener MAS DE UN Excel asociado: pares
    redundantes (primario/secundario, ej. Calderas_8_9_10_Desaireador en
    .195 y .196, o CALD_LA_FLORIDA en .251 y .252) o relevamientos
    repetidos del mismo PLC. En esos casos se fusionan (union) los sets de
    tags vivos de todas las fuentes -- si el tag vive en CUALQUIERA de los
    controladores del par, cuenta como "En Uso" -- y se listan todas las
    IPs involucradas.

    Devuelve (asociados: {proyecto: {"ips": [...], "tags_vivos": set,
              "archivos": [...]}},
              huerfanos: [(programa, ip, cant_tags, archivo)],  -- excels
              sin proyecto CSV que los reclame
              congelados: [(proyecto, programa, ip, archivo)])  -- excels que
              SI matchearon un proyecto pero ese proyecto esta en
              PROYECTOS_CONGELADOS: se descartan a proposito, no se asocian.
    """
    asociados = {}
    huerfanos = []
    congelados = []

    for path in sorted(glob.glob(os.path.join(dir_yanco, "*.xlsx"))):
        xl = pd.ExcelFile(path, engine="openpyxl")
        info = xl.parse("PLCs").iloc[0]
        ip = str(info["PLC (path)"]).strip()
        programa = str(info["Nombre de programa"]).strip()
        tags_df = xl.parse("Tags")

        tags_raw = tags_df["Tag"].astype(str).str.strip().str.upper()
        tags_vivos = set(tags_raw)
        for t in tags_raw:
            m = _RE_PROGRAM_TAG.match(t)
            if m:
                tags_vivos.add(m.group(1))

        # La reasignacion manual por IP gana por sobre el nombre reportado
        # por el propio Excel (ver MANUAL_IP_OVERRIDES).
        if ip in MANUAL_IP_OVERRIDES:
            proyecto = MANUAL_IP_OVERRIDES[ip]
        else:
            proyecto = _emparejar_proyecto(programa, proyectos)

        if proyecto and proyecto in PROYECTOS_CONGELADOS:
            congelados.append((proyecto, programa, ip, os.path.basename(path)))
            continue

        if proyecto:
            entrada = asociados.setdefault(
                proyecto, {"ips": [], "tags_vivos": set(), "archivos": [], "programa": programa})
            if ip not in entrada["ips"]:
                entrada["ips"].append(ip)
            entrada["tags_vivos"] |= tags_vivos
            entrada["archivos"].append(os.path.basename(path))
        else:
            huerfanos.append((programa, ip, len(tags_df), os.path.basename(path)))

    return asociados, huerfanos, congelados


# ------------------------------------------------------------------
def cruzar_csv(path_csv, info_planta):
    """Lee un CSV de resultados, agrega Estado_Planta / IP_Fisica, devuelve
    (filas_enriquecidas, metricas)."""
    with open(path_csv, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        filas = list(reader)

    en_uso = 0
    obsoleto = 0
    ip_fisica = " / ".join(info_planta["ips"]) if info_planta else ""
    for fila in filas:
        tag_norm = (fila.get("tag_viejo") or "").strip().upper()
        if info_planta is None:
            fila["Estado_Planta"] = SIN_RELEVAMIENTO
            fila["IP_Fisica"] = ""
        elif tag_norm in info_planta["tags_vivos"]:
            fila["Estado_Planta"] = EN_USO
            fila["IP_Fisica"] = ip_fisica
            en_uso += 1
        else:
            fila["Estado_Planta"] = OBSOLETO
            fila["IP_Fisica"] = ip_fisica
            obsoleto += 1

    return filas, {"total": len(filas), "en_uso": en_uso, "obsoleto": obsoleto,
                    "sin_relevamiento": len(filas) if info_planta is None else 0}


def escribir_csv(path_salida, filas):
    with open(path_salida, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_SALIDA, delimiter=";")
        w.writeheader()
        w.writerows(filas)


# ------------------------------------------------------------------
def main():
    if not os.path.isdir(DIR_RESULTADOS):
        print(f"No existe: {DIR_RESULTADOS}")
        return
    if not os.path.isdir(DIR_YANCO):
        print(f"No existe: {DIR_YANCO}")
        return
    os.makedirs(DIR_SALIDA, exist_ok=True)

    proyectos = descubrir_proyectos(DIR_RESULTADOS)
    asociados, huerfanos, congelados = cargar_excels_yanco(DIR_YANCO, proyectos)

    print("=" * 74)
    print("  CRUCE PLANTA VIVA (Yanco) x AUDITORIA ISA-5.1 (L5X)")
    print("=" * 74)
    print(f"Proyectos con CSV de auditoria : {len(proyectos)}")
    print(f"Excels de Yanco encontrados    : {len(asociados) + len(huerfanos) + len(congelados)}")
    print(f"  -> asociados a un PLC canonico: {len(asociados)}")
    print(f"  -> descartados (proyecto congelado): {len(congelados)}")
    print(f"  -> sin PLC canonico (bonus)   : {len(huerfanos)}")
    print("-" * 74)

    metricas_por_proyecto = []
    for proyecto in sorted(proyectos):
        info_planta = asociados.get(proyecto)
        tot = {"total": 0, "en_uso": 0, "obsoleto": 0, "sin_relevamiento": 0}
        for sufijo in ("mapeo_exitoso", "sin_clasificar"):
            nombre = f"{proyecto}_{sufijo}.csv"
            path_in = os.path.join(DIR_RESULTADOS, nombre)
            if not os.path.isfile(path_in):
                continue
            filas, m = cruzar_csv(path_in, info_planta)
            escribir_csv(os.path.join(DIR_SALIDA, nombre), filas)
            for k in tot:
                tot[k] += m[k]

        if proyecto in PROYECTOS_CONGELADOS:
            estado = "CONGELADO (freeze manual)"
        elif info_planta:
            estado = f"IP {' / '.join(info_planta['ips'])}"
        else:
            estado = "SIN EXCEL DE YANCO"
        pct_uso = (100 * tot["en_uso"] / tot["total"]) if tot["total"] else 0.0
        print(f"  [{estado:38}] {proyecto:26} tot {tot['total']:5} | "
              f"en_uso {tot['en_uso']:5} ({pct_uso:5.1f}%) | "
              f"obsoleto {tot['obsoleto']:5} | sin_dato {tot['sin_relevamiento']:5}")
        metricas_por_proyecto.append((proyecto, tot))

    # ---- Resumen global ----
    g_total = sum(m["total"] for _, m in metricas_por_proyecto)
    g_uso = sum(m["en_uso"] for _, m in metricas_por_proyecto)
    g_obs = sum(m["obsoleto"] for _, m in metricas_por_proyecto)
    g_sin = sum(m["sin_relevamiento"] for _, m in metricas_por_proyecto)
    universo_verificable = g_uso + g_obs  # excluye los Sin_Relevamiento_Vivo

    print("=" * 74)
    print("  RESUMEN GLOBAL")
    print("=" * 74)
    print(f"  Tags totales (todos los proyectos)      : {g_total}")
    print(f"  PLCs SIN Excel de Yanco (Sin_Relevamiento_Vivo): {g_sin} tags "
          f"({len([p for p, m in metricas_por_proyecto if m['sin_relevamiento']])} proyectos)")
    print("-" * 74)
    print(f"  Universo verificable (con Excel)        : {universo_verificable}")
    print(f"    En Uso                                : {g_uso}"
          + (f"  ({100*g_uso/universo_verificable:.1f}%)" if universo_verificable else ""))
    print(f"    Obsoleto/Desconectado                 : {g_obs}"
          + (f"  ({100*g_obs/universo_verificable:.1f}%)" if universo_verificable else ""))
    print("=" * 74)
    print(f"  CSV cruzados escritos en: {DIR_SALIDA}")

    if congelados:
        print("\n  --- Excels DESCARTADOS a proposito (proyecto congelado) ---")
        for proyecto, programa, ip, archivo in congelados:
            motivo = PROYECTOS_CONGELADOS.get(proyecto, "")
            print(f"    - {archivo} (IP {ip}, programa reportado '{programa}') "
                  f"matcheaba a '{proyecto}', congelado: {motivo}")

    if huerfanos:
        print("\n  --- Hallazgos bonus: Excels de Yanco de PLCs vivos SIN auditoria L5X ---")
        for programa, ip, n_tags, archivo in huerfanos:
            print(f"    - {programa} (IP {ip}, {n_tags} tags vivos) -- archivo: {archivo}"
                  f"  [pendiente exportar su .L5X para poder auditarlo]")


if __name__ == "__main__":
    main()
