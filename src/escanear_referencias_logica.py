"""
escanear_referencias_logica.py
================================
Modulo COMPLEMENTARIO de auditoria (no reemplaza a auditar_l5x.py ni a
cruzar_planta_viva.py; corre despues de ambos). Objetivo: distinguir un
tag "vivo en la tabla de memoria del PLC" (lo que ya confirma
Estado_Planta='En Uso' via el Excel de Yanco) de un tag "referenciado por
algun rung/diagrama FBD activo" -- que es lo unico que prueba que la
logica realmente lo usa.

Para cada PLC canonico, escanea TODA la logica de programa contenida en
su .L5X: texto de rungs RLL (Routine > Rung > Text), diagramas de bloques
FBD (Routine > Sheet > IRef/ORef/Block, con su Wire de interconexion), y
en general cualquier nodo de logica dentro de una <Routine> que traiga
texto de programacion u operandos. Arma con eso el "vocabulario de
logica" del controlador: el set de identificadores efectivamente
mencionados en algun lado ejecutable.

Reutiliza extraer_tags_referenciados() de auditar_l5x.py -- la misma
funcion que el motor principal ya usa (validada) para la herencia de area
por Scope -- en vez de duplicar el parseo RLL/FBD.

Cuidado con los sufijos de UDT (Rockwell): un tag complejo se referencia
en logica con sufijo de miembro por punto (Bomba_Agua.Cmd_Run) o indice de
arreglo (Tag[3].Member).
  - En texto RLL (rungs), extraer_tags_referenciados() ya lo resuelve solo:
    tokeniza con una regex de identificador que corta en '.', '[', '(',
    etc. -- "XIC(Bomba_Agua.Cmd_Run)" separa en tokens "BOMBA_AGUA" y
    "CMD_RUN", la raiz queda sola en el set.
  - En operandos FBD (IRef/ORef/Block), el atributo Operand se toma
    COMPLETO como un solo token (ej. "BOMBA_AGUA.CMD_RUN"). Para que la
    raiz "BOMBA_AGUA" tambien cuente (y no se marque como falso negativo),
    este modulo agrega ADEMAS, para cada Operand con '.' o '[', la porcion
    anterior al primer separador como token propio.

Escribe la columna Referenciado_En_Logica ('Si'/'No') directamente en los
CSV de auto_agustin/resultados_cruzados/ (los mismos que ya tienen
Estado_Planta / IP_Fisica del cruce con los Excel de Yanco).

Uso:
    python escanear_referencias_logica.py
"""

import os
import re
import csv
import sys
import glob
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import auditar_l5x as base                    # noqa: E402
import procesar_todos_l5x as orquestador       # noqa: E402

PROJECT_ROOT = orquestador.PROJECT_ROOT
DIR_L5X = orquestador.DIR_L5X
DIR_SALIDA = os.path.join(DIR_L5X, "resultados_cruzados")

_RE_SUFIJO_CSV = re.compile(r"_(mapeo_exitoso|sin_clasificar)\.csv$", re.IGNORECASE)
_RE_RAIZ_OPERANDO = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*")

COL_NUEVA = "Referenciado_En_Logica"
SI, NO = "Si", "No"


# ------------------------------------------------------------------
def raiz_de_operando(operando):
    """Raiz de un Operand FBD antes del primer separador ('.', '[', etc.):
    resuelve miembros de UDT y elementos de arreglo referenciados en
    diagramas de bloques."""
    m = _RE_RAIZ_OPERANDO.match(operando)
    return m.group(0).upper() if m else None


def vocabulario_logica(path_l5x):
    """Set de identificadores (raiz) referenciados en TODA la logica del
    controlador: texto RLL de rungs + operandos FBD (IRef/ORef/Block, y
    cualquier otro nodo con atributo Operand), de cualquier Routine
    dentro de cualquier Program."""
    tree = ET.parse(path_l5x)
    root = tree.getroot()
    vocab = set()

    for routine_el in root.iter("Routine"):
        # Motor validado: texto de rungs RLL (ya tokenizado, corta en '.')
        # + Operand de IRef/ORef/Block (FBD), completo.
        vocab |= base.extraer_tags_referenciados(routine_el)

        # Refuerzo anti-falso-negativo: raiz de CUALQUIER Operand con
        # sufijo de UDT/arreglo dentro de esa Routine (cubre nodos FBD
        # que extraer_tags_referenciados no haya enumerado por nombre).
        for el in routine_el.iter():
            op = el.get("Operand")
            if op:
                raiz = raiz_de_operando(op)
                if raiz:
                    vocab.add(raiz)

    return vocab


# ------------------------------------------------------------------
def descubrir_proyectos_cruzados(dir_salida):
    proyectos = set()
    for f in os.listdir(dir_salida):
        m = _RE_SUFIJO_CSV.search(f)
        if m:
            proyectos.add(f[: m.start()])
    return proyectos


