"""
analizar_dist_recolectado.py
==============================
Segunda etapa del flujo de recoleccion (ver recolector_fuentes_plc.py):
toma una carpeta "dist" ya recolectada -- eventualmente el resultado de
correr RecolectorFuentesPLC.exe en varias PCs de ingenieria y despues
fusionar manualmente esos resultados en una sola carpeta -- y responde la
pregunta operativa real: "de todo esto, cual es la version MAS RECIENTE de
cada equipo, y ya la tenemos auditada o hace falta pedir un export nuevo?"

Por que no alcanza con el trazabilidad_extraccion.csv del recolector:
  Si "dist" es la fusion manual de varias corridas en varias PCs, el CSV de
  trazabilidad de cada corrida se PISA (modo 'w') por la corrida siguiente
  que escriba en esa misma carpeta -- se pierde el detalle de origen de
  corridas anteriores. PERO la fecha de modificacion de cada archivo sigue
  intacta en disco (shutil.copy2 la preservo en su momento), asi que este
  modulo no depende del CSV: recorre los archivos directamente y confia en
  su mtime real.

Agrupamiento ("familia" de equipo):
  El recolector ya crea una subcarpeta por equipo, pero al fusionar varias
  corridas quedan variantes tipo 'DIBACCO_DUP3', 'DIBACCO.BAK000',
  'FABRICA.WIN_XXXX.ADMINISTRADOR.BAK093' -- todas el mismo equipo. Se
  vuelven a agrupar cortando el sufijo '_DUP<n>' y cualquier cola que
  empiece con '.BAK<n>', '.DESKTOP-' o '.WIN_'.

Filtro de ruido:
  "dist" suele arrastrar instalaciones de ejemplos de Rockwell (AOIs de
  muestra, DriveLogix samples, etc.) si el barrido se hizo sobre C:\\
  completo. Se filtra por una lista curada de palabras clave del
  vocabulario real de la planta (ver PALABRAS_CLAVE_PLANTA) -- lo que no
  matchea se cuenta aparte, nunca se descarta en silencio.

Salida: <dist>/ANALISIS_mas_recientes.csv, con una fila por familia de
equipo real: archivo mas reciente (cualquier extension), archivo .L5X mas
reciente (el unico que se puede auditar con nuestro motor), y comparacion
contra el canonico vigente en auto_agustin/ (si existe) con una accion
sugerida.

Uso:
    python analizar_dist_recolectado.py "<ruta a la carpeta dist>"
"""

import os
import re
import sys
import csv
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DIR_CANONICOS = os.path.join(PROJECT_ROOT, "auto_agustin")

PALABRAS_CLAVE_PLANTA = [
    "DIBACCO", "CALD_LA_FLORIDA", "CALD11", "CALD_11", "CALDERAS_8_9_10",
    "CALD_8_9_10", "CENIZAS", "CENTRIFUGA", "TRAPICHE", "USINA_LA_FLORIDA",
    "DESTILERIA", "JW2013", "VINAZA", "FABRICA", "DESFIBRADOR", "TURBINA",
    "MOENDA", "VARIADOR_CENTRIFUGA", "RED_VARIADOR",
]

# Familia -> nombre(s) que puede tener el .L5X canonico vigente en
# auto_agustin/ (varios candidatos porque el canonico puede ser un backup
# .BAK con nombre largo). Se busca por PREFIJO case-insensitive.
FAMILIA_A_CANONICO = {
    "DIBACCO": "DIBACCO",
    "CALD_LA_FLORIDA": "CALD_LA_FLORIDA",
    "CALDERAS_8_9_10_DESAIREADOR": "CALDERAS_8_9_10_DESAIREADOR",
    "CENIZAS2020": "CENIZAS2020",
    "CENTRIFUGA_DE_PRIMERA": "CENTRIFUGA_DE_PRIMERA",
    "TRAPICHE2022": "TRAPICHE2022",
    "USINA_LA_FLORIDA": "USINA_LA_FLORIDA",
    "DESTILERIA": "DESTILERIA_RECUPERADO",
    "JW2013": "JW2013",
    "VINAZA": "VINAZA",
}

_RE_DUP = re.compile(r"_DUP\d+$", re.IGNORECASE)
_RE_COLA_BACKUP = re.compile(r"\.(BAK\d+|DESKTOP-|WIN_)", re.IGNORECASE)


def grupo_base(nombre_carpeta):
    n = nombre_carpeta.upper()
    n = _RE_DUP.sub("", n)
    m = _RE_COLA_BACKUP.search(n)
    if m:
        n = n[: m.start()]
    return n.strip("_- ")


def escanear_dist(dir_dist):
    """Devuelve una lista de dicts: grupo, carpeta_top, archivo, ruta,
    mtime, ext -- uno por cada .ACD/.L5X encontrado en dist/<carpeta>/."""
    filas = []
    for carpeta in sorted(os.listdir(dir_dist)):
        ruta_carpeta = os.path.join(dir_dist, carpeta)
        if not os.path.isdir(ruta_carpeta):
            continue
        for archivo in os.listdir(ruta_carpeta):
            ext = os.path.splitext(archivo)[1].lower()
            if ext not in (".acd", ".l5x"):
                continue
            ruta = os.path.join(ruta_carpeta, archivo)
            try:
                mtime = os.path.getmtime(ruta)
            except OSError:
                continue
            filas.append({
                "grupo": grupo_base(carpeta), "carpeta_top": carpeta,
                "archivo": archivo, "ruta": ruta, "mtime": mtime, "ext": ext,
            })
    return filas


