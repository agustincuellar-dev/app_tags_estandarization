"""Propuesta masiva de numeracion (Fase 3 del sprint) — SOLO LECTURA sobre SQLite.

Entrada : exports/analisis_40_lazos.csv (salida de src/trazador_lazos_profundo.py)
Salidas : exports/propuesta_numeracion_masiva_180926_v1.csv      (una fila por TAG propuesto)
          exports/resumen_propuesta_masiva_180926_v1.csv        (resumen por area y variable)
          exports/bloqueos_propuesta_masiva_180926_v1.csv       (por que NO entra cada lazo)
          El entregable vigente (v2, corregido) lo escribe src/corregir_propuesta_masiva.py.

CRITERIOS DE ELEGIBILIDAD (todos obligatorios; si falla uno, el lazo NO entra)
--------------------------------------------------------
1. El trazador lo clasifico CERRABLE_HOY (entrada y salida con direccion fisica unica).
2. Extremo EXCLUSIVO: ni la direccion fisica de entrada ni la de salida pueden estar
   compartidas con otro lazo cerrable. Un instrumento que alimenta varios controladores es
   exactamente el bloqueo EXTREMO_COMPARTIDO que el proyecto ya trata como no numerable.
3. Area determinable con criterio documentado:
     - prefijo de programa/tag segun docs/Manual_Estandarizacion.md:87-97
       (EVAP=500, COC=600, CCV=700, CLA=400, SEC=800, DEST=200, CAL=300, MOL=100)
     - o PLC segun src/auditar_l5x.py AREA_DEFECTO_POR_PLC + MAPEO_AREA_OVERRIDE_POR_PLC
   Si las señales no coinciden, el area queda ambigua y el lazo NO entra.
4. Variable ISA determinada por el morfema del tag de entrada (PT->P, TT->T, LT->L, FT->F,
   AIT->A, DT->D) y CONFIRMADA por el tipo de controlador (CONTROL_PRESION*->P,
   CONTROL_NIVEL*->L, CONTROL_TEMPERATURA*->T, CONTROL_CAUDAL*->F). Si discrepan, NO entra.

UNIVERSOS DE VERIFICACION DE NUMERO LIBRE
------------------------------------------
U1 DB de produccion (20 tags) por (area, numero) y por tag_completo.
U2 Backup historico de 693 por (area, numero).
U3 Inventarios online declarados (areas 200 y 300) via src/identificadores_vigentes.py.
U4 Identificadores ISA-like del L5X de los 10 PLC (morfema ISA + numero 2-3 digitos).
U5 Numeros ISA citados en docs/*.md por area (documentacion del proyecto).

El numero asignado es un CANDIDATO: no se inserta nada y no se toca la base.
"""

from __future__ import annotations

import csv
import re
import sqlite3
import sys
from collections import Counter, OrderedDict, defaultdict
from contextlib import closing
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from identificadores_vigentes import cargar_catalogos_isa, extraer_todo, formatear_rangos  # noqa: E402

ANALISIS = RAIZ / "exports" / "analisis_210_lazos.csv"
ANALISIS_40 = RAIZ / "exports" / "analisis_40_lazos.csv"
# OJO: este modulo NO escribe el nombre canonico del entregable. Su salida es la v1 (propuesta
# previa al pase de correccion R1..R7); el entregable vigente lo escribe
# src/corregir_propuesta_masiva.py. Asi el generador se puede re-correr sin pisar la v2.
SALIDA = RAIZ / "exports" / "propuesta_numeracion_masiva_180926_v1.csv"
RESUMEN = RAIZ / "exports" / "resumen_propuesta_masiva_180926_v1.csv"
BLOQUEOS = RAIZ / "exports" / "bloqueos_propuesta_masiva_180926_v1.csv"

DB_PRODUCCION = RAIZ / "app_etiquetas" / "tags_ingenio.db"
# U1 para numerar es un SNAPSHOT inmutable pre-olas (20 tags), no la producción viva: la
# producción cambia después de cada alta y no puede renumerar retrospectivamente la propuesta.
SNAPSHOT_OCUPACION = RAIZ / "app_etiquetas" / "backups" / "tags_ingenio_antes_ola1_20260921_080425_058865_byte_identico.db"
BACKUP_693 = RAIZ / "app_etiquetas" / "backups" / "tags_ingenio_antes_purga_20260911_110901_186931.db"
DIR_L5X = RAIZ / "L5X_Produccion"
DIR_DOCS = RAIZ / "docs"