def enriquecer_csv(path_csv, vocab):
    with open(path_csv, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        campos_entrada = reader.fieldnames
        filas = list(reader)

    referenciados = 0
    for fila in filas:
        tag_norm = (fila.get("tag_viejo") or "").strip().upper()
        # mismo criterio de raiz que en los operandos FBD: si el propio
        # tag_viejo trae sufijo de UDT (poco comun en esta columna, pero
        # por consistencia se aplica igual), se compara por su raiz.
        raiz = raiz_de_operando(tag_norm) or tag_norm
        if tag_norm in vocab or raiz in vocab:
            fila[COL_NUEVA] = SI
            referenciados += 1
        else:
            fila[COL_NUEVA] = NO

    campos_salida = campos_entrada + [COL_NUEVA]
    with open(path_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos_salida, delimiter=";")
        w.writeheader()
        w.writerows(filas)

    return len(filas), referenciados


# ------------------------------------------------------------------
def main():
    if not os.path.isdir(DIR_SALIDA):
        print(f"No existe: {DIR_SALIDA} (corre primero cruzar_planta_viva.py)")
        return

    canonicos, _ = orquestador.seleccionar_canonicos(DIR_L5X)
    proyectos = sorted(descubrir_proyectos_cruzados(DIR_SALIDA))

    print("=" * 78)
    print("  ESCANEO PROFUNDO DE LOGICA - deteccion de tags 'Zombi'")
    print("=" * 78)

    total_filas = 0
    total_referenciados = 0
    total_en_uso = 0
    total_zombi = 0
    filas_por_proyecto = []

    for proyecto in proyectos:
        filename = canonicos.get(proyecto)
        if not filename:
            print(f"  [SALTEADO] {proyecto:26} sin .L5X canonico localizable")
            continue

        path_l5x = os.path.join(DIR_L5X, filename)
        vocab = vocabulario_logica(path_l5x)

        tot_proj = 0
        ref_proj = 0
        for sufijo in ("mapeo_exitoso", "sin_clasificar"):
            nombre = f"{proyecto}_{sufijo}.csv"
            path_csv = os.path.join(DIR_SALIDA, nombre)
            if not os.path.isfile(path_csv):
                continue
            n, r = enriquecer_csv(path_csv, vocab)
            tot_proj += n
            ref_proj += r

        # Zombi = En Uso segun planta viva, pero NO referenciado en logica.
        zombi_proj = 0
        en_uso_proj = 0
        for sufijo in ("mapeo_exitoso", "sin_clasificar"):
            path_csv = os.path.join(DIR_SALIDA, f"{proyecto}_{sufijo}.csv")
            if not os.path.isfile(path_csv):
                continue
            with open(path_csv, "r", encoding="utf-8-sig", newline="") as fh:
                for fila in csv.DictReader(fh, delimiter=";"):
                    if fila.get("Estado_Planta") == "En Uso":
                        en_uso_proj += 1
                        if fila.get(COL_NUEVA) == NO:
                            zombi_proj += 1

        pct = (100 * ref_proj / tot_proj) if tot_proj else 0.0
        pct_zombi = (100 * zombi_proj / en_uso_proj) if en_uso_proj else 0.0
        print(f"  [OK] {proyecto:26} vocab_logica {len(vocab):6} | "
              f"tags {tot_proj:5} -> referenciados {ref_proj:5} ({pct:5.1f}%) | "
              f"ZOMBI {zombi_proj:5}/{en_uso_proj:5} ({pct_zombi:4.1f}% de los En Uso)")

        total_filas += tot_proj
        total_referenciados += ref_proj
        total_en_uso += en_uso_proj
        total_zombi += zombi_proj
        filas_por_proyecto.append((proyecto, tot_proj, ref_proj, en_uso_proj, zombi_proj))

    print("=" * 78)
    print("  REPORTE ZOMBI GLOBAL")
    print("=" * 78)
    print(f"  Tags procesados (con columna nueva)         : {total_filas}")
    print(f"  Referenciados en logica (Si)                : {total_referenciados}"
          + (f"  ({100*total_referenciados/total_filas:.1f}%)" if total_filas else ""))
    print("-" * 78)
    print(f"  Universo 'En Uso' (segun Excel Yanco)       : {total_en_uso}")
    print(f"  >> ZOMBI (En Uso + NO referenciado en logica): {total_zombi}"
          + (f"  ({100*total_zombi/total_en_uso:.1f}% de los En Uso)" if total_en_uso else ""))
    print("=" * 78)
    print(f"  CSV actualizados en: {DIR_SALIDA}")


if __name__ == "__main__":
    main()