def es_plant_keyword(grupo):
    return any(k in grupo for k in PALABRAS_CLAVE_PLANTA)


def fecha_canonico_actual(familia):
    """mtime del .L5X canonico vigente en auto_agustin/ para esta familia,
    None si no se encuentra (PLC nunca auditado)."""
    prefijo = FAMILIA_A_CANONICO.get(familia)
    if not prefijo or not os.path.isdir(DIR_CANONICOS):
        return None
    candidatos = [f for f in os.listdir(DIR_CANONICOS)
                  if f.lower().endswith(".l5x") and f.upper().startswith(prefijo.upper())]
    if not candidatos:
        return None
    mtimes = [os.path.getmtime(os.path.join(DIR_CANONICOS, f)) for f in candidatos]
    return max(mtimes)


def main():
    dir_dist = sys.argv[1] if len(sys.argv) > 1 else input(
        "Ruta de la carpeta dist a analizar: ").strip().strip('"')
    if not os.path.isdir(dir_dist):
        print(f"No existe: {dir_dist}")
        return

    filas = escanear_dist(dir_dist)
    print(f"Archivos .ACD/.L5X encontrados en {dir_dist}: {len(filas)}")

    reales = [f for f in filas if es_plant_keyword(f["grupo"])]
    ruido = [f for f in filas if not es_plant_keyword(f["grupo"])]
    print(f"  -> vocabulario de planta reconocido: {len(reales)} archivos, "
          f"{len(set(f['grupo'] for f in reales))} familias")
    print(f"  -> sin reconocer (posible ejemplo Rockwell / AOI suelto): "
          f"{len(ruido)} archivos, {len(set(f['grupo'] for f in ruido))} grupos")

    familias = sorted(set(f["grupo"] for f in reales))
    salida_csv = os.path.join(dir_dist, "ANALISIS_mas_recientes.csv")
    campos = ["familia", "archivo_mas_reciente", "fecha_mas_reciente", "extension",
              "archivo_l5x_mas_reciente", "fecha_l5x_mas_reciente",
              "fecha_canonico_vigente", "accion_sugerida", "ruta_mas_reciente"]

    print("\n" + "=" * 100)
    with open(salida_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, delimiter=";")
        w.writeheader()

        for familia in familias:
            del_grupo = [f for f in reales if f["grupo"] == familia]
            mas_reciente = max(del_grupo, key=lambda f: f["mtime"])
            l5x_del_grupo = [f for f in del_grupo if f["ext"] == ".l5x"]
            l5x_mas_reciente = max(l5x_del_grupo, key=lambda f: f["mtime"]) if l5x_del_grupo else None

            fc = fecha_canonico_actual(familia)
            fecha_canonico_str = datetime.fromtimestamp(fc).strftime("%Y-%m-%d %H:%M:%S") if fc else ""

            # IMPORTANTE: esto es solo un triage por FECHA, no por contenido.
            # Ya nos paso (lote NUEVO_RELEVAMIENTO del 06/08) que un .L5X con
            # fecha de export mas nueva resulto ser un SUBCONJUNTO de tags
            # del canonico vigente -- exportado hoy pero desde un .ACD viejo
            # sin tocar hace meses. "Mas nuevo por fecha" NO es lo mismo que
            # "mas completo". Un CANDIDATO a re-auditar siempre debe
            # confirmarse con una comparacion de tags (ver cruzar_planta_viva
            # / la comparacion manual usada en NUEVO_RELEVAMIENTO) antes de
            # reemplazar el canonico.
            if fc is None:
                accion = "EQUIPO NUEVO: no tiene canonico auditado todavia"
            elif l5x_mas_reciente and l5x_mas_reciente["mtime"] > fc + 1:
                accion = "CANDIDATO a revisar: hay un .L5X con fecha mas nueva -- CONFIRMAR con diff de tags antes de reemplazar el canonico"
            elif mas_reciente["mtime"] > fc + 1 and mas_reciente["ext"] == ".acd":
                accion = "PEDIR EXPORT L5X: el .ACD mas nuevo es posterior al canonico y no tiene .L5X"
            else:
                accion = "Al dia (canonico vigente ya es la version mas reciente)"

            w.writerow({
                "familia": familia,
                "archivo_mas_reciente": mas_reciente["archivo"],
                "fecha_mas_reciente": datetime.fromtimestamp(mas_reciente["mtime"]).strftime("%Y-%m-%d %H:%M:%S"),
                "extension": mas_reciente["ext"],
                "archivo_l5x_mas_reciente": l5x_mas_reciente["archivo"] if l5x_mas_reciente else "",
                "fecha_l5x_mas_reciente": (datetime.fromtimestamp(l5x_mas_reciente["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
                                            if l5x_mas_reciente else ""),
                "fecha_canonico_vigente": fecha_canonico_str,
                "accion_sugerida": accion,
                "ruta_mas_reciente": mas_reciente["ruta"],
            })

            print(f"  {familia:30} mas_reciente {mas_reciente['fecha' if False else 'archivo']:45}"
                  f" ({datetime.fromtimestamp(mas_reciente['mtime']):%Y-%m-%d %H:%M})  |  {accion}")

    print("=" * 100)
    print(f"CSV: {salida_csv}")


if __name__ == "__main__":
    main()