# U5 (numeros citados en docs/) NO lee los informes de avance del sprint: son documentos DERIVADOS
# del propio CSV, citan numeros CANDIDATOS que no asignan nada y, si se contaran como ocupacion,
# cada informe renumeraria el entregable que documenta (verificado el 21/09: el informe del 18/09
# movia 100/029, 200/087 y 700/008). Los informes anteriores a esta fecha de corte se siguen
# leyendo: cambiarlo ensancha la numeracion libre y es una decision del usuario, no del motor.
INFORMES_DERIVADOS_DESDE = "2026-09-18"

# Prefijo -> area, segun docs/Manual_Estandarizacion.md:87-97 (acronimos oficiales de la tabla).
AREA_POR_PREFIJO = {
    "RECEP": "000", "MOL": "100", "DEST": "200", "CAL": "300", "CLA": "400", "EVAP": "500",
    "COC": "600", "CCV": "700", "SEC": "800", "FM": "900", "TAS": "950",
}
# PLC -> area, segun src/auditar_l5x.py (AREA_DEFECTO_POR_PLC + override del desaireador).
AREA_POR_PLC = {
    "CENTRIFUGA_DE_PRIMERA": "700", "USINA_LA_FLORIDA": "900", "DIBACCO": "000",
    "CALD_LA_FLORIDA": "300", "cenizas2020": "300", "DESTILERIA": "200",
    "Painel_Ctr_Turb_Moenda": "100", "TRAPICHE2022": "100",
    "Calderas_8_9_10_Desaireador": "300", "FABRICA": None,
}
# Área por identidad, solo para FABRICA y por decisión explícita del usuario del 23/09/2026.
# FLEX5000_MIELES se incluye como identidad de canal, no como acrónimo general de área.
AREA_POR_IDENTIDAD_POR_PLC = {
    "FABRICA": {
        "TK_MIEL": "700", "MIEL_CENT": "700", "MIEL_RICA": "700",
        "FLEX5000_MIELES": "700",
    },
}
PROGRAMAS_AREA_PENDIENTE_USUARIO = {"SULFO_ENCALADO"}
INSTANCIAS_AREA_PENDIENTE_USUARIO = {
    "COC_LC_MELADO_T", "CONTROL_PRESION_BIO", "CONTROL_CAUDAL_JUGO_DEST",
}
MORFEMA_A_VARIABLE = {"PT": "P", "TT": "T", "LT": "L", "FT": "F", "AIT": "A", "AT": "A",
                      "DT": "D", "WT": "W", "ST": "S", "IT": "I", "PIT": "P", "LIT": "L", "TIT": "T"}
AOI_A_VARIABLE = {"CONTROL_PRESION": "P", "CONTROL_NIVEL": "L", "CONTROL_TEMPERATURA": "T",
                  "CONTROL_CAUDAL": "F", "CONTROL_FLUJO": "F", "CONTROL_DENSIDAD": "D",
                  "CONTROL_ANALISIS": "A", "CONTROL_PRESION_CASCADA": "P"}

ESTADO = "PROPUESTA_CONCRETA_PARA_REVISION — NO_INSERTAR"
RE_ISA = re.compile(r"^([A-Z]{1,4})(?:_[A-Z0-9]+)*_(\d{2,4})$")
RE_CITA_DOC = re.compile(r"\b(000|100|200|250|300|400|500|600|700|800|900|950)_([A-Z]{1,4})_(\d{2,4})\b")


# ------------------------------------------------------------------ universos
def ocupacion_db(ruta: Path) -> tuple:
    """(conjunto (area,numero), conjunto de tag_completo) de una base."""
    pares, tags = set(), set()
    with closing(sqlite3.connect(Path(ruta).resolve().as_uri() + "?mode=ro", uri=True)) as c:
        c.execute("PRAGMA query_only=ON")
        for codigo, numero, tag in c.execute(
                "SELECT a.codigo, t.numero_loop, t.tag_completo FROM tags t JOIN areas a ON a.id = t.area_id"):
            pares.add((codigo, int(numero)))
            tags.add(tag)
    return pares, tags


