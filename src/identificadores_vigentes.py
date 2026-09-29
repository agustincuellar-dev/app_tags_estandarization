"""Extraccion reproducible de numeros ocupados por identificadores vigentes (correccion P2).

PROBLEMA QUE RESUELVE
---------------------
La columna `Numeros_Detectados_Identificadores_Vigentes_Area` de la propuesta v1 no era
reproducible: mezclaba instancias de bloque de escalera (BNOT_xx, ADD_xx, SCL_xx, MUL_xx,
ALM_xx, ACUM_xx), bits booleanos (B_*, BAND_*), equipos (BBA_*) y mensajes (MSG_*, ETH_*)
con verdaderos identificadores de instrumento. Ademas citaba tokens (020, 081 en area 300;
601 en area 200) que no existen como tales en la fuente.

REGLA DE EXTRACCION (deterministica y documentada)
--------------------------------------------------
 1. Fuente: hoja `Tags` de los inventarios online declarados por area (INVENTARIOS_POR_AREA).
 2. Se toma la columna `Tag` y se quita el prefijo de alcance (`Controller.` / `Program:<x>.`).
 3. Se quita el prefijo de area opcional (`000_`, `100_`, ..., `950_`).
 4. El identificador es candidato ISA sii su PRIMER token es un morfema de instrumento y el
    SEGUNDO token es un numero de 2 a 3 digitos:

        [<AREA>_]<MORFEMA>_<NUM>[_<calificadores...>]

 5. MORFEMA = 1 letra de variable + 1 codigo de funcion, tomados de los catalogos ISA del
    proyecto: tablas `variables` y `funciones` de app_etiquetas/tags_ingenio.db (solo lectura).
    Esto excluye POR CONSTRUCCION las instancias de bloque/escalera (BNOT_xx, ADD_xx, SCL_xx,
    MUL_xx, DIV_xx, GRT_xx, LES_xx, SEL_xx, LPF_xx, ABS_xx, ALM_xx, ACUM_xx), los bits
    booleanos (B_*, BAND_*, BNOT_*), las bombas y equipos (BBA_*), los mensajes (MSG_*, ETH_*)
    y los numeros de equipo embebidos al final (DES_2_..._TK_20_NORTE, TT_CHIMENEA_CAL_10_ESTE),
    porque en todos esos casos el numero no va precedido por un morfema ISA en las dos
    primeras posiciones.
 6. Se excluyen los numeros de 4 digitos (p. ej. 1000 / 1001 en DES_S1_LT_TK_1000): son
    ambiguos con numeros de activo/tanque. La norma admite 3 o 4 digitos, pero para ocupacion
    de lazo esta herramienta se declara conservadora y solo informa 2-3 digitos.
 7. Salida: por area, numeros ordenados + identificadores de evidencia + archivo de origen.

LIMITES DECLARADOS (evidencia honesta)
--------------------------------------
- La regla es LEXICA. Registra que el numero esta en uso por un identificador con forma ISA
  dentro de un inventario online; NO prueba existencia fisica, ni servicio, ni runtime.
- Un instrumento cuyo identificador no ponga el numero inmediatamente despues del morfema
  (p. ej. `LIT_102_CALDERA_11` si entra; `S1_LT_TK_DESAIREADOR` no tiene numero y queda fuera
  por diseno) no se informa. Por eso el resultado es un PISO, no un techo, de la ocupacion.
- Los identificadores con numero de 4 digitos quedan fuera por el punto 6.

Uso:
    python src/identificadores_vigentes.py                    # escribe exports/identificadores_vigentes_por_area.csv
    python src/identificadores_vigentes.py --area 300         # imprime solo el area 300
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB_PRODUCCION = RAIZ / "app_etiquetas" / "tags_ingenio.db"
DIR_INVENTARIOS = RAIZ / "variables plc programa yanco"
SALIDA_CSV = RAIZ / "exports" / "identificadores_vigentes_por_area.csv"

# Inventarios online por area. Fuente del mapeo PLC -> area: src/auditar_l5x.py
# (AREA_DEFECTO_POR_PLC + MAPEO_AREA_OVERRIDE_POR_PLC).
#   - Area 300 agrupa TODOS los PLCs de Calderas (8/9/10 desaireador, 11 y La Florida 251/252)
#     porque la numeracion ISA es por area.
#   - El PLC FABRICA es multi-area: sus identificadores se atribuyen por prefijo, que es el
#     acronimo de la tabla oficial de areas (docs/Manual_Estandarizacion.md:87-97): EVAP=500,
#     COC=600, CCV=700. Sin ese filtro, un numero de evaporacion bloquearia un lazo de tachos.
INVENTARIOS_POR_AREA = {
    "100": (
        ("inventario_plcs_20260806_085612-PLC_Trapiche.xlsx", None),
        ("inventario_plcs_20260806_094422-PLC_Ctr_Turb_Moenda.xlsx", None),
    ),
    "200": (
        ("inventario_plcs_20260806_093238-PLC_Destileria.xlsx", None),
    ),
    "300": (
        ("inventario_plcs_20260806_093710-PLC_Caldera_8_9_10_Desaireador(195).xlsx", None),
        ("inventario_plcs_20260806_093327-PLC_Caldera_8_9_10_Desaireador(196).xlsx", None),
        ("inventario_plcs_20260806_090505-PLC_Caldera_11.xlsx", None),
        ("inventario_plcs_20260806_094150-PLC_Caldera_LaFlorida(251).xlsx", None),
        ("inventario_plcs_20260806_094107-PLC_Caldera_LaFlorida(252).xlsx", None),
    ),
    "500": (
        ("inventario_plcs_20260806_085528-PLC_Fabrica.xlsx", ("EVAP",)),
    ),
    "600": (
        ("inventario_plcs_20260806_085528-PLC_Fabrica.xlsx", ("COC",)),
    ),
    "700": (
        ("inventario_plcs_20260806_085528-PLC_Fabrica.xlsx", ("CCV",)),
        ("inventario_plcs_20260806_094309-PLC_Centrifuga_1ra.xlsx", None),
    ),
}

PREFIJOS_AREA = ("000_", "100_", "200_", "250_", "300_", "400_", "500_", "600_", "700_", "800_", "900_", "950_")
RE_ALCANCE = re.compile(r"^(?:Controller\.|Program:[A-Za-z0-9_]+\.)")
RE_ANIO = re.compile(r"^\d{2}$")  # excluido abajo por rango, se documenta por claridad

# Identificadores cuyo nombre empieza con estos prefijos NUNCA son instrumentos de lazo.
# La regla de morfema ya los descarta; se declaran para que la exclusion sea explicita y auditable.
PREFIJOS_NO_INSTRUMENTO = (
    "B_", "BBA_", "BP_", "BAND_", "BNOT_", "ETH_", "MSG_", "VDF_", "IS_", "ACUM_", "ALM_",
    "LOCAL_REMOTO_", "ESTADO_", "FALLA_", "MAN_", "PROMEDIO_", "AUX_",
)


def cargar_catalogos_isa(ruta_db: Path = DB_PRODUCCION) -> tuple[set[str], set[str]]:
    """Devuelve (letras de variable, codigos de funcion) de los catalogos ISA del proyecto.

    Lee la base de produccion con URI mode=ro y PRAGMA query_only=ON y cierra explicitamente.
    """
    uri = Path(ruta_db).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conexion:
        conexion.execute("PRAGMA query_only=ON")
        variables = {fila[0] for fila in conexion.execute("SELECT letra FROM variables")}
        funciones = {fila[0] for fila in conexion.execute("SELECT letra FROM funciones")}
    return variables, funciones


def quitar_prefijos(nombre: str) -> str:
    """Quita el prefijo de alcance y el de area. Deterministico y sin regex ambiguas."""
    texto = RE_ALCANCE.sub("", str(nombre).strip())
    for prefijo in PREFIJOS_AREA:
        if texto.startswith(prefijo):
            texto = texto[len(prefijo):]
            break
    return texto


def es_morfema_isa(token: str, variables: set[str], funciones: set[str]) -> bool:
    """True si `token` es exactamente <1 letra de variable><1 codigo de funcion>."""
    return len(token) >= 2 and token[0] in variables and token[1:] in funciones


def numero_de_identificador(tag: str, variables: set[str], funciones: set[str]) -> int | None:
    """Numero de lazo del identificador, o None si no cumple la regla de extraccion."""
    base = quitar_prefijos(tag)
    if not base:
        return None
    if base.upper().startswith(PREFIJOS_NO_INSTRUMENTO):
        return None
    tokens = base.split("_")
    if len(tokens) < 2:
        return None
    morfema, numero = tokens[0], tokens[1]
    if not numero.isdigit() or not (2 <= len(numero) <= 3):
        return None
    if not es_morfema_isa(morfema, variables, funciones):
        return None
    if int(numero) == 0:
        return None
    return int(numero)


def _columna_tag(cabecera: list[str]) -> int:
    normalizada = [str(c).strip() for c in cabecera]
    if "Tag" not in normalizada:
        raise ValueError("El inventario no tiene columna 'Tag' en la hoja Tags")
    return normalizada.index("Tag")


def extraer_archivo(ruta: Path, variables: set[str], funciones: set[str], prefijos=None) -> dict[int, set[str]]:
    """{numero: {identificadores de evidencia}} para un inventario.

    `prefijos` limita la extraccion a los identificadores que empiezan con esos acronimos. Se usa
    para el PLC multi-area FABRICA, donde EVAP/COC/CCV pertenecen a areas distintas.
    """
    import openpyxl  # import local: la dependencia solo se necesita en la extraccion

    encontrados: dict[int, set[str]] = {}
    libro = openpyxl.load_workbook(str(ruta), read_only=True, data_only=True)
    try:
        if "Tags" not in libro.sheetnames:
            raise ValueError("El inventario %s no tiene hoja 'Tags'" % ruta.name)
        hoja = libro["Tags"]
        indice_tag = None
        for fila in hoja.iter_rows(values_only=True):
            if indice_tag is None:
                indice_tag = _columna_tag(list(fila))
                continue
            if indice_tag >= len(fila):
                continue
            base = quitar_prefijos(fila[indice_tag])
            if prefijos and not base.upper().startswith(tuple(prefijos)):
                continue
            numero = numero_de_identificador(fila[indice_tag], variables, funciones)
            if numero is None:
                continue
            encontrados.setdefault(numero, set()).add(base)
    finally:
        libro.close()
    return encontrados


def extraer_area(area: str, variables: set[str], funciones: set[str], dir_inventarios: Path = DIR_INVENTARIOS) -> dict:
    """Extrae un area completa. Devuelve {'numeros': [...], 'evidencia': {num: [...]}, 'archivos': [...]}."""
    if area not in INVENTARIOS_POR_AREA:
        raise ValueError("Area sin inventarios declarados: %s" % area)
    numeros: set[int] = set()
    evidencia: dict[int, set[str]] = {}
    etiquetas = []
    for nombre, prefijos in sorted(INVENTARIOS_POR_AREA[area]):
        ruta = Path(dir_inventarios) / nombre
        if not ruta.exists():
            raise FileNotFoundError("Falta el inventario declarado: %s" % ruta)
        etiquetas.append("%s%s" % (nombre, " [prefijo %s]" % ",".join(prefijos) if prefijos else ""))
        for numero, identificadores in extraer_archivo(ruta, variables, funciones, prefijos).items():
            numeros.add(numero)
            evidencia.setdefault(numero, set()).update(identificadores)
    return {
        "area": area,
        "numeros": sorted(numeros),
        "evidencia": {n: sorted(evidencia[n]) for n in sorted(evidencia)},
        "archivos": etiquetas,
    }


def extraer_todo(areas=None, dir_inventarios: Path = DIR_INVENTARIOS) -> list[dict]:
    """Extrae todas las areas declaradas, en orden de clave. Deterministico."""
    variables, funciones = cargar_catalogos_isa()
    claves = sorted(INVENTARIOS_POR_AREA) if areas is None else sorted(areas)
    return [extraer_area(area, variables, funciones, dir_inventarios) for area in claves]


def formatear_rangos(numeros) -> str:
    """[101,102,103,105] -> '101-103|105'. Contiguos se agrupan; el resto se lista suelto."""
    valores = sorted(set(int(n) for n in numeros))
    if not valores:
        return "NINGUNO"
    tramos = []
    inicio = anterior = valores[0]
    for valor in valores[1:]:
        if valor == anterior + 1:
            anterior = valor
            continue
        tramos.append((inicio, anterior))
        inicio = anterior = valor
    tramos.append((inicio, anterior))
    return "|".join("%d-%d" % (a, b) if a != b else "%d" % a for a, b in tramos)


def escribir_csv(resultados, destino: Path = SALIDA_CSV, max_evidencia: int = 6) -> Path:
    """Escribe el CSV de ocupacion vigente por area. Orden y contenido deterministas."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo, delimiter=";", lineterminator="\n")
        escritor.writerow([
            "Area", "Numeros_Vigentes", "Cantidad_Numeros", "Numero",
            "Identificadores_Evidencia", "Cantidad_Identificadores_Numero",
            "Archivos_Inventario",
        ])
        for resultado in resultados:
            archivos = " | ".join(resultado["archivos"])
            if not resultado["numeros"]:
                escritor.writerow([resultado["area"], "NINGUNO", 0, "", "", 0, archivos])
                continue
            for numero in resultado["numeros"]:
                identificadores = resultado["evidencia"][numero]
                muestra = " | ".join(identificadores[:max_evidencia])
                escritor.writerow([
                    resultado["area"], formatear_rangos(resultado["numeros"]),
                    len(resultado["numeros"]), "%03d" % numero,
                    muestra, len(identificadores), archivos,
                ])
    return destino


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Numeros de lazo ocupados por identificadores vigentes (solo lectura).")
    parser.add_argument("--area", action="append", help="Area a informar (repetible). Por defecto todas.")
    parser.add_argument("--salida", default=str(SALIDA_CSV), help="CSV de salida.")
    args = parser.parse_args(argv)

    resultados = extraer_todo(args.area)
    for resultado in resultados:
        print("[AREA %s] %d numeros vigentes: %s"
              % (resultado["area"], len(resultado["numeros"]), formatear_rangos(resultado["numeros"])))
        for numero in resultado["numeros"]:
            print("   %03d  %s" % (numero, " , ".join(resultado["evidencia"][numero][:4])))
    destino = escribir_csv(resultados, Path(args.salida))
    print("[OK] CSV: %s" % destino)
    print("[OK] Base leida en modo solo lectura (mode=ro + PRAGMA query_only=ON); cero escrituras SQLite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
