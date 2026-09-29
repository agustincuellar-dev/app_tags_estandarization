"""Genera la propuesta v2 de numeracion de los 3 lazos (correcciones P1, P2 y P4).

QUE HACE
--------
Toma la propuesta v1 (`exports/propuesta_numeracion_3_lazos_v1.csv`, resguardada) y produce la
v2 con la MISMA numeracion (083 / 081 / 082, decision cerrada del usuario) y estos cambios:

  P1  Citas de hoja/fila corregidas a los valores reales de los inventarios online.
  P2  `Numeros_Detectados_Identificadores_Vigentes_Area` regenerado con
      src/identificadores_vigentes.py (regla lexica documentada, excluye tokens de equipo).
  P3  (registro) `Nota_Sucesion` con la sucesion documental de cada numero.
  P4  `Tag_Intermedio` + `Camino_Completo_Lazo` con el camino real de wires
      (alias de campo -> SCL -> tag interno REAL -> PV -> MV -> alias de salida),
      `Observaciones_Lazo` (accion directa/inversa) y `Ambiguedades_Sin_Accion`.

Columnas nuevas respecto de v1:
  Tag_Intermedio, Migrado_De, Camino_Completo_Lazo, Observaciones_Lazo, Ambiguedades_Sin_Accion,
  Nota_Sucesion, Evidencia_Identificadores_Vigentes, Fluido_Proceso, Tipo_Senal,
  Entrada_Salida_BD, DataType_BD, Estado_BD

REGLA DE "MIGRADO DE" (decision del usuario)
--------------------------------------------
Solo identidades PLC que el tecnico ve en el ingenio:
  ENTRADA     -> tag interno REAL que alimenta PV (DES_LT_TK_DESAIREADOR / FT_AGUA / LT_TK_AGUA_POTABLE)
  CONTROLADOR -> instancia AOI (B_DES_LC_DOMO / B_Ctrol_FT_AGUA_A_MOSTO / B_Ctrol_TK_AGUA_POTABLE)
  SALIDA      -> alias de salida (DES_S6_PV_VALVULA_EVACUACION_DES / Slot_PV_VALVULA_CAUDAL_AGUA /
                 Slot_PV_VALVULA_NIVEL_TK_AGUA)
PROHIBIDO en "Migrado de": los tags de catalogo historico que nadie usa (200_LT_012, 200_ST_009,
200_PV_003, 200_FT_002). Esos quedan SOLO en las columnas de auditoria historica.
El alias de campo, su AliasFor y el paso por el bloque SCL van en `Tag_Intermedio`, no en `Migrado_De`.

Solo lectura sobre SQLite. Salida: CSV. No inserta nada.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from identificadores_vigentes import extraer_todo, formatear_rangos  # noqa: E402

ENTRADA_V1 = RAIZ / "exports" / "propuesta_numeracion_3_lazos_v1.csv"
SALIDA_V2 = RAIZ / "exports" / "propuesta_numeracion_3_lazos.csv"

ESTADO_PRO = "PROPUESTA_CONCRETA_PARA_REVISION — NO_INSERTAR"

# --- P1: citas verificadas hoja/fila (los valores reales, no los de v1) ------------------
FUENTES_AREA = {
    "300": (
        "docs/Manual_Estandarizacion.md:83-97 (tabla oficial de areas; fila 300 = Calderas / "
        "Generacion de Vapor, linea 90) | docs/Roadmap_Arquitectura_Inteligente.md:19-22 "
        "(DES = Desaireador area 300 en Calderas_8_9_10_Desaireador) | "
        "docs/Manual_Mantenimiento_Codigo.md:110-112 (MAPEO_AREA_OVERRIDE_POR_PLC) | "
        "inventario_plcs_20260806_093710-PLC_Caldera_8_9_10_Desaireador(195).xlsx hoja PLCs fila 2 "
        "(192.168.10.195) y hoja Programas fila 6 (programa DES, rutina DES_LC_DESAIREADOR) | "
        "inventario_plcs_20260806_093327-PLC_Caldera_8_9_10_Desaireador(196).xlsx hoja PLCs fila 2 "
        "(192.168.10.196) y hoja Programas fila 6 (programa DES) | "
        "L5X_Produccion/Calderas_8_9_10_Desaireador.L5X"
    ),
    "200": (
        "docs/Manual_Estandarizacion.md:83-97 (tabla oficial de areas; fila 200 = Destileria, "
        "linea 89) | inventario_plcs_20260806_093238-PLC_Destileria.xlsx hoja PLCs fila 2 "
        "(192.168.10.128) y hoja Programas fila 3 (programa FERMENTACION, rutina PID_FERMENTACION) | "
        "L5X_Produccion/DESTILERIA.L5X"
    ),
}

# --- P4: camino real de wires, por lazo ---------------------------------------------------
# Verificado por traza de <Wire> en las hojas FBD: alias -> In del SCL -> Out -> ORef interno,
# y luego PV del AOI CONTROL_NIVEL -> MV -> ORef del alias de salida.
CAMINO_LAZO = {
    "Calderas_8_9_10_Desaireador/Program:DES/B_DES_LC_DOMO": (
        "DES_S1_LT_TK_DESAIREADOR (alias de campo, AliasFor Desaireador:2:I.Ch[4].Data) "
        "-> SCL B_DES_LT_TK_DESAIREADOR (Program:DES, rutina DES_S1_ESCALADO_AI) "
        "-> DES_LT_TK_DESAIREADOR (tag interno REAL) "
        "-> PV de B_DES_LC_DOMO (Program:DES, rutina DES_LC_DESAIREADOR) -> MV "
        "-> DES_S6_PV_VALVULA_EVACUACION_DES (alias de salida, AliasFor Desaireador:6:O.Ch4Data)"
    ),
    "DESTILERIA/Program:FERMENTACION/B_Ctrol_FT_AGUA_A_MOSTO": (
        "Slot_FT_AGUA (alias de campo, AliasFor jw_fermerntacion_2022:6:I.Ch[0].Data) "
        "-> SCL B_FT_AGUA (Program:FERMENTACION, rutina ESCALADOS_PT_FT_LT_TT) "
        "-> FT_AGUA (tag interno REAL) "
        "-> PV de B_Ctrol_FT_AGUA_A_MOSTO (Program:FERMENTACION, rutina PID_FERMENTACION) -> MV "
        "-> Slot_PV_VALVULA_CAUDAL_AGUA (alias de salida, AliasFor jw_fermerntacion_2022:10:O.Ch2Data)"
    ),
    "DESTILERIA/Program:FERMENTACION/B_Ctrol_TK_AGUA_POTABLE": (
        "Slot_LT_TK_AGUA_POTABLE (alias de campo, AliasFor jw_fermerntacion_2022:5:I.Ch[7].Data) "
        "-> SCL B_LT_TK_AGUA_POTABLE (Program:FERMENTACION, rutina ESCALADOS_PT_FT_LT_TT) "
        "-> LT_TK_AGUA_POTABLE (tag interno REAL) "
        "-> PV de B_Ctrol_TK_AGUA_POTABLE (Program:FERMENTACION, rutina PID_FERMENTACION) -> MV "
        "-> Slot_PV_VALVULA_NIVEL_TK_AGUA (alias de salida, AliasFor jw_fermerntacion_2022:11:O.Ch1Data)"
    ),
}

# Tag_Intermedio por tag propuesto (P4): el tramo que le corresponde a cada rol.
TAG_INTERMEDIO = {
    "300_LT_083": (
        "Alias de campo DES_S1_LT_TK_DESAIREADOR (AliasFor Desaireador:2:I.Ch[4].Data) "
        "-> SCL B_DES_LT_TK_DESAIREADOR (bloque SCL ID 59, wire IRef 38 -> In / Out -> ORef 48) "
        "-> tag interno REAL DES_LT_TK_DESAIREADOR. El controlador NO recibe el alias directo: PV se "
        "cablea al tag interno."
    ),
    "300_LIC_083": (
        "PV <- DES_LT_TK_DESAIREADOR (tag interno REAL, no el alias de campo); "
        "MV -> DES_S6_PV_VALVULA_EVACUACION_DES. AOI CONTROL_NIVEL, instancia B_DES_LC_DOMO."
    ),
    "300_LV_083": (
        "MV de B_DES_LC_DOMO -> ORef alias de salida DES_S6_PV_VALVULA_EVACUACION_DES "
        "(AliasFor Desaireador:6:O.Ch4Data). Salida directa desde el controlador, sin bloque intermedio."
    ),
    "200_FT_081": (
        "Alias de campo Slot_FT_AGUA (AliasFor jw_fermerntacion_2022:6:I.Ch[0].Data) "
        "-> SCL B_FT_AGUA (bloque SCL, wire IRef 88 -> In / Out -> ORef 109) "
        "-> tag interno REAL FT_AGUA. El controlador NO recibe el alias directo: PV se cablea al tag interno."
    ),
    "200_FIC_081": (
        "PV <- FT_AGUA (tag interno REAL, no el alias de campo); "
        "MV -> Slot_PV_VALVULA_CAUDAL_AGUA. AOI CONTROL_NIVEL, instancia B_Ctrol_FT_AGUA_A_MOSTO."
    ),
    "200_FV_081": (
        "MV de B_Ctrol_FT_AGUA_A_MOSTO -> ORef alias de salida Slot_PV_VALVULA_CAUDAL_AGUA "
        "(AliasFor jw_fermerntacion_2022:10:O.Ch2Data). Salida directa desde el controlador."
    ),
    "200_LT_082": (
        "Alias de campo Slot_LT_TK_AGUA_POTABLE (AliasFor jw_fermerntacion_2022:5:I.Ch[7].Data) "
        "-> SCL B_LT_TK_AGUA_POTABLE (bloque SCL ID 672, wire IRef 633 -> In / Out -> ORef 651) "
        "-> tag interno REAL LT_TK_AGUA_POTABLE. El controlador NO recibe el alias directo."
    ),
    "200_LIC_082": (
        "PV <- LT_TK_AGUA_POTABLE (tag interno REAL, no el alias de campo); "
        "MV -> Slot_PV_VALVULA_NIVEL_TK_AGUA. AOI CONTROL_NIVEL, instancia B_Ctrol_TK_AGUA_POTABLE."
    ),
    "200_LV_082": (
        "MV de B_Ctrol_TK_AGUA_POTABLE -> ORef alias de salida Slot_PV_VALVULA_NIVEL_TK_AGUA "
        "(AliasFor jw_fermerntacion_2022:11:O.Ch1Data). Salida directa desde el controlador."
    ),
}

# Migrado_De (decision del usuario): solo identidades PLC visibles para el tecnico.
MIGRADO_DE = {
    "300_LT_083": "DES_LT_TK_DESAIREADOR",
    "300_LIC_083": "B_DES_LC_DOMO",
    "300_LV_083": "DES_S6_PV_VALVULA_EVACUACION_DES",
    "200_FT_081": "FT_AGUA",
    "200_FIC_081": "B_Ctrol_FT_AGUA_A_MOSTO",
    "200_FV_081": "Slot_PV_VALVULA_CAUDAL_AGUA",
    "200_LT_082": "LT_TK_AGUA_POTABLE",
    "200_LIC_082": "B_Ctrol_TK_AGUA_POTABLE",
    "200_LV_082": "Slot_PV_VALVULA_NIVEL_TK_AGUA",
}

# Observaciones por lazo: constantes reales cableadas y sentido de la accion.
OBSERVACIONES_LAZO = {
    "Calderas_8_9_10_Desaireador/Program:DES/B_DES_LC_DOMO": (
        "ACCION_CTRL_DIREC1_INVER0 = 1 (accion directa, IRef constante '1'). "
        "PV_MIN = 0.0 | PV_MAX = 100.0 (IRef constantes). "
        "La salida MV va directa al alias de salida."
    ),
    "DESTILERIA/Program:FERMENTACION/B_Ctrol_FT_AGUA_A_MOSTO": (
        "ACCION_CTRL_DIREC1_INVER0 = 1 (accion directa). "
        "PV_MIN = 0.0 | PV_MAX = 100.0 | SP_MAX = 150.0 | MV_MAX = 1.0 (IRef constantes). "
        "La salida MV va directa al alias de salida."
    ),
    "DESTILERIA/Program:FERMENTACION/B_Ctrol_TK_AGUA_POTABLE": (
        "ACCION_CTRL_DIREC1_INVER0 = 0 -> ACCION INVERSA DECLARADA (los otros dos lazos usan 1). "
        "PV_MIN = 0.0 | PV_MAX = 100.0 (IRef constantes). "
        "La salida MV va directa al alias de salida."
    ),
}

AMBIGUEDADES_SIN_ACCION = {
    "Calderas_8_9_10_Desaireador/Program:DES/B_DES_LC_DOMO": "NINGUNA",
    "DESTILERIA/Program:FERMENTACION/B_Ctrol_FT_AGUA_A_MOSTO": "NINGUNA",
    "DESTILERIA/Program:FERMENTACION/B_Ctrol_TK_AGUA_POTABLE": (
        "IRef LT_CUBA_1 (ID 55) declarado en la hoja del FBD y SIN CABLE al bloque "
        "B_Ctrol_TK_AGUA_POTABLE: ambiguedad registrada SIN ACCION, no altera la numeracion "
        "propuesta ni el camino del lazo."
    ),
}

# Nota_Sucesion por numero propuesto (texto de gobernanza dictado por el usuario).
NOTA_SUCESION = {
    "083": (
        "Sin antecedente en area 300: ninguna fila con area 300 y numero 083 en el backup de 693 "
        "tags ni en la documentacion localizada. Salto de area 200->300 documentado: las "
        "identidades historicas del mismo equipo se registraron en area 200 (200_LT_012, "
        "200_ST_009, 200_PV_003), no en 300. Solo columnas de auditoria."
    ),
    "081": (
        "Dueno previo FT_VINO_A_JW_ACUM_TOTAL, retirado 28/08 (Resumen 280826:125), nunca "
        "insertado; reasignado 18/09 al lazo caudal agua a mosto."
    ),
    "082": (
        "Figura como Conservar para FT_VINO_A_JW_ACUM_HR_ACT (Resumen 280826:123), derivado que "
        "segun lineas 108-109 no debe llevar tag numerado; nunca insertado; asignado 18/09 al "
        "lazo nivel agua potable (variable y clave de lazo distintas)."
    ),
}

# --- P3 (v2.1): texto corregido de la columna de auditoria historica para el numero 082 ------
# v1 afirmaba "historico"; la linea 123 real del Resumen 280826 lista 200_FT_082 en la columna
# "Conservar". La v2 lo dejo como en v1 (fuera de alcance); la v2.1 lo corrige por autorizacion.
COINCIDENCIA_HISTORICA_POR_NUMERO = {
    "082": ("NO retirado: Resumen 280826:123 coloca 200_FT_082 en columna Conservar; "
            "nunca insertado en DB ni backup; ver Nota_Sucesion"),
}

# Datos de alta en la base (los usa src/insertar_9_tags_aprobados.py leyendo SOLO este CSV).
FLUIDO_PROCESO = {
    "300_LT_083": "Agua (desaireador)", "300_LIC_083": "Agua (desaireador)", "300_LV_083": "Agua (desaireador)",
    "200_FT_081": "Agua a mosto", "200_FIC_081": "Agua a mosto", "200_FV_081": "Agua a mosto",
    "200_LT_082": "Agua potable", "200_LIC_082": "Agua potable", "200_LV_082": "Agua potable",
}
ENTRADA_SALIDA_BD = {"ENTRADA": "Entrada", "CONTROLADOR": "Memoria / Red", "SALIDA": "Salida"}

ORDEN_COLUMNAS = [
    "PLC", "Program", "Routine", "Scope_Identidad", "Loop_ID", "Rol", "Identidad_Actual",
    "AliasFor_Direccion_Fisica", "Tag_Intermedio", "Migrado_De",
    "Area", "Variable_ISA", "Funcion_ISA", "Numero_Propuesto", "Tag_Propuesto",
    "Descripcion_Propuesta", "Fluido_Proceso", "Tipo_Senal", "Entrada_Salida_BD", "DataType_BD",
    "Estado_BD", "Verificacion_Documental_Area", "Fuentes_Area",
    "Numeros_Ocupados_11_Manuales_Area", "Numero_En_11_Manuales",
    "Numeros_Detectados_Identificadores_Vigentes_Area", "Numero_En_Identificadores_Vigentes",
    "Fuente_Identificadores_Vigentes", "Evidencia_Identificadores_Vigentes",
    "Conflicto_Con_Otros_Lazos_Propuestos",
    "Coincidencias_Historico_Retirado_Por_Identidad",
    "Coincidencias_Historico_Retirado_Por_Numero", "Historico_Retirado_Bloquea",
    "Nota_Sucesion", "Observaciones_Lazo", "Ambiguedades_Sin_Accion", "Camino_Completo_Lazo",
    "Verificacion_Area", "Verificacion_Numero", "Estado_Propuesta", "Escritura_SQLite",
]


def leer_v1(ruta: Path = ENTRADA_V1) -> list[dict]:
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def contexto_p2(resultados) -> dict:
    """Columnas P2 por area: lista de numeros, marca de colision, fuente y evidencia compacta."""
    salida = {}
    for resultado in resultados:
        area = resultado["area"]
        numeros = resultado["numeros"]
        ejemplos = []
        for numero in numeros[:3]:
            identificadores = resultado["evidencia"][numero][:2]
            ejemplos.append("%03d: %s" % (numero, "|".join(identificadores)))
        salida[area] = {
            "numeros": formatear_rangos(numeros),
            "cantidad": len(numeros),
            "fuente": (
                "src/identificadores_vigentes.py (regla lexica documentada, deterministica): hoja Tags "
                "de los inventarios online del area; forma <MORFEMA ISA>_<NUM 2-3 digitos> al inicio del "
                "identificador, quitando prefijo de alcance y de area; morfema validado contra los "
                "catalogos ISA del proyecto (tablas variables/funciones, base en solo lectura). Excluye "
                "instancias de bloque/escalera (BNOT_xx, ADD_xx, SCL_xx, MUL_xx...), bits y equipos "
                "(B_*, BAND_*, BBA_*), mensajes (MSG_*, ETH_*) y numeros de 4 digitos. Archivos: "
                + " | ".join(resultado["archivos"])
            ),
            "evidencia": ("%d numeros detectados. Muestra -> %s" % (len(numeros), " ; ".join(ejemplos)))
            if numeros else "sin numeros detectados",
        }
    return salida


def construir_v2(filas_v1: list[dict], p2: dict) -> list[dict]:
    salida = []
    for fila in filas_v1:
        tag = fila["Tag_Propuesto"]
        loop = fila["Loop_ID"]
        area = fila["Area"]
        numero = str(fila["Numero_Propuesto"]).zfill(3)
        nueva = {columna: fila.get(columna, "") for columna in ORDEN_COLUMNAS}
        nueva["Fuentes_Area"] = FUENTES_AREA[area]                      # P1
        nueva["Numeros_Detectados_Identificadores_Vigentes_Area"] = p2[area]["numeros"]  # P2
        nueva["Numero_En_Identificadores_Vigentes"] = "NO"              # verificado abajo
        nueva["Fuente_Identificadores_Vigentes"] = p2[area]["fuente"]
        nueva["Evidencia_Identificadores_Vigentes"] = p2[area]["evidencia"]
        nueva["Tag_Intermedio"] = TAG_INTERMEDIO[tag]                   # P4
        nueva["Migrado_De"] = MIGRADO_DE[tag]
        nueva["Camino_Completo_Lazo"] = CAMINO_LAZO[loop]
        nueva["Observaciones_Lazo"] = OBSERVACIONES_LAZO[loop]
        nueva["Ambiguedades_Sin_Accion"] = AMBIGUEDADES_SIN_ACCION[loop]
        nueva["Nota_Sucesion"] = NOTA_SUCESION[numero]
        nueva["Fluido_Proceso"] = FLUIDO_PROCESO[tag]
        nueva["Tipo_Senal"] = "Analógico"
        nueva["Entrada_Salida_BD"] = ENTRADA_SALIDA_BD[fila["Rol"]]
        nueva["DataType_BD"] = "REAL"
        nueva["Estado_BD"] = "Planificado"
        nueva["Estado_Propuesta"] = ESTADO_PRO
        nueva["Escritura_SQLite"] = "NO"
        if numero in COINCIDENCIA_HISTORICA_POR_NUMERO:                 # P3 / v2.1
            nueva["Coincidencias_Historico_Retirado_Por_Numero"] = COINCIDENCIA_HISTORICA_POR_NUMERO[numero]
        salida.append(nueva)

    # La marca de colision P2 no puede ser inventada: se calcula.
    for fila in salida:
        numero = int(str(fila["Numero_Propuesto"]).zfill(3))
        rango = p2[fila["Area"]]["numeros"]
        if rango == "NINGUNO":
            colision = False
        else:
            colision = False
            for tramo in rango.split("|"):
                if "-" in tramo:
                    a, b = tramo.split("-")
                    colision = colision or (int(a) <= numero <= int(b))
                else:
                    colision = colision or (numero == int(tramo))
        fila["Numero_En_Identificadores_Vigentes"] = "SI" if colision else "NO"
    return salida


def escribir_v2(filas: list[dict], destino: Path = SALIDA_V2) -> Path:
    with open(destino, "w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=ORDEN_COLUMNAS, delimiter=";", lineterminator="\n")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({columna: fila.get(columna, "") for columna in ORDEN_COLUMNAS})
    return destino


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Genera la propuesta v2 (P1 + P2 + P4). Solo lectura sobre SQLite.")
    parser.add_argument("--v1", default=str(ENTRADA_V1))
    parser.add_argument("--salida", default=str(SALIDA_V2))
    args = parser.parse_args(argv)

    filas_v1 = leer_v1(Path(args.v1))
    if len(filas_v1) != 9:
        raise SystemExit("La v1 debe tener 9 filas; tiene %d" % len(filas_v1))
    p2 = contexto_p2(extraer_todo(["200", "300"]))
    filas = construir_v2(filas_v1, p2)
    destino = escribir_v2(filas, Path(args.salida))
    print("[OK] Propuesta v2: %s (%d filas x %d columnas)" % (destino, len(filas), len(ORDEN_COLUMNAS)))
    for area in ("300", "200"):
        print("[P2] Area %s -> %s" % (area, p2[area]["numeros"]))
    colisiones = [f["Tag_Propuesto"] for f in filas if f["Numero_En_Identificadores_Vigentes"] == "SI"]
    print("[P2] Numeros propuestos en colision con identificadores vigentes: %s" % (colisiones or "NINGUNA"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