def ocupacion_l5x(variables, funciones) -> dict:
    """{numero: set(identificadores)} de los 10 L5X, usando la misma regla morfema+numero
    que src/identificadores_vigentes.py (documentada y testeada alli)."""
    hallados = defaultdict(set)
    for ruta in sorted(DIR_L5X.glob("*.L5X")):
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'(?:Name|Operand)="([^"]+)"', texto):
            nombre = m.group(1).lstrip("\\").split(".")[-1]
            partes = nombre.split("_")
            for i in range(len(partes) - 1):
                numero = partes[i + 1]
                morfema = partes[i]
                if numero.isdigit() and 2 <= len(numero) <= 3 and len(morfema) >= 2 \
                        and morfema[0] in variables and morfema[1:] in funciones:
                    hallados[int(numero)].add(nombre)
    return hallados


def es_informe_derivado(ruta: Path) -> bool:
    """True para los informes de avance del sprint (documentos derivados del CSV, no normativos).

    El nombre del informe es `Resumen_Ejecutivo_Avance_DDMMAA.md` (el dia que cubre). Se compara
    como fecha ISO para que el corte no dependa del orden alfabetico del nombre.
    """
    m = re.match(r"^Resumen_Ejecutivo_Avance_(\d{2})(\d{2})(\d{2})\.md$", ruta.name)
    if not m:
        return False
    dia, mes, anio = m.groups()
    return "20%s-%s-%s" % (anio, mes, dia) >= INFORMES_DERIVADOS_DESDE


def ocupacion_docs() -> dict:
    """{area: set(numeros)} citados en la documentacion NO derivada del proyecto."""
    por_area = defaultdict(set)
    for ruta in sorted(DIR_DOCS.glob("*.md")):
        if es_informe_derivado(ruta):
            continue
        for area, _morfema, numero in RE_CITA_DOC.findall(ruta.read_text(encoding="utf-8", errors="replace")):
            por_area[area].add(int(numero))
    return por_area


def cargar_universos(snapshot_db: Path = SNAPSHOT_OCUPACION) -> dict:
    """Carga U1 desde un snapshot explícito, nunca desde la base viva de producción."""
    variables, funciones = cargar_catalogos_isa(snapshot_db)
    pares_prod, tags_prod = ocupacion_db(snapshot_db)
    pares_hist, tags_hist = ocupacion_db(BACKUP_693)
    # U3: TODAS las areas declaradas (100, 200, 300, 500, 600, 700) — R6 del pase de correccion.
    inv = {}
    for resultado in extraer_todo():
        inv[resultado["area"]] = set(resultado["numeros"])
    return {
        "prod": pares_prod, "prod_tags": tags_prod,
        "hist": pares_hist, "hist_tags": tags_hist,
        "inventario": inv,
        "l5x": ocupacion_l5x(variables, funciones),
        "docs": ocupacion_docs(),
    }


def numero_ocupado(area: str, numero: int, u: dict) -> list:
    """Devuelve la lista de universos donde (area,numero) YA esta ocupado."""
    donde = []
    if (area, numero) in u["prod"]:
        donde.append("U1_DB_produccion")
    if (area, numero) in u["hist"]:
        donde.append("U2_backup_693")
    if numero in u["inventario"].get(area, set()):
        donde.append("U3_inventario_online")
    if numero in u["l5x"]:
        donde.append("U4_identificadores_L5X")
    if numero in u["docs"].get(area, set()):
        donde.append("U5_documentacion")
    return donde


def numeros_libres(area: str, u: dict, cuantos: int) -> list:
    """Numeros consecutivos libres del area, desde el menor disponible."""
    libres, n = [], 1
    while len(libres) < cuantos and n <= 999:
        if not numero_ocupado(area, n, u):
            libres.append(n)
        n += 1
    return libres


