"""Diff reproducible entre la propuesta v1 y la v2 (entregable 1).

Salida: exports/diff_propuesta_v1_v2.csv (una fila por columna y por tag afectado).
Sin argumentos. Solo lee los dos CSV. No toca SQLite.
"""

from __future__ import annotations

import csv
import sys
from collections import OrderedDict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
V1 = RAIZ / "exports" / "propuesta_numeracion_3_lazos_v1.csv"
V2 = RAIZ / "exports" / "propuesta_numeracion_3_lazos.csv"
SALIDA = RAIZ / "exports" / "diff_propuesta_v1_v2.csv"


def leer(ruta: Path) -> tuple[list[str], "OrderedDict[str, dict]"]:
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        columnas = list(lector.fieldnames or [])
        filas = OrderedDict((fila["Tag_Propuesto"], fila) for fila in lector)
    return columnas, filas


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Diff entre dos versiones de la propuesta (solo lee CSV).")
    parser.add_argument("--a", default=str(V1), help="Version anterior (por defecto v1).")
    parser.add_argument("--b", default=str(V2), help="Version nueva (por defecto la vigente).")
    parser.add_argument("--salida", default=None, help="CSV de salida del diff.")
    args = parser.parse_args(argv)

    ruta_a, ruta_b = Path(args.a), Path(args.b)
    salida = Path(args.salida) if args.salida else SALIDA
    if args.salida is None and ruta_a != V1:
        salida = SALIDA.with_name("diff_propuesta_%s_%s.csv" % (ruta_a.stem.split("_")[-1], ruta_b.stem.split("_")[-1]))

    columnas_v1, filas_v1 = leer(ruta_a)
    columnas_v2, filas_v2 = leer(ruta_b)

    agregadas = [c for c in columnas_v2 if c not in columnas_v1]
    eliminadas = [c for c in columnas_v1 if c not in columnas_v2]
    comunes = [c for c in columnas_v1 if c in columnas_v2]

    filas_diff = []
    for columna in comunes:
        afectadas = [(tag, filas_v1[tag][columna], filas_v2[tag][columna])
                     for tag in filas_v1 if filas_v1[tag][columna] != filas_v2[tag][columna]]
        if not afectadas:
            continue
        for tag, antes, despues in afectadas:
            filas_diff.append({
                "Columna": columna, "Tipo": "MODIFICADA", "Tag_Propuesto": tag,
                "Valor_V1": antes, "Valor_V2": despues,
            })
    for columna in agregadas:
        for tag in filas_v2:
            filas_diff.append({
                "Columna": columna, "Tipo": "AGREGADA", "Tag_Propuesto": tag,
                "Valor_V1": "", "Valor_V2": filas_v2[tag][columna],
            })

    with open(salida, "w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=["Columna", "Tipo", "Tag_Propuesto", "Valor_V1", "Valor_V2"],
                                 delimiter=";", lineterminator="\n")
        escritor.writeheader()
        for fila in filas_diff:
            escritor.writerow(fila)

    print("Comparacion: %s  ->  %s" % (ruta_a.name, ruta_b.name))

    print("Columnas v1: %d | v2: %d" % (len(columnas_v1), len(columnas_v2)))
    print("  agregadas : %s" % (", ".join(agregadas) or "ninguna"))
    print("  eliminadas: %s" % (", ".join(eliminadas) or "ninguna"))
    print("  comunes   : %d" % len(comunes))
    print()
    print("Columnas comunes MODIFICADAS:")
    modificadas = []
    for fila in filas_diff:
        if fila["Tipo"] == "MODIFICADA" and fila["Columna"] not in modificadas:
            modificadas.append(fila["Columna"])
    for columna in modificadas:
        afectadas = [f for f in filas_diff if f["Columna"] == columna and f["Tipo"] == "MODIFICADA"]
        print("  - %s (%d filas)" % (columna, len(afectadas)))
        for fila in afectadas[:1]:
            print("      v1: %s" % (fila["Valor_V1"][:150] or "(vacio)"))
            print("      v2: %s" % (fila["Valor_V2"][:150] or "(vacio)"))
    print()
    print("Columnas NUEVAS (tipo AGREGADA):")
    for columna in agregadas:
        ejemplo = next(f["Valor_V2"] for f in filas_diff if f["Columna"] == columna)
        print("  + %-32s ej: %s" % (columna, ejemplo[:100]))
    print()
    print("Ninguna columna de NUMERACION cambio (083 / 081 / 082 intactos): %s"
          % all(filas_v1[t]["Tag_Propuesto"] == filas_v2[t]["Tag_Propuesto"]
                and filas_v1[t]["Numero_Propuesto"] == filas_v2[t]["Numero_Propuesto"] for t in filas_v1))
    print("[OK] Diff: %s (%d filas)" % (salida, len(filas_diff)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
