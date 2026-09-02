"""
auditar_masivo.py
=================
Auditor MASIVO para el volcado tabular de tags de TODA la planta
(~25.000 tags / ~27 PLCs del Ingenio La Florida).

A diferencia de `auditar_l5x.py` (que lee UN archivo .L5X con toda su
estructura XML: Program/Routine/Sheet/Wire/Alias), este script consume un
archivo TABULAR plano (CSV o XLSX) con una fila por tag. Reutiliza el mismo
motor de inteligencia de `auditar_l5x.py`:

    - Clasificacion normativa ISA-5.1        (base.clasificar)
    - Validaciones del diccionario ISA        (base.validar_reglas)
    - Mapeo corporativo a miembros de UDT      (base.transformar_interna_a_miembro)
    - Inferencia semantica por palabras clave  (base.area_por_palabras_clave)
    - Herencia de area por Scope (columna)     (base.area_por_nombre_contenedor)

LIMITACIONES en modo tabular (respecto al modo .L5X), por diseno y honestas:
    - NO hay trazado de cableado FBD: los bloques tipo SCL_NN sin nombre de
      instrumento en si mismos solo pueden enlazarse por coincidencia de
      nombre, no por el cable que los alimenta.
    - NO hay votacion por vecinos de rutina: la herencia de area por Scope
      se limita a la columna de Programa/Scope de cada fila (si existe).
    - FISICO_ISA (alias a I/O fisico) solo se detecta si el archivo trae una
      columna de Alias; una lista plana de NAME+DATATYPE no puede probar el
      aliasing fisico.

Salidas (misma limpieza que la fase piloto):
    25k_mapeo_exitoso.csv   -> tags resueltos con exito (ISA final o UDT)
    25k_sin_clasificar.csv  -> PENDIENTE/??? de cualquier clase (revision campo)

Uso:
    python auditar_masivo.py "inventario_tags.csv"
    python auditar_masivo.py "volcado_25k.xlsx"           (requiere openpyxl)
    python auditar_masivo.py "volcado_25k.xlsx" "Hoja2"   (hoja especifica)
"""

import sys
import os
import csv
from collections import defaultdict

import auditar_l5x as base  # reutiliza TODO el motor normativo/UDT/semantico

# Este script vive en <PROYECTO>/src/. Las salidas van a
# <PROYECTO>/resultados/ para no ensuciar el codigo fuente.
BASE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resultados")

# Nombres de columna aceptados (case-insensitive) para cada dato que
# necesita el motor. Se toma la primera que exista en el archivo.
COLS_NOMBRE     = ["NAME", "NOMBRE", "TAG", "TAG_VIEJO", "NOMBRE DE TAG", "TAGNAME"]
COLS_DATATYPE   = ["DATATYPE", "DATA TYPE", "TIPO", "TIPO DE DATO", "DATA_TYPE"]
COLS_DESCRIPCION = ["DESCRIPTION", "DESCRIPCION", "DESC", "COMENTARIO"]
COLS_SCOPE      = ["SCOPE", "ALCANCE", "PROGRAMA", "NOMBRE DE PROGRAMA", "PROGRAM"]
COLS_TAGTYPE    = ["TAGTYPE", "TIPO DE TAG"]
COLS_ALIASFOR   = ["ALIASFOR", "ALIAS FOR", "ALIAS", "ALIAS_DE"]
COLS_RECORDTYPE = ["TYPE"]   # RSLogix CSV: TAG / TEXTBOX / COMMENT ...
COLS_PLC        = ["PLC", "PLC (PATH)", "IP", "CONTROLADOR", "CONTROLLER"]


# ------------------------------------------------------------------
# Carga del archivo tabular (CSV con sniffing de delimitador/preambulo,
# o XLSX via pandas). Devuelve (lista_de_dicts, mapa_de_columnas).
# ------------------------------------------------------------------
def _norm(s):
    return (s or "").strip().strip('"').upper()