# ------------------------------------------------------------------ criterios
def area_del_lazo(fila: dict) -> tuple:
    """(area, criterio, confianza). ('', motivo, '') si es ambigua."""
    plc = str(fila.get("PLC", ""))
    program = str(fila.get("Program", ""))
    instancia = str(fila.get("Instancia") or fila.get("Instancia_AOI") or "")
    if (program.upper() in PROGRAMAS_AREA_PENDIENTE_USUARIO or
            instancia.upper() in INSTANCIAS_AREA_PENDIENTE_USUARIO):
        return ("", "área expresamente pendiente por decisión de usuario; no asignar", "")
    identidades = " ".join(str(fila.get(campo) or "") for campo in
                            ("Instancia", "Instancia_AOI", "Entrada_Operando", "Entrada_Fisica", "Salida_Fisica")).upper()
    for identidad, area in AREA_POR_IDENTIDAD_POR_PLC.get(plc, {}).items():
        if re.search(r"(?<![A-Z0-9])%s(?![A-Z0-9])" % re.escape(identidad), identidades):
            return (area, "decisión de usuario 23/09/2026; identidad/prefijo Mieles %s en FABRICA" % identidad,
                    "ALTA")
    prefijos = set()
    for campo in ("Entrada_Fisica", "Salida_Fisica"):
        for trozo in (fila.get(campo) or "").split("|"):
            nombre = trozo.strip().split(" ")[0]
            if "_" in nombre:
                prefijos.add(nombre.split("_")[0])
    areas_prefijo = {AREA_POR_PREFIJO[p] for p in prefijos if p in AREA_POR_PREFIJO}
    area_plc = AREA_POR_PLC.get(fila["PLC"], None)
    # El prefijo del PROGRAMA tambien cuenta (FAB_EVAP -> EVAP)
    sufijo_prog = fila["Program"].split("_")[-1]
    if sufijo_prog in AREA_POR_PREFIJO:
        areas_prefijo.add(AREA_POR_PREFIJO[sufijo_prog])

    if len(areas_prefijo) == 1:
        area = areas_prefijo.pop()
        if area_plc and area_plc != area:
            return ("", "area contradictoria: prefijos->%s / PLC->%s" % (area, area_plc), "")
        return (area, "prefijos de tag/programa segun Manual_Estandarizacion.md:87-97 (%s)"
                % ",".join(sorted(prefijos | {sufijo_prog})), "ALTA")
    if len(areas_prefijo) > 1:
        return ("", "prefijos de area contradictorios entre los tags del lazo: %s"
                % ",".join(sorted(areas_prefijo)), "")
    if area_plc:
        return (area_plc, "PLC segun src/auditar_l5x.py AREA_DEFECTO_POR_PLC", "MEDIA")
    return ("", "area no determinable: sin prefijo documentado y PLC sin area declarada", "")


def variable_del_lazo(fila: dict) -> tuple:
    """(variable, criterio). MANDA EL MORFEMA DE LA ENTRADA.

    Precedente que fija esta regla: el lazo ya aprobado `200_FIC_081` usa el AOI
    `CONTROL_NIVEL` (nombre generico) sobre una entrada de caudal `FT_AGUA`, y se aprobo como
    variable F. En esta planta el nombre del AOI no determina la variable del lazo; la medicion
    si. El tipo de AOI se usa como respaldo cuando la direccion fisica no aporta morfema, y toda
    discrepancia queda anotada (no bloquea).
    """
    morfemas = set()
    for trozo in (fila.get("Entrada_Fisica") or "").split("|"):
        nombre = trozo.strip().split(" ")[0]
        for p in nombre.lstrip("\\").split("_"):
            if p in MORFEMA_A_VARIABLE:
                morfemas.add(MORFEMA_A_VARIABLE[p])
                break
    morfema_interno = ""
    if not morfemas:
        nombre = str(fila.get("Entrada_Operando", "")).strip()
        if "." in nombre:
            nombre = nombre.rsplit(".", 1)[-1]
        for p in nombre.split("_"):
            if p in MORFEMA_A_VARIABLE:
                morfemas.add(MORFEMA_A_VARIABLE[p])
                morfema_interno = nombre
                break
    tipo = fila.get("Tipo_AOI", "")
    variable_aoi = next((v for k, v in AOI_A_VARIABLE.items() if tipo.startswith(k)), None)

    if len(morfemas) == 1:
        variable = morfemas.pop()
        if morfema_interno:
            return (variable, "morfema del tag interno conectado a PV (%s) -> %s"
                    % (morfema_interno, variable))
        if variable_aoi and variable_aoi != variable:
            return (variable, "morfema de la entrada -> %s (el AOI %s sugiere %s, nombre generico; "
                              "precedente: 200_FIC_081 con CONTROL_NIVEL y variable F)"
                    % (variable, tipo, variable_aoi))
        return (variable, "morfema de la entrada -> %s (confirmado por AOI %s)" % (variable, tipo))
    if variable_aoi:
        return (variable_aoi, "tipo de AOI %s -> %s (la direccion fisica no aporta morfema)" % (tipo, variable_aoi))
    return ("", "variable no determinable (morfemas: %s / AOI: %s)" % (sorted(morfemas), tipo))


