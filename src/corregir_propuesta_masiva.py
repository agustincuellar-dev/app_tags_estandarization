"""Pase de correccion determinista sobre la propuesta masiva (R1..R7).

NO re-traza wires: usa los caminos XML ya validados en exports/analisis_210_lazos.csv. Solo
consulta el TIPO de tag (`<Tag TagType=... AliasFor=...>`) en el L5X para saber si la identidad
que alimenta PV es un tag REAL interno o un alias; eso no es re-trazar.

REGLAS APLICADAS
----------------
R1 Variable = morfema ISA del TAG REAL INTERNO que alimenta PV (precedente 200_FIC_081: el
   morfema manda sobre el nombre generico del AOI). Se recae en el tipo de AOI SOLO si la entrada
   es canal crudo sin tag interno. Si ni morfema ni AOI determinan variable:
   BLOQUEADO_VARIABLE_AMBIGUA y la fila queda fuera de la propuesta.
R2 Funcion de SALIDA = XV si el pin es MV_VALV_NC / MV_VALV_NA (todo/nada); V si el pin es MV
   (modulante). Si el elemento final es un arrancador de motor (Slot_IS_MOTOR_*, IS_BBA_*, SI_BB_*)
   el lazo sale de la propuesta y va a REVISION_ELEMENTO_FINAL, sin numerar.
R3 `Migrado_De` de ENTRADA = tag REAL interno que alimenta PV. Si el PV recibe el canal fisico
   directo: `CANAL_CRUDO:<direccion>` + nota. Se elimina la etiqueta "SIN TAG PLC" cuando existe
   tag interno en el camino.
R4 Se agregan Descripcion_Propuesta, Fluido_Proceso, Tipo_Senal, Entrada_Salida_BD y DataType_BD,
   generadas de forma determinista desde la identidad del lazo.
R5 Renumeracion por area + variable corregida, re-verificando libertad en los 5 universos
   (DB de produccion, backup 693, inventarios online, identificadores ISA-like del L5X,
   numeros citados en docs/). El numero sigue siendo compartido por lazo.
R6 La evidencia de ocupacion cubre ahora las areas 100, 200, 300, 500, 600 y 700
   (src/identificadores_vigentes.py extendido, con prefijo por area en el PLC multi-area FABRICA).
R7 analisis_210_lazos.csv se re-etiqueta: `Clasificacion` pasa a ser el estado POST-FILTRO y el
   estado crudo del trazador queda en `Clasificacion_Trazado`, con `Motivo_PostFiltro`.
R8 Tipo_Senal = Digital para las salidas con pin MV_VALV_NC / MV_VALV_NA (todo/nada) y Analogico
   para las salidas con pin MV y para entradas y controladores.
DECISION A Las salidas todo/nada mantienen la convencion de casa area+variable+funcion con funcion
   XV (`500_LXV_088`, `700_PXV_008`, `200_FXV_087`); XV pelado queda reservado a valvulas de corte
   fuera de lazo. Se registra en la columna `Nota_Convencion`.
DECISION B Las salidas cuyo extremo es una direccion fisica cruda pasan a
   `Migrado_De = CANAL_CRUDO:<direccion>`, la direccion queda tambien en
   `AliasFor_Direccion_Fisica` y se emite exports/salidas_canal_crudo_pendientes.csv como backlog
   de limpieza pre-paro (sin alias no hay nada que renombrar en Studio 5000).

ARTEFACTOS
----------
Entradas : exports/propuesta_numeracion_masiva_180926_v1.csv (salida del generador) y
           exports/analisis_210_lazos.csv.
Salidas  : exports/propuesta_numeracion_masiva_180926.csv (v3 vigente) + _v2.csv (v2 resguardada),
           diff v1->v2 y v2->v3, resumen, bloqueos, revision_elemento_final y backlog de canal crudo.

OJO: volver a correr el trazador regenera analisis_210_lazos.csv y borra las columnas post-filtro;
hay que volver a correr este modulo despues.

Solo lectura sobre SQLite. Nada se inserta.
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

from generar_propuesta_masiva import (  # noqa: E402
    AOI_A_VARIABLE, AREA_POR_PREFIJO, BACKUP_693, DB_PRODUCCION, DIR_L5X,
    cargar_universos, numero_ocupado, numeros_libres,
)
from trazador_lazos_profundo import RE_ATRIB, RE_TAG, L5X  # noqa: E402

ANALISIS = RAIZ / "exports" / "analisis_210_lazos.csv"
V1 = RAIZ / "exports" / "propuesta_numeracion_masiva_180926_v1.csv"
V2 = RAIZ / "exports" / "propuesta_numeracion_masiva_180926.csv"
V2_PRESERVADA = RAIZ / "exports" / "propuesta_numeracion_masiva_180926_v2.csv"
DIFF = RAIZ / "exports" / "diff_propuesta_masiva_v1_v2.csv"
DIFF_V2_V3 = RAIZ / "exports" / "diff_propuesta_masiva_v2_v3.csv"
RESUMEN = RAIZ / "exports" / "resumen_propuesta_masiva_180926.csv"
BLOQUEOS = RAIZ / "exports" / "bloqueos_propuesta_masiva_180926.csv"
REVISION_FINAL = RAIZ / "exports" / "revision_elemento_final_180926.csv"
CANAL_CRUDO_PENDIENTES = RAIZ / "exports" / "salidas_canal_crudo_pendientes.csv"
# La numeracion de una propuesta APROBADA E INSERTADA no se recalcula nunca: se congela aqui.
# Motivo (21/09): los universos de ocupacion incluyen la documentacion (U5) y cualquier informe,
# handoff o nota nueva que cite un candidato lo convertia en "ocupado" y renumeraba el entregable,
# desalineandolo de la base. La busqueda de libres queda solo como verificacion para numeros nuevos.
NUMERACION_CONGELADA = RAIZ / "exports" / "numeracion_congelada_180926.csv"

AREA_NOMBRE = {
    "000": "Recepción y Preparación de Caña", "100": "Molienda", "200": "Destilería",
    "250": "Biodestilería", "300": "Calderas / Generación de Vapor", "400": "Clarificación y Encalado",
    "500": "Evaporación", "600": "Cocimiento / Tachos", "700": "Centrifugado / Purga",
    "800": "Secado y Envase", "900": "Fuerza Motriz / Turbogeneradores", "950": "Tratamiento de Agua y Servicios",
}
MORFEMA_A_VARIABLE = {
    "PT": "P", "TT": "T", "LT": "L", "FT": "F", "AIT": "A", "AT": "A", "DT": "D", "WT": "W",
    "ST": "S", "PIT": "P", "LIT": "L", "TIT": "T", "CT": "C", "ZT": "Z", "QT": "Q",
}
# Elemento final que NO es valvula: arrancador de motor / bomba -> REVISION_ELEMENTO_FINAL (R2)
PATRON_ARRANCADOR = ("SLOT_IS_MOTOR", "IS_BBA", "SI_BB", "VDF_", "ARRANQUE", "_BBA_", "MOTOR")
FLUIDO_POR_CLAVE = OrderedDict([
    ("VAP", "Vapor"), ("ESCAPE", "Vapor de escape"), ("COND", "Condensado"), ("JUGO", "Jugo"),
    ("MELAZA", "Melaza"), ("MELADO", "Melado"), ("MOSTO", "Mosto"), ("AGUA", "Agua"),
    ("VINO", "Vino"), ("ALCOHOL", "Alcohol"), ("LECHADA", "Lechada"), ("VINAZA", "Vinaza"),
    ("MIEL", "Miel"), ("INMIBICION", "Agua de imbibición"), ("MESA", "Caña / mesa de molienda"),
    ("CAL", "Cal"), ("VAPOR", "Vapor"),
])
TIPO_SEÑAL = "Analógico"          # entradas y controladores: el lazo se traza sobre REAL
TIPO_SEÑAL_DIGITAL = "Digital"    # R8: salidas todo/nada (pin MV_VALV_NC / MV_VALV_NA)
NOTA_CONVENCION_XV = ("DECISION A: funcion XV con la convencion de casa area+variable+funcion "
                      "(700_PXV_008). XV pelado queda reservado a valvulas de corte fuera de lazo.")
NOTA_SALIDA_CANAL_CRUDO = ("DECISION B: la salida escribe el canal fisico directo (sin alias de "
                           "campo); no hay tag que renombrar en Studio 5000. Backlog de limpieza "
                           "en exports/salidas_canal_crudo_pendientes.csv.")
ESTADO = "PROPUESTA_CONCRETA_PARA_REVISION — NO_INSERTAR"
ESTADO_REVISION = "REVISION_ELEMENTO_FINAL — NO_NUMERAR_SIN_AUTORIZACION"


# --------------------------------------------------------------- utilidades
def leer_csv(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def escribir_csv(ruta: Path, filas: list[dict], columnas: list[str]) -> Path:
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=";", lineterminator="\n")
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c, "") for c in columnas})
    return ruta


def clasificar(operando: str) -> tuple:
    return L5X.clasificar_operando(operando)


def tag_de_operando(operando: str) -> str:
    """'\\FAB_ESCALADOS.CCV_PT_10_5BAR' -> 'CCV_PT_10_5BAR'; direccion -> ''."""
    return L5X.nombre_tag(operando)


def morfema_de(nombre: str) -> str:
    """Primer morfema ISA presente en el nombre ('CCV_PT_10_5BAR' -> 'PT')."""
    for token in nombre.lstrip("\\").replace(".", "_").split("_"):
        if token in MORFEMA_A_VARIABLE:
            return token
    return ""


def variable_por_morfema(nombre: str) -> str:
    return MORFEMA_A_VARIABLE.get(morfema_de(nombre), "")


def es_arrancador(texto: str) -> bool:
    t = (texto or "").upper()
    return any(p in t for p in PATRON_ARRANCADOR)


def es_direccion_cruda(texto: str) -> bool:
    """True si el texto es una direccion fisica de modulo (no un tag del PLC)."""
    return clasificar((texto or "").strip())[0] == "DIRECCION"


def partes_direccion(direccion: str) -> tuple:
    """'jw_fermerntacion_2022:11:O.Ch7Data' -> ('jw_fermerntacion_2022', '11', 'O')."""
    partes = (direccion or "").split(":")
    if len(partes) < 3:
        return (direccion or "", "", "")
    return (partes[0], partes[1], partes[2].split(".")[0])


def fluido_de(texto: str) -> str:
    t = (texto or "").upper()
    for clave, valor in FLUIDO_POR_CLAVE.items():
        if clave in t:
            return valor
    return "No determinado en la identidad del lazo"


def tipos_de_tags(plcs) -> dict:
    """{plc: {tag: (TagType, AliasFor)}} leyendo SOLO los elementos <Tag> (no re-traza)."""
    salida = {}
    for plc in sorted(set(plcs)):
        ruta = DIR_L5X / ("%s.L5X" % plc)
        if not ruta.exists():
            salida[plc] = {}
            continue
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        mapa = {}
        for m in RE_TAG.finditer(texto):
            a = dict(RE_ATRIB.findall(m.group(2)))
            mapa[m.group(1)] = (a.get("TagType", ""), (a.get("AliasFor") or "").strip())
        salida[plc] = mapa
    return salida


def nombre_variables() -> dict:
    with closing(sqlite3.connect(DB_PRODUCCION.resolve().as_uri() + "?mode=ro", uri=True)) as c:
        c.execute("PRAGMA query_only=ON")
        return {f[0]: f[1] for f in c.execute("SELECT letra, nombre FROM variables")}


def nombre_funciones() -> dict:
    with closing(sqlite3.connect(DB_PRODUCCION.resolve().as_uri() + "?mode=ro", uri=True)) as c:
        c.execute("PRAGMA query_only=ON")
        return {f[0]: f[1] for f in c.execute("SELECT letra, nombre FROM funciones")}


# --------------------------------------------------------------- R3 y R4
def identidad_entrada(fila: dict, tags: dict) -> tuple:
    """(Migrado_De, AliasFor, Nota) aplicando R3."""
    operando = (fila.get("Entrada_Operando") or "").strip()
    tipo, valor, programa = clasificar(operando)
    if tipo == "DIRECCION":
        return ("CANAL_CRUDO:%s" % valor, valor,
                "El pin PV recibe el canal fisico directo: no existe tag interno en el camino XML.")
    if tipo in ("TAG", "CRUZADO"):
        tag = valor
        tag_tipo, alias_for = tags.get(tag, ("", ""))
        nota = ""
        if tag_tipo == "Alias":
            nota = ("El pin PV recibe directamente el alias de campo '%s' (AliasFor %s): no hay tag "
                    "interno REAL en el camino." % (tag, alias_for or "sin AliasFor"))
            return (tag, alias_for, nota)
        if programa:
            nota = "Tag REAL interno declarado en el programa %s." % programa
        return (tag, "", nota)
    return ("", "", "El pin PV no tiene operando clasificable: %s" % (operando or "(vacio)"))


def texto_procedencia(identidad: str, es_salida: bool = False) -> str:
    """Procedencia visible y auditable; la aclaracion de canal directo aplica a salidas."""
    identidad = identidad or "(sin identidad)"
    texto = "Migrado de: %s" % identidad
    if es_salida and identidad.startswith("CANAL_CRUDO:"):
        texto += " (sin tag de campo en el PLC: la salida escribe directo al canal)"
    return texto


def describir(rol: str, variable: str, area: str, instancia: str, identidad: str,
              rutina: str, funcion: str, variables: dict) -> str:
    """Descripcion determinista con lectura, procedencia, rutina y area (formato de produccion)."""
    var_nombre = variables.get(variable, variable)
    if rol == "ENTRADA":
        lectura = "Transmisor de %s" % var_nombre.lower()
    elif rol == "CONTROLADOR":
        lectura = "Controlador indicador de %s" % var_nombre.lower()
    else:
        clase = "Válvula todo/nada" if funcion == "XV" else "Válvula de control"
        lectura = "%s de %s" % (clase, var_nombre.lower())
    nombre_area = AREA_NOMBRE.get(area, "") or "No determinada"
    return ("%s — lazo %s; %s; rutina %s; área %s (%s)"
            % (lectura, instancia, texto_procedencia(identidad, es_salida=(rol == "SALIDA")),
               rutina or "(sin rutina)", area, nombre_area))


def entrada_salida_bd(rol: str) -> str:
    return {"ENTRADA": "Entrada", "CONTROLADOR": "Memoria / Red", "SALIDA": "Salida"}.get(rol, "N/D")


# --------------------------------------------------------------- correccion
def ocupados_de_area(area: str, u: dict) -> str:
    """Resumen de numeros ocupados del area en los 5 universos, formateado en rangos."""
    from identificadores_vigentes import formatear_rangos
    numeros = {n for (a, n) in u["prod"] if a == area} | {n for (a, n) in u["hist"] if a == area}
    numeros |= set(u["inventario"].get(area, set())) | set(u["docs"].get(area, set()))
    return formatear_rangos(sorted(numeros))


def correcciones_por_lazo(v1, analisis, tags, variables, funciones) -> tuple:
    """Primera pasada: decide por lazo sin asignar numeros. Devuelve (decisiones, revision)."""
    indice = {(a["PLC"], a["Program"], a["Routine"], a["Instancia"]): a for a in analisis}
    por_lazo = OrderedDict()
    for fila in v1:
        clave = (fila["PLC"], fila["Program"], fila["Routine"], fila["Instancia_AOI"])
        por_lazo.setdefault(clave, []).append(fila)

    decisiones, revision = OrderedDict(), []
    for clave in sorted(por_lazo):
        grupo = por_lazo[clave]
        a = indice.get(clave, {})
        entrada_operando = a.get("Entrada_Operando", "")
        tipo_op, valor_op, prog_op = clasificar(entrada_operando)
        pin = (a.get("Pin_Salida") or grupo[0].get("Pin_Salida") or "").strip()
        area = grupo[0]["Area"]
        identidad_salida = grupo[-1].get("Migrado_De", "") if grupo[-1]["Rol"] == "SALIDA" else ""
        alias_salida = grupo[-1].get("AliasFor_Direccion_Fisica", "") if grupo[-1]["Rol"] == "SALIDA" else ""

        # --- R2: arrancador de motor -> REVISION_ELEMENTO_FINAL, sin numerar ---
        if grupo[-1]["Rol"] == "SALIDA" and es_arrancador(identidad_salida + " " + alias_salida):
            decisiones[clave] = {"propuesta": False, "estado": "REVISION_ELEMENTO_FINAL",
                                 "motivo": "el elemento final es un arrancador/bomba (%s), no una valvula de control"
                                           % identidad_salida}
            for f in grupo:
                revision.append({
                    "Lazo": f["Lazo"], "PLC": f["PLC"], "Program": f["Program"], "Routine": f["Routine"],
                    "Instancia_AOI": f["Instancia_AOI"], "Rol": f["Rol"], "Area": area,
                    "Variable_ISA": variable_por_morfema(valor_op) if tipo_op in ("TAG", "CRUZADO") else "",
                    "Propuesta_Funcion": ("Y (elemento final no valvula) o tag de bomba propio"
                                          if f["Rol"] == "SALIDA" else "se numeraria con el mismo lazo"),
                    "Elemento_Final_Actual": identidad_salida,
                    "AliasFor_Direccion_Fisica": alias_salida, "Pin_Salida": pin,
                    "Motivo": "R2: el pin %s comanda un arrancador/bomba (%s); no se numera sin definir "
                              "el elemento final." % (pin or "(sin pin)", identidad_salida),
                    "Estado_Propuesta": ESTADO_REVISION, "Escritura_SQLite": "NO",
                })
            continue

        # --- R1: variable = morfema del tag interno que alimenta PV ---
        morfema = morfema_de(valor_op) if tipo_op in ("TAG", "CRUZADO") else ""
        variable = MORFEMA_A_VARIABLE.get(morfema, "")
        if variable:
            criterio = "morfema '%s' del tag que alimenta PV (%s)" % (morfema, valor_op)
        else:
            v_aoi = next((v for k, v in AOI_A_VARIABLE.items() if grupo[0]["Tipo_AOI"].startswith(k)), None)
            if v_aoi and tipo_op == "DIRECCION":
                variable, criterio = v_aoi, "sin tag interno (canal crudo): tipo de AOI %s" % grupo[0]["Tipo_AOI"]
            else:
                decisiones[clave] = {
                    "propuesta": False, "estado": "BLOQUEADO_VARIABLE_AMBIGUA",
                    "motivo": "ni morfema en el tag que alimenta PV (%s) ni tipo de AOI reconocido (%s)"
                              % (entrada_operando or "(vacio)", grupo[0]["Tipo_AOI"])}
                continue

        # --- R3 ---
        migrado_ent, alias_ent, nota_ent = identidad_entrada({"Entrada_Operando": entrada_operando}, tags)
        funcion_salida = "XV" if pin in ("MV_VALV_NC", "MV_VALV_NA") else "V"
        if funcion_salida not in funciones or "IC" not in funciones or "T" not in funciones:
            raise SystemExit("Funcion ISA faltante en el catalogo de la base (XV/IC/T): revise catalogo")
        decisiones[clave] = {
            "propuesta": True, "area": area, "variable": variable, "criterio": criterio,
            "pin": pin, "funcion_salida": funcion_salida,
            "migrado_ent": migrado_ent, "alias_ent": alias_ent, "nota_ent": nota_ent,
            "identidad_salida": identidad_salida, "alias_salida": alias_salida,
            "estado": "CERRABLE_HOY", "motivo": "", "grupo": grupo, "instancia": grupo[0]["Instancia_AOI"],
        }
    return decisiones, revision


# --------------------------------------------------------------- numeracion congelada
def modo_v4(activo: bool = True) -> dict:
    """Redirige los artefactos del pase a los nombres del sprint v4, sin tocar los canonicos.

    En v4 el diff de la entrega es v3 -> v4, asi que la version "preservada" pasa a ser el CSV
    canonico (lo ya insertado en la base).
    """
    global ANALISIS, V1, V2, V2_PRESERVADA, DIFF, DIFF_V2_V3, RESUMEN, BLOQUEOS, REVISION_FINAL
    global CANAL_CRUDO_PENDIENTES
    if activo:
        ANALISIS = RAIZ / "exports" / "analisis_210_lazos_v4.csv"
        V1 = RAIZ / "exports" / "propuesta_numeracion_masiva_v4_210926_v1.csv"
        V2 = RAIZ / "exports" / "propuesta_numeracion_masiva_v4_210926.csv"
        V2_PRESERVADA = RAIZ / "exports" / "propuesta_numeracion_masiva_180926.csv"
        DIFF = RAIZ / "exports" / "diff_propuesta_masiva_v4_v1_v4.csv"
        DIFF_V2_V3 = RAIZ / "exports" / "diff_propuesta_masiva_v3_v4.csv"
        RESUMEN = RAIZ / "exports" / "resumen_propuesta_masiva_v4_210926.csv"
        BLOQUEOS = RAIZ / "exports" / "bloqueos_propuesta_masiva_v4_210926.csv"
        REVISION_FINAL = RAIZ / "exports" / "revision_elemento_final_v4_210926.csv"
        CANAL_CRUDO_PENDIENTES = RAIZ / "exports" / "salidas_canal_crudo_pendientes_v4.csv"
    return {"ANALISIS": ANALISIS, "V1": V1, "V2": V2, "V2_PRESERVADA": V2_PRESERVADA,
            "DIFF_V2_V3": DIFF_V2_V3, "RESUMEN": RESUMEN, "BLOQUEOS": BLOQUEOS,
            "REVISION_FINAL": REVISION_FINAL}


def cargar_numeracion_congelada() -> dict:
    """{(PLC, Program, Routine, Instancia): numero} de la linea base aprobada e insertada."""
    if not NUMERACION_CONGELADA.exists():
        return {}
    with open(NUMERACION_CONGELADA, encoding="utf-8-sig", newline="") as f:
        return {(f["PLC"], f["Program"], f["Routine"], f["Instancia"]): int(f["Numero"])
                for f in csv.DictReader(f, delimiter=";")}


def escribir_numeracion_congelada(filas: list[dict]) -> Path:
    """Congela la numeracion de una propuesta ya aprobada, un lazo por fila (idempotente)."""
    columnas = ["Lazo", "PLC", "Program", "Routine", "Instancia", "Area", "Variable_ISA",
                "Funcion_Salida", "Numero", "Tag_Entrada", "Tag_Controlador", "Tag_Salida"]
    por_lazo = OrderedDict()
    for f in filas:
        clave = (f["PLC"], f["Program"], f["Routine"], f["Instancia_AOI"])
        por_lazo.setdefault(clave, {})[f["Rol"]] = f
    with open(NUMERACION_CONGELADA, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas, delimiter=";", lineterminator="\n")
        w.writeheader()
        for clave in sorted(por_lazo):
            roles = por_lazo[clave]
            w.writerow({
                "Lazo": roles["ENTRADA"]["Lazo"], "PLC": clave[0], "Program": clave[1],
                "Routine": clave[2], "Instancia": clave[3], "Area": roles["ENTRADA"]["Area"],
                "Variable_ISA": roles["ENTRADA"]["Variable_ISA"],
                "Funcion_Salida": roles["SALIDA"]["Funcion_ISA"],
                "Numero": int(roles["ENTRADA"]["Numero_Propuesto"]),
                "Tag_Entrada": roles["ENTRADA"]["Tag_Propuesto"],
                "Tag_Controlador": roles["CONTROLADOR"]["Tag_Propuesto"],
                "Tag_Salida": roles["SALIDA"]["Tag_Propuesto"],
            })
    return NUMERACION_CONGELADA


def corregir(v1, analisis, u: dict, tags: dict, variables: dict, funciones: dict,
             estados_base: dict) -> tuple:
    """Devuelve (filas_v2, revision_elemento_final, estados_post_filtro)."""
    decisiones, revision = correcciones_por_lazo(v1, analisis, tags, variables, funciones)
    estados = dict(estados_base)          # decisiones del generador (compartido/area/variable)
    for clave, d in decisiones.items():
        estados[clave] = (d["estado"], d["motivo"])

    # R5: numerar siguiendo el orden (area, variable, identidad del lazo) — los lazos de la misma
    # variable dentro de un area quedan con numeros consecutivos.
    elegibles = [c for c, d in decisiones.items() if d["propuesta"]]
    elegibles.sort(key=lambda c: (decisiones[c]["area"], decisiones[c]["variable"], c))
    congelada = cargar_numeracion_congelada()
    usados = defaultdict(set)
    filas_v2 = []
    for clave in elegibles:
        d = decisiones[clave]
        area, variable = d["area"], d["variable"]
        # La numeracion de un lazo ya aprobado e insertado se toma de la linea base congelada; solo
        # un lazo nuevo (sin numero congelado) busca el primer libre en los universos.
        numero = congelada.get(clave)
        if numero is None:
            numero = next(n for n in numeros_libres(area, u, 999) if n not in usados[area])
        usados[area].add(numero)
        for f in d["grupo"]:
            f = dict(f)
            f["Variable_ISA"] = variable
            f["Variable_Criterio"] = d["criterio"]
            f["Funcion_ISA"] = {"ENTRADA": "T", "CONTROLADOR": "IC", "SALIDA": d["funcion_salida"]}[f["Rol"]]
            f["Numero_Propuesto"] = "%03d" % numero
            f["Tag_Propuesto"] = "%s_%s%s_%03d" % (area, variable, f["Funcion_ISA"], numero)
            # DECISION B: salida con direccion cruda -> CANAL_CRUDO:<dir>; la direccion queda
            # tambien en AliasFor_Direccion_Fisica (mas abajo) y en el backlog de limpieza.
            identidad = {"ENTRADA": d["migrado_ent"], "CONTROLADOR": d["instancia"],
                         "SALIDA": d["identidad_salida"]}[f["Rol"]]
            crudo_salida = f["Rol"] == "SALIDA" and es_direccion_cruda(identidad)
            if crudo_salida:
                identidad = "CANAL_CRUDO:%s" % identidad
            f["Migrado_De"] = identidad
            if f["Rol"] == "ENTRADA":
                f["Nota_Migrado_De"] = d["nota_ent"]
            elif crudo_salida:
                f["Nota_Migrado_De"] = NOTA_SALIDA_CANAL_CRUDO
            else:
                f["Nota_Migrado_De"] = ""
            f["AliasFor_Direccion_Fisica"] = {"ENTRADA": d["alias_ent"], "CONTROLADOR": "",
                                              "SALIDA": d["alias_salida"]}[f["Rol"]]
            f["Pin_Salida"] = d["pin"] if f["Rol"] == "SALIDA" else ""
            f["Entrada_Operando"] = ""     # se rellena al final, para las 3 filas del lazo
            f["Descripcion_Propuesta"] = describir(f["Rol"], variable, area, d["instancia"],
                                                   f["Migrado_De"], f["Routine"], f["Funcion_ISA"], variables)
            f["Fluido_Proceso"] = fluido_de("%s %s" % (d["migrado_ent"], d["instancia"]))
            # R8: solo las salidas todo/nada (pin MV_VALV_NC / MV_VALV_NA) son Digital
            if f["Rol"] == "SALIDA":
                f["Tipo_Senal"] = (TIPO_SEÑAL_DIGITAL if d["pin"] in ("MV_VALV_NC", "MV_VALV_NA")
                                   else TIPO_SEÑAL)
            else:
                f["Tipo_Senal"] = TIPO_SEÑAL
            f["Nota_Convencion"] = NOTA_CONVENCION_XV if f["Funcion_ISA"] == "XV" else ""
            f["Entrada_Salida_BD"] = entrada_salida_bd(f["Rol"])
            f["DataType_BD"] = "REAL"
            f["Numeros_Ocupados_Area_Resumen"] = ocupados_de_area(area, u)
            f["Estado_Propuesta"] = ESTADO
            f["Escritura_SQLite"] = "NO"
            # Entrada_Operando se propaga a las 3 filas del lazo para dejar la traza completa
            filas_v2.append(f)
        estados[clave] = ("CERRABLE_HOY", "propuesta con numero candidato %03d" % numero)
    # la entrada_operando viaja en la decision: se rellena en las filas ya construidas
    por_clave = defaultdict(list)
    for f in filas_v2:
        por_clave[(f["PLC"], f["Program"], f["Routine"], f["Instancia_AOI"])].append(f)
    for clave, filas in por_clave.items():
        operando = (next((a["Entrada_Operando"] for a in analisis
                          if (a["PLC"], a["Program"], a["Routine"], a["Instancia"]) == clave), "") or "")
        for f in filas:
            f["Entrada_Operando"] = operando
    return filas_v2, revision, estados


def reetiquetar_analisis(analisis: list[dict], estados: dict) -> list[dict]:
    """R7: `Clasificacion` = estado post-filtro; el crudo queda en `Clasificacion_Trazado`."""
    salida = []
    for fila in analisis:
        f = dict(fila)
        crudo = f.get("Clasificacion_Trazado") or f.get("Clasificacion", "")
        f["Clasificacion_Trazado"] = crudo
        clave = (f["PLC"], f["Program"], f["Routine"], f["Instancia"])
        post, motivo = estados.get(clave, (crudo, ""))
        f["Clasificacion"] = post
        f["Motivo_PostFiltro"] = motivo
        salida.append(f)
    return salida


def diff(v1: list[dict], v2: list[dict]) -> list[dict]:
    """Diff por columna y por tag propuesto (usa el indice de fila como ancla de lazo+rol)."""
    def indexar(filas):
        return OrderedDict(((f["Lazo"], f["Rol"]), f) for f in filas)
    a, b = indexar(v1), indexar(v2)
    filas = []
    for clave in sorted(set(a) | set(b)):
        fa, fb = a.get(clave), b.get(clave)
        if fa is None:
            filas.append({"Lazo": clave[0], "Rol": clave[1], "Columna": "(toda la fila)", "Tipo": "AGREGADA",
                          "Valor_V1": "", "Valor_V2": fb.get("Tag_Propuesto", "")})
            continue
        if fb is None:
            filas.append({"Lazo": clave[0], "Rol": clave[1], "Columna": "(toda la fila)", "Tipo": "QUITADA",
                          "Valor_V1": fa.get("Tag_Propuesto", ""), "Valor_V2": ""})
            continue
        for columna in sorted(set(fa) | set(fb)):
            va, vb = fa.get(columna, ""), fb.get(columna, "")
            if va != vb:
                tipo = "AGREGADA" if columna not in fa else ("QUITADA" if columna not in fb else "MODIFICADA")
                filas.append({"Lazo": clave[0], "Rol": clave[1], "Columna": columna, "Tipo": tipo,
                              "Valor_V1": va, "Valor_V2": vb})
    return filas


COLUMNAS_V2 = [
    "Lazo", "PLC", "Program", "Routine", "Instancia_AOI", "Tipo_AOI", "Prioridad_Frontera",
    "Rol", "Area", "Variable_ISA", "Funcion_ISA", "Numero_Propuesto", "Tag_Propuesto",
    "Migrado_De", "Nota_Migrado_De", "AliasFor_Direccion_Fisica", "Pin_Salida",
    "Descripcion_Propuesta", "Fluido_Proceso", "Tipo_Senal", "Entrada_Salida_BD", "DataType_BD",
    "Nota_Convencion", "Entrada_Operando", "Area_Criterio", "Area_Confianza", "Variable_Criterio",
    "Numeros_Ocupados_Area_Resumen", "Numero_Libre_En", "Clasificacion_Trazado", "Nota_Trazado",
    "Camino_XML", "Estado_Propuesta", "Escritura_SQLite",
]
COLUMNAS_REVISION = ["Lazo", "PLC", "Program", "Routine", "Instancia_AOI", "Rol", "Area", "Variable_ISA",
                     "Propuesta_Funcion", "Elemento_Final_Actual", "AliasFor_Direccion_Fisica",
                     "Pin_Salida", "Motivo", "Estado_Propuesta", "Escritura_SQLite"]
COLUMNAS_CANAL_CRUDO = ["Lazo", "Tag_Propuesto", "Rol", "Area", "Variable_ISA", "Funcion_ISA",
                        "Instancia_AOI", "PLC", "Program", "Routine", "Direccion_Cruda", "Modulo",
                        "Slot", "Tipo_Pin", "Pin_Salida", "Comentario_Mantenimiento"]
COLUMNAS_DIFF = ["Lazo", "Rol", "Columna", "Tipo", "Valor_V1", "Valor_V2"]


def backlog_canal_crudo(v2: list[dict]) -> list[dict]:
    """Salidas cuyo Migrado_De es CANAL_CRUDO:<dir> (DECISION B) — backlog de limpieza pre-paro."""
    filas = []
    for f in v2:
        if f["Rol"] != "SALIDA" or not f["Migrado_De"].startswith("CANAL_CRUDO:"):
            continue
        direccion = f["Migrado_De"].split("CANAL_CRUDO:", 1)[1]
        modulo, slot, tipo = partes_direccion(direccion)
        filas.append({
            "Lazo": f["Lazo"], "Tag_Propuesto": f["Tag_Propuesto"], "Rol": f["Rol"],
            "Area": f["Area"], "Variable_ISA": f["Variable_ISA"], "Funcion_ISA": f["Funcion_ISA"],
            "Instancia_AOI": f["Instancia_AOI"], "PLC": f["PLC"], "Program": f["Program"],
            "Routine": f["Routine"], "Direccion_Cruda": direccion, "Modulo": modulo, "Slot": slot,
            "Tipo_Pin": tipo, "Pin_Salida": f["Pin_Salida"],
            "Comentario_Mantenimiento": ("Sin alias de campo: la salida se escribe directo al canal %s. "
                                         "No hay tag que renombrar en Studio 5000; si se quiere alias, "
                                         "crearlo en el pre-paro." % direccion),
        })
    return filas


def main() -> int:
    if not V1.exists():
        raise SystemExit("Falta la v1 (%s): es la salida de src/generar_propuesta_masiva.py. "
                         "Corra ese modulo primero." % V1.name)
    if not V2_PRESERVADA.exists():
        print("[OJO] No existe %s: no se podra emitir el diff v2 -> v3." % V2_PRESERVADA.name)
    v1 = leer_csv(V1)
    analisis = leer_csv(ANALISIS)
    print("v1: %d filas | analisis: %d filas" % (len(v1), len(analisis)))

    u = cargar_universos()
    print("Universos: DB %d pares | backup693 %d | inventarios %s | L5X %d | docs %s"
          % (len(u["prod"]), len(u["hist"]), {k: len(v) for k, v in u["inventario"].items()},
             len(u["l5x"]), {k: len(v) for k, v in u["docs"].items()}))
    tags = tipos_de_tags([f["PLC"] for f in v1])
    variables, funciones = nombre_variables(), nombre_funciones()

    # Estado post-filtro base: las exclusiones del generador (extremo compartido, area, variable)
    # tienen que quedar reflejadas en el analisis y en los bloqueos, aunque el lazo no este en v1.
    import generar_propuesta_masiva as gpm
    _, bloqueos_generador = gpm.analizar_elegibilidad(analisis)
    estados_base = {}
    for b in bloqueos_generador:
        partes = b["Lazo"].split("/")
        if len(partes) != 3:
            continue
        plc, programa, instancia = partes
        for a in analisis:
            if (a["PLC"], a["Program"], a["Instancia"]) == (plc, programa, instancia):
                estados_base[(a["PLC"], a["Program"], a["Routine"], a["Instancia"])] = \
                    (b["Clasificacion"], b["Motivo"])
                break

    v2, revision, estados = corregir(v1, analisis, u, {t: v for plc in tags for t, v in tags[plc].items()},
                                     variables, funciones, estados_base)
    escribir_csv(V2, v2, COLUMNAS_V2)
    escribir_csv(REVISION_FINAL, revision, COLUMNAS_REVISION)

    resumen = OrderedDict()
    for f in v2:
        clave = (f["Area"], f["Variable_ISA"])
        fila = resumen.setdefault(clave, {"lazos": 0, "tags": 0, "numeros": []})
        fila["tags"] += 1
        if f["Rol"] == "ENTRADA":
            fila["lazos"] += 1
            fila["numeros"].append(f["Numero_Propuesto"])
    with open(RESUMEN, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["Area", "Variable_ISA", "Lazos", "Tags_Propuestos", "Numeros"],
                           delimiter=";", lineterminator="\n")
        w.writeheader()
        for (area, variable), r in sorted(resumen.items()):
            w.writerow({"Area": area, "Variable_ISA": variable, "Lazos": r["lazos"],
                        "Tags_Propuestos": r["tags"], "Numeros": "|".join(sorted(set(r["numeros"])))})

    lazos_v2 = {(f["Lazo"], f["Rol"]) for f in v2}
    bloqueos = []
    for fila in analisis:
        clave = (fila["PLC"], fila["Program"], fila["Routine"], fila["Instancia"])
        post, motivo = estados.get(clave, (fila["Clasificacion"], ""))
        if post != "CERRABLE_HOY":
            bloqueos.append({"Lazo": "%s/%s/%s" % (fila["PLC"], fila["Program"], fila["Instancia"]),
                             "Clasificacion": post, "Motivo": motivo or fila.get("Nota", "")})
    escribir_csv(BLOQUEOS, bloqueos, ["Lazo", "Clasificacion", "Motivo"])

    escribir_csv(ANALISIS, reetiquetar_analisis(analisis, estados),
                 list(dict.fromkeys(list(analisis[0].keys()) + ["Clasificacion_Trazado", "Motivo_PostFiltro"])))
    escribir_csv(DIFF, diff(v1, v2), COLUMNAS_DIFF)
    if V2_PRESERVADA.exists():
        escribir_csv(DIFF_V2_V3, diff(leer_csv(V2_PRESERVADA), v2), COLUMNAS_DIFF)
    pendientes = backlog_canal_crudo(v2)
    escribir_csv(CANAL_CRUDO_PENDIENTES, pendientes, COLUMNAS_CANAL_CRUDO)

    escrituras = {f["Escritura_SQLite"] for f in v2} | {f["Escritura_SQLite"] for f in revision}
    print()
    print("=== PROPUESTA MASIVA v3 (R1..R8 + decisiones A y B) ===")
    print("  lazos : %d | tags : %d" % (len({f['Lazo'] for f in v2}), len(v2)))
    print("  a REVISION_ELEMENTO_FINAL: %d filas (%d lazos)" % (len(revision), len({f['Lazo'] for f in revision})))
    for (area, variable), r in sorted(resumen.items()):
        print("   area %s var %s -> %d lazos | numeros %s" % (area, variable, r["lazos"],
                                                              ",".join(sorted(set(r["numeros"])))))
    print("  funciones de salida: %s" % dict(Counter(f["Funcion_ISA"] for f in v2 if f["Rol"] == "SALIDA")))
    print("  R8 Tipo_Senal: %s" % dict(Counter(f["Tipo_Senal"] for f in v2)))
    print("  DECISION B salidas CANAL_CRUDO: %d (backlog de limpieza)" % len(pendientes))
    print("  Escritura_SQLite en todas las filas: %s" % (escrituras or "vacio"))
    print()
    for clase, n in sorted(Counter(b["Clasificacion"] for b in bloqueos).items()):
        print("   bloqueo %-34s %d" % (clase, n))
    for ruta in (V2, RESUMEN, BLOQUEOS, REVISION_FINAL, DIFF, DIFF_V2_V3, CANAL_CRUDO_PENDIENTES):
        print("[OK] %s" % ruta)
    return 0


if __name__ == "__main__":
    if "--v4" in sys.argv:
        modo_v4(True)
    sys.exit(main())