def _detectar_columna(headers, candidatas):
    """Devuelve el nombre REAL de columna del archivo que corresponde a la
    primera candidata que matchee (comparando en mayusculas), o None."""
    hdr_norm = {_norm(h): h for h in headers}
    for c in candidatas:
        if c in hdr_norm:
            return hdr_norm[c]
    return None


def cargar_csv(path):
    """Lee un CSV detectando delimitador y saltando lineas de preambulo
    (ej. las cabeceras 'remark' de los export de RSLogix). Encuentra la
    fila de header como la primera que contenga una columna de nombre."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        lineas = f.readlines()

    delim_candidatos = [";", ",", "\t"]
    idx_header, delim_ok, headers = None, None, None
    for i, linea in enumerate(lineas):
        for d in delim_candidatos:
            celdas = [_norm(c) for c in linea.rstrip("\n").split(d)]
            if any(c in COLS_NOMBRE for c in celdas):
                idx_header, delim_ok, headers = i, d, linea.rstrip("\n").split(d)
                break
        if idx_header is not None:
            break
    if idx_header is None:
        raise ValueError(
            "No se encontro una columna de nombre de tag "
            f"(se buscaron: {COLS_NOMBRE}). Revise el archivo."
        )

    headers = [h.strip().strip('"') for h in headers]
    filas = []
    reader = csv.reader(lineas[idx_header + 1:], delimiter=delim_ok)
    for celdas in reader:
        if not celdas or all(c.strip() == "" for c in celdas):
            continue
        fila = {}
        for j, h in enumerate(headers):
            fila[h] = celdas[j].strip().strip('"') if j < len(celdas) else ""
        filas.append(fila)
    return filas, headers


def cargar_xlsx(path, hoja=None):
    """Lee un XLSX via pandas (requiere openpyxl instalado)."""
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("Para leer XLSX se necesita pandas. Instale: pip install pandas openpyxl")
    try:
        df = pd.read_excel(path, sheet_name=(hoja if hoja else 0), dtype=str)
    except ImportError:
        raise RuntimeError("Para leer XLSX se necesita openpyxl. Instale: pip install openpyxl")
    df = df.fillna("")
    headers = list(df.columns)
    filas = [{h: str(row[h]).strip() for h in headers} for _, row in df.iterrows()]
    return filas, headers


def cargar_tabla(path, hoja=None):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return cargar_xlsx(path, hoja)
    return cargar_csv(path)


# ------------------------------------------------------------------
# Procesamiento: mismo flujo de 4 pasos que auditar_l5x.procesar(), pero
# alimentado desde filas tabulares en vez de nodos <Tag> del XML.
# ------------------------------------------------------------------
def procesar_tabla(filas, cols):
    col_nombre   = cols["nombre"]
    col_datatype = cols.get("datatype")
    col_desc     = cols.get("descripcion")
    col_scope    = cols.get("scope")
    col_tagtype  = cols.get("tagtype")
    col_aliasfor = cols.get("aliasfor")
    col_recordtype = cols.get("recordtype")
    col_plc      = cols.get("plc")

    descartadas = 0

    # ---- Paso 1: clasificar cada fila (sin numerar todavia) ----
    interim = []
    for fila in filas:
        # Filtrar registros que no son tags (ej. TEXTBOX/COMMENT del export)
        if col_recordtype:
            rt = _norm(fila.get(col_recordtype))
            if rt and rt not in ("TAG", "ALIAS"):
                descartadas += 1
                continue

        nombre = (fila.get(col_nombre) or "").strip()
        if not nombre:
            descartadas += 1
            continue

        datatype = (fila.get(col_datatype) or "").strip() if col_datatype else ""
        descripcion = (fila.get(col_desc) or "").strip() if col_desc else ""
        scope = (fila.get(col_scope) or "").strip() if col_scope else ""
        aliasfor = (fila.get(col_aliasfor) or "").strip() if col_aliasfor else ""
        plc = (fila.get(col_plc) or "").strip() if col_plc else ""
        if col_tagtype:
            tagtype = (fila.get(col_tagtype) or "Base").strip() or "Base"
        else:
            tagtype = "Alias" if aliasfor else "Base"

        clase, funcion, area, notas = base.clasificar(nombre, tagtype, aliasfor, datatype)
        notas = base.validar_reglas(nombre, funcion, notas, clase)

        interim.append({
            "tag_viejo": nombre, "clase": clase, "funcion_ISA": funcion or "",
            "area_detectada": area or "", "datatype": datatype, "alias_for": aliasfor,
            "descripcion": descripcion, "scope": scope, "plc": plc, "notas": notas,
        })

    indice_area_por_nombre = {
        f["tag_viejo"].upper(): base.MAPEO_AREA[f["area_detectada"]]
        for f in interim if f["area_detectada"] and base.MAPEO_AREA.get(f["area_detectada"])
    }

    # ---- Paso 2: herencia de area por Scope (columna de Programa) ----
    # En modo tabular NO hay estructura de rutinas: la unica herencia
    # disponible es por el nombre del Program/Scope de la propia fila.
    cod_area_heredado_por_tag = {}
    for fila in interim:
        if fila["area_detectada"]:
            continue
        cod = base.area_por_nombre_contenedor(fila["scope"]) if fila["scope"] else None
        if cod:
            cod_area_heredado_por_tag[fila["tag_viejo"]] = (cod, f"Program/Scope '{fila['scope']}'")
            fila["notas"].append(f"Area heredada por Scope (columna): '{fila['scope']}' -> {cod}")
        else:
            cod_area_heredado_por_tag[fila["tag_viejo"]] = (None, None)

    # ---- Paso 2.5: inferencia semantica por palabras clave ----
    for fila in interim:
        cod_actual, _ = cod_area_heredado_por_tag.get(fila["tag_viejo"], (None, None))
        if fila["area_detectada"] or cod_actual:
            continue
        cod_kw, evidencia = base.area_por_palabras_clave(fila["tag_viejo"])
        if cod_kw == "AMBIGUO":
            resumen_amb = ", ".join(f"{a} por '{kw}'" for a, kw in evidencia.items())
            fila["notas"].append(f"Palabra clave AMBIGUA: coincide con mas de un area ({resumen_amb}) - revisar manualmente")
        elif cod_kw:
            cod_area_heredado_por_tag[fila["tag_viejo"]] = (cod_kw, f"palabra clave '{evidencia}'")
            fila["notas"].append(f"Area asignada por palabra clave de proceso: '{evidencia}' -> {cod_kw}")

    # ---- Paso 3: numerar y armar filas definitivas ----
    contador = defaultdict(int)
    resumen = defaultdict(int)
    filas_out = []
    for fila in interim:
        area_label = fila["area_detectada"]
        if area_label:
            cod_area = base.MAPEO_AREA.get(area_label)
        else:
            cod_area, _ = cod_area_heredado_por_tag.get(fila["tag_viejo"], (None, None))

        tag_nuevo = base.proponer_tag(fila["clase"], cod_area, fila["funcion_ISA"] or None, contador)
        resumen[fila["clase"]] += 1
        filas_out.append({
            "tag_viejo": fila["tag_viejo"],
            "clase": fila["clase"],
            "funcion_ISA": fila["funcion_ISA"],
            "area_detectada": area_label,
            "cod_area": cod_area or "",
            "datatype": fila["datatype"],
            "alias_for": fila["alias_for"],
            "tag_nuevo_propuesto": tag_nuevo,
            "descripcion": fila["descripcion"],
            "scope": fila["scope"],
            "plc": fila["plc"],
            "validacion": " | ".join(fila["notas"]),
        })

    # ---- Paso 4: agrupar INTERNA como miembros de UDT ----
    # grafo FBD vacio: en modo tabular el enlazado es solo por nombre.
    indice_base = {
        f["tag_viejo"].upper(): f for f in filas_out
        if f["clase"] in ("FUNCIONAL_ISA", "FISICO_ISA")
    }
    indice_pendiente = {
        f["tag_viejo"].upper(): f for f in filas_out if f["clase"] == "SIN_CLASIFICAR"
    }
    grafo_vacio = []
    for fila in filas_out:
        if fila["clase"] != "INTERNA":
            continue
        tag_nuevo, nota_udt = base.transformar_interna_a_miembro(
            fila, indice_base, indice_pendiente, grafo_vacio, cod_area_heredado_por_tag
        )
        fila["tag_nuevo_propuesto"] = tag_nuevo
        fila["validacion"] = (fila["validacion"] + " | " + nota_udt).strip(" |")

    return filas_out, resumen, descartadas


# ------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Uso: python auditar_masivo.py <archivo.csv|.xlsx> [hoja]")
        sys.exit(1)
    path = sys.argv[1]
    hoja = sys.argv[2] if len(sys.argv) > 2 else None
    if not os.path.isfile(path):
        print(f"No existe el archivo: {path}")
        sys.exit(1)

    filas_raw, headers = cargar_tabla(path, hoja)

    cols = {
        "nombre":     _detectar_columna(headers, COLS_NOMBRE),
        "datatype":   _detectar_columna(headers, COLS_DATATYPE),
        "descripcion": _detectar_columna(headers, COLS_DESCRIPCION),
        "scope":      _detectar_columna(headers, COLS_SCOPE),
        "tagtype":    _detectar_columna(headers, COLS_TAGTYPE),
        "aliasfor":   _detectar_columna(headers, COLS_ALIASFOR),
        "recordtype": _detectar_columna(headers, COLS_RECORDTYPE),
        "plc":        _detectar_columna(headers, COLS_PLC),
    }
    if not cols["nombre"]:
        print(f"No se detecto columna de nombre de tag. Columnas vistas: {headers}")
        sys.exit(1)

    filas_out, resumen, descartadas = procesar_tabla(filas_raw, cols)

    campos = ["tag_viejo", "clase", "funcion_ISA", "area_detectada", "cod_area",
              "datatype", "alias_for", "tag_nuevo_propuesto", "descripcion",
              "scope", "plc", "validacion"]

    def es_pendiente(f):
        return "PENDIENTE" in f["tag_nuevo_propuesto"] or "???" in f["tag_nuevo_propuesto"]

    filas_limpias = [f for f in filas_out if not es_pendiente(f)]
    filas_pendientes = [f for f in filas_out if es_pendiente(f)]

    os.makedirs(BASE_DIR, exist_ok=True)
    salida_ok = os.path.join(BASE_DIR, "25k_mapeo_exitoso.csv")
    salida_sc = os.path.join(BASE_DIR, "25k_sin_clasificar.csv")
    for ruta, datos in ((salida_ok, filas_limpias), (salida_sc, filas_pendientes)):
        with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
            w.writeheader()
            w.writerows(datos)

    total = len(filas_out)
    print(f"\n=== AUDITORIA MASIVA: {os.path.basename(path)} ===")
    print(f"Columnas detectadas: " + ", ".join(f"{k}='{v}'" for k, v in cols.items() if v))
    print(f"Filas descartadas (no-tag / vacias): {descartadas}")
    print(f"Total de tags procesados: {total}")
    print("-" * 46)
    for clase, n in sorted(resumen.items(), key=lambda x: -x[1]):
        pct = (100 * n / total) if total else 0
        print(f"  {clase:18} {n:6}  ({pct:4.1f}%)")
    print("-" * 46)
    cobertura = (100 * len(filas_limpias) / total) if total else 0
    print(f"  Consolidados en 25k_mapeo_exitoso.csv : {len(filas_limpias)}  ({cobertura:.1f}%)")
    print(f"  Movidos a 25k_sin_clasificar.csv       : {len(filas_pendientes)}")
    print(f"\n  {salida_ok}")
    print(f"  {salida_sc}")


if __name__ == "__main__":
    main()