# ------------------------------------------------------------------ armado
def estado_crudo(fila: dict) -> str:
    """Estado del TRAZADO, no el post-filtro.

    Despues de correr src/corregir_propuesta_masiva.py, `Clasificacion` guarda el estado
    post-filtro y el crudo queda en `Clasificacion_Trazado`. Toda la logica de elegibilidad tiene
    que mirar el crudo, o el pipeline deja de ser idempotente (la segunda corrida veria solo los
    lazos ya propuestos y no detectaria extremos compartidos con los bloqueados).
    """
    return fila.get("Clasificacion_Trazado") or fila.get("Clasificacion") or ""


def analizar_elegibilidad(filas: list[dict]) -> tuple:
    """Devuelve (elegibles, bloqueos). Aplica los 4 criterios en orden."""
    cerrables = [f for f in filas if estado_crudo(f) == "CERRABLE_HOY"]
    cuenta_ent = Counter(f["Entrada_Fisica"] for f in cerrables)
    cuenta_sal = Counter(f["Salida_Fisica"] for f in cerrables if f["Salida_Fisica"])
    elegibles, bloqueos = [], []
    for fila in filas:
        ident = "%s/%s/%s" % (fila["PLC"], fila["Program"], fila["Instancia"])
        if estado_crudo(fila) != "CERRABLE_HOY":
            bloqueos.append({"Lazo": ident, "Clasificacion": estado_crudo(fila),
                             "Motivo": fila["Nota"]})
            continue
        if cuenta_ent[fila["Entrada_Fisica"]] > 1 or cuenta_sal[fila["Salida_Fisica"]] > 1:
            bloqueos.append({"Lazo": ident, "Clasificacion": "BLOQUEADO_EXTREMO_COMPARTIDO",
                             "Motivo": "extremo compartido con otro lazo: entrada '%s' en %d lazos, salida '%s' en %d"
                                       % (fila["Entrada_Fisica"], cuenta_ent[fila["Entrada_Fisica"]],
                                          fila["Salida_Fisica"], cuenta_sal[fila["Salida_Fisica"]])})
            continue
        area, criterio_area, confianza = area_del_lazo(fila)
        if not area:
            bloqueos.append({"Lazo": ident, "Clasificacion": "BLOQUEADO_AREA_AMBIGUA", "Motivo": criterio_area})
            continue
        variable, criterio_var = variable_del_lazo(fila)
        if not variable:
            bloqueos.append({"Lazo": ident, "Clasificacion": "BLOQUEADO_VARIABLE_AMBIGUA", "Motivo": criterio_var})
            continue
        elegibles.append({**fila, "Area": area, "Criterio_Area": criterio_area,
                          "Confianza_Area": confianza, "Variable_ISA": variable,
                          "Criterio_Variable": criterio_var, "Lazo": ident})
    elegibles.sort(key=lambda f: (f["Area"], f["PLC"], f["Program"], f["Instancia"]))
    return elegibles, bloqueos


def asignar(elegibles: list[dict], u: dict) -> list[dict]:
    """Asigna numero consecutivo libre por area y arma los 3 tags de cada lazo."""
    por_area = defaultdict(list)
    for fila in elegibles:
        por_area[fila["Area"]].append(fila)
    propuestos = []
    for area in sorted(por_area):
        lazos = por_area[area]
        usados_en_run = set()
        for fila in lazos:
            libres = [n for n in numeros_libres(area, u, len(lazos) + len(usados_en_run) + 5)
                      if n not in usados_en_run]
            numero = libres[0]
            usados_en_run.add(numero)
            variable = fila["Variable_ISA"]
            evidencias = {n: numero_ocupado(area, n, u) for n in (numero,)}
            base = {
                "Lazo": fila["Lazo"], "PLC": fila["PLC"], "Program": fila["Program"],
                "Routine": fila["Routine"], "Instancia_AOI": fila["Instancia"],
                "Tipo_AOI": fila["Tipo_AOI"], "Prioridad_Frontera": fila["Prioridad"],
                "Area": area, "Area_Criterio": fila["Criterio_Area"], "Area_Confianza": fila["Confianza_Area"],
                "Variable_ISA": variable, "Variable_Criterio": fila["Criterio_Variable"],
                "Numero_Propuesto": "%03d" % numero,
                "Numeros_Ocupados_Area_Resumen": formatear_rangos(
                    sorted({n for (a, n) in u["prod"] | u["hist"] if a == area} |
                           u["inventario"].get(area, set()) | u["docs"].get(area, set()))),
                "Numero_Libre_En": "U1_DB_produccion | U2_backup_693 | U3_inventario_online | U4_identificadores_L5X | U5_documentacion",
                "Clasificacion_Trazado": fila["Clasificacion"], "Nota_Trazado": fila["Nota"],
                "Estado_Propuesta": ESTADO, "Escritura_SQLite": "NO",
            }
            for rol, funcion, identidad, direccion in (
                ("ENTRADA", "T", fila["Entrada_Fisica"].split(" (")[0],
                 fila["Entrada_Fisica"].split("(")[-1].rstrip(")")),
                ("CONTROLADOR", "IC", fila["Instancia"], ""),
                ("SALIDA", "V", fila["Salida_Fisica"].split(" (")[0],
                 fila["Salida_Fisica"].split("(")[-1].rstrip(")")),
            ):
                # Si la traza termina en un canal crudo del módulo se conserva `CANAL_CRUDO:`;
                # el corrector v3 completa luego la aclaración de que no existe tag de campo.
                if rol == "ENTRADA" and ":" in identidad:
                    migrado = "CANAL_CRUDO:%s" % identidad
                else:
                    migrado = identidad
                propuestos.append({
                    **base, "Rol": rol, "Funcion_ISA": funcion,
                    "Tag_Propuesto": "%s_%s%s_%03d" % (area, variable, funcion, numero),
                    "Migrado_De": migrado,
                    "AliasFor_Direccion_Fisica": direccion,
                    "Camino_XML": fila["Entrada_Camino"][:300],
                    "Pin_Salida": fila["Pin_Salida"] if rol == "SALIDA" else "",
                })
    return propuestos


def colisiones_con_aprobados(propuestos: list[dict], u: dict) -> list:
    problemas = []
    for p in propuestos:
        if p["Tag_Propuesto"] in u["prod_tags"]:
            problemas.append("%s ya existe en la base" % p["Tag_Propuesto"])
        if (p["Area"], int(p["Numero_Propuesto"])) in u["prod"]:
            problemas.append("%s: el numero %s ya esta usado en el area %s por un tag de produccion"
                             % (p["Tag_Propuesto"], p["Numero_Propuesto"], p["Area"]))
    return problemas


def modo_v4(activo: bool = True) -> dict:
    """Redirige la salida a los nombres del sprint de frontera v4, SIN tocar los canonicos.

    El canonico documenta lo ya insertado en la base; el v4 es una propuesta NUEVA que se escribe
    aparte, con su propio analisis de frontera.
    """
    global ANALISIS, SALIDA, RESUMEN, BLOQUEOS
    if activo:
        ANALISIS = RAIZ / "exports" / "analisis_210_lazos_v4.csv"
        SALIDA = RAIZ / "exports" / "propuesta_numeracion_masiva_v4_210926_v1.csv"
        RESUMEN = RAIZ / "exports" / "resumen_propuesta_masiva_v4_210926.csv"
        BLOQUEOS = RAIZ / "exports" / "bloqueos_propuesta_masiva_v4_210926.csv"
    return {"ANALISIS": ANALISIS, "SALIDA": SALIDA, "RESUMEN": RESUMEN, "BLOQUEOS": BLOQUEOS}


def escribir(propuestos, resumen, bloqueos) -> tuple:
    columnas = ["Lazo", "PLC", "Program", "Routine", "Instancia_AOI", "Tipo_AOI", "Prioridad_Frontera",
                "Rol", "Area", "Variable_ISA", "Funcion_ISA", "Numero_Propuesto", "Tag_Propuesto",
                "Migrado_De", "AliasFor_Direccion_Fisica", "Pin_Salida",
                "Area_Criterio", "Area_Confianza", "Variable_Criterio",
                "Numeros_Ocupados_Area_Resumen", "Numero_Libre_En", "Clasificacion_Trazado",
                "Nota_Trazado", "Camino_XML", "Estado_Propuesta", "Escritura_SQLite"]
    with open(SALIDA, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=";", lineterminator="\n")
        w.writeheader()
        for p in propuestos:
            w.writerow({c: p.get(c, "") for c in columnas})
    with open(RESUMEN, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Area", "Variable_ISA", "Lazos", "Tags_Propuestos", "Numeros"],
                           delimiter=";", lineterminator="\n")
        w.writeheader()
        for clave in sorted(resumen):
            fila = resumen[clave]
            w.writerow({"Area": clave[0], "Variable_ISA": clave[1], "Lazos": fila["lazos"],
                        "Tags_Propuestos": fila["tags"], "Numeros": "|".join(fila["numeros"])})
    with open(BLOQUEOS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Lazo", "Clasificacion", "Motivo"], delimiter=";", lineterminator="\n")
        w.writeheader()
        for b in bloqueos:
            w.writerow(b)
    return SALIDA, RESUMEN, BLOQUEOS


def main(snapshot_db: Path = SNAPSHOT_OCUPACION) -> int:
    ruta = ANALISIS if ANALISIS.exists() else ANALISIS_40
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    print("Trazados leidos: %d (%s)" % (len(filas), ruta.name))
    u = cargar_universos(snapshot_db)
    print("Snapshot U1: %s" % snapshot_db)
    print("Universos: DB produccion %d pares | backup 693 %d pares | inventarios %s | L5X %d numeros | docs %s"
          % (len(u["prod"]), len(u["hist"]), {k: len(v) for k, v in u["inventario"].items()},
             len(u["l5x"]), {k: len(v) for k, v in u["docs"].items()}))

    elegibles, bloqueos = analizar_elegibilidad(filas)
    propuestos = asignar(elegibles, u)
    problemas = colisiones_con_aprobados(propuestos, u)

    resumen = OrderedDict()
    for p in propuestos:
        clave = (p["Area"], p["Variable_ISA"])
        fila = resumen.setdefault(clave, {"lazos": 0, "tags": 0, "numeros": []})
        fila["tags"] += 1
        if p["Rol"] == "ENTRADA":
            fila["lazos"] += 1
            fila["numeros"].append(p["Numero_Propuesto"])
    for fila in resumen.values():
        fila["numeros"] = sorted(set(fila["numeros"]))

    rutas = escribir(propuestos, resumen, bloqueos)
    print()
    print("=== PROPUESTA MASIVA ===")
    print("  lazos elegibles   : %d" % len(elegibles))
    print("  tags propuestos   : %d" % len(propuestos))
    print("  bloqueos restantes: %d" % len(bloqueos))
    print("  colisiones con los 9 aprobados o con produccion: %s" % (problemas or "NINGUNA"))
    print()
    for (area, variable), fila in sorted(resumen.items()):
        print("   area %s var %s -> %d lazos | numeros %s" % (area, variable, fila["lazos"], ",".join(fila["numeros"])))
    print()
    for clase, n in sorted(Counter(b["Clasificacion"] for b in bloqueos).items()):
        print("   bloqueo %-34s %d" % (clase, n))
    for ruta in rutas:
        print("[OK] %s" % ruta)
    return 0


if __name__ == "__main__":
    if "--v4" in sys.argv:
        modo_v4(True)
    sys.exit(main())
