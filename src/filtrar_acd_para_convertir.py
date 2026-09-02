"""
filtrar_acd_para_convertir.py
================================
Tercera etapa del flujo de recoleccion (ver recolector_fuentes_plc.py y
analizar_dist_recolectado.py). Arma la carpeta de trabajo "ACD_Para_Convertir"
con SOLO el codigo fresco (Julio/Agosto 2026 en adelante) para que el
usuario lo abra en Studio 5000 y lo exporte a .L5X -- y separa aparte, sin
copiar, las familias cuyo archivo mas reciente es de 2023-2025, para que
no se auditen bajo ISA-5.1 sin antes verificarlas contra la planta viva.

Regla de negocio (decidida explicitamente por el Ingenio, 13/08/2026):
  1. Filtro Julio/Agosto 2026 (prioridad absoluta): se copia a
     ACD_Para_Convertir/ CUALQUIER archivo .ACD/.L5X individual cuya fecha
     de modificacion (real, preservada por shutil.copy2 desde el disco
     original) caiga entre el 01/07/2026 y HOY. Es un filtro por archivo,
     no por familia: si una familia tiene 3 backups de 2025 y 1 de agosto
     2026, SOLO se copia el de agosto -- los 3 viejos quedan atras.
  2. Cuarentena: una familia entera (ver agrupamiento en
     analizar_dist_recolectado.grupo_base) cae en cuarentena cuando NINGUNO
     de sus archivos tiene fecha dentro de la ventana Jul/Ago 2026 -- es
     decir, su version mas reciente es de 2023/2024/2025. Esas familias NO
     se copian a ACD_Para_Convertir. Se listan en
     REQUIEREN_VALIDACION_YANCO.csv, una fila por familia, con su archivo
     mas reciente y la ruta de origen para exportarlo a mano.
  3. Estrategia de validacion viva: el paso siguiente para cada familia en
     cuarentena NO es taguear directo -- es exportar su .ACD a .L5X a mano
     y correr cruzar_planta_viva.py contra los Excels de Yanco del 07/08.
     Si las variables viven en el PLC real, se re-evalua incorporarla; si
     no, se descarta. Este script no hace ese cruce, solo prepara la lista.

No destructivo: todo se copia con shutil.copy2 (preserva fecha original).
Nada se mueve ni se borra del "dist" de origen.

Uso:
    python filtrar_acd_para_convertir.py "<ruta a la carpeta dist>" "<ruta ACD_Para_Convertir>"
"""

import os
import sys
import csv
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import analizar_dist_recolectado as motor  # noqa: E402  (reutiliza escaneo/agrupado/filtro de ruido ya validados)

# Ventana de "codigo fresco": desde el 1 de julio de 2026 hasta ahora.
FECHA_CORTE = datetime(2026, 7, 1).timestamp()


def clasificar(dir_dist):
    """Devuelve (frescos: [dict archivo], cuarentena: {familia: dict del
    archivo mas reciente de esa familia})."""
    filas = motor.escanear_dist(dir_dist)
    reales = [f for f in filas if motor.es_plant_keyword(f["grupo"])]

    frescos = [f for f in reales if f["mtime"] >= FECHA_CORTE]

    familias = sorted(set(f["grupo"] for f in reales))
    cuarentena = {}
    for familia in familias:
        del_grupo = [f for f in reales if f["grupo"] == familia]
        tiene_fresco = any(f["mtime"] >= FECHA_CORTE for f in del_grupo)
        if not tiene_fresco:
            cuarentena[familia] = max(del_grupo, key=lambda f: f["mtime"])

    return frescos, cuarentena


def copiar_frescos(frescos, dir_destino):
    os.makedirs(dir_destino, exist_ok=True)
    ruta_csv = os.path.join(dir_destino, "trazabilidad_ACD_Para_Convertir.csv")
    campos = ["familia", "archivo", "fecha_modificacion_original", "ruta_origen"]

    copiados = 0
    errores = 0
    with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, delimiter=";")
        w.writeheader()
        for f in sorted(frescos, key=lambda x: (x["grupo"], -x["mtime"])):
            carpeta_familia = os.path.join(dir_destino, f["grupo"])
            os.makedirs(carpeta_familia, exist_ok=True)
            destino = os.path.join(carpeta_familia, f["archivo"])
            # Evita pisar si dos rutas de origen distintas comparten
            # nombre de archivo dentro de la misma familia (poco comun,
            # pero posible tras fusionar corridas).
            if os.path.exists(destino):
                base, ext = os.path.splitext(f["archivo"])
                destino = os.path.join(carpeta_familia, f"{base}__{int(f['mtime'])}{ext}")
            try:
                shutil.copy2(f["ruta"], destino)
            except (PermissionError, OSError, shutil.Error) as e:
                errores += 1
                print(f"  [ERROR copiando] {f['ruta']}: {e}")
                continue
            copiados += 1
            w.writerow({
                "familia": f["grupo"],
                "archivo": os.path.basename(destino),
                "fecha_modificacion_original": datetime.fromtimestamp(f["mtime"]).strftime("%Y-%m-%d %H:%M:%S"),
                "ruta_origen": f["ruta"],
            })
    return copiados, errores, ruta_csv


def escribir_cuarentena(cuarentena, dir_destino):
    os.makedirs(dir_destino, exist_ok=True)
    ruta_csv = os.path.join(dir_destino, "REQUIEREN_VALIDACION_YANCO.csv")
    campos = ["familia", "archivo_mas_reciente", "fecha_mas_reciente",
              "antiguedad_aprox", "ruta_origen", "proximo_paso"]

    ahora = datetime.now()
    with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, delimiter=";")
        w.writeheader()
        for familia in sorted(cuarentena):
            f = cuarentena[familia]
            fecha_dt = datetime.fromtimestamp(f["mtime"])
            meses = (ahora.year - fecha_dt.year) * 12 + (ahora.month - fecha_dt.month)
            w.writerow({
                "familia": familia,
                "archivo_mas_reciente": f["archivo"],
                "fecha_mas_reciente": fecha_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "antiguedad_aprox": f"~{meses} meses",
                "ruta_origen": f["ruta"],
                "proximo_paso": "Exportar a .L5X manualmente y cruzar con cruzar_planta_viva.py "
                                 "contra los Excel de Yanco del 07/08/2026 antes de taguear",
            })
    return ruta_csv


def main():
    dir_dist = sys.argv[1] if len(sys.argv) > 1 else input("Ruta de la carpeta dist: ").strip().strip('"')
    dir_destino = sys.argv[2] if len(sys.argv) > 2 else input(
        "Ruta de ACD_Para_Convertir [Enter = ./ACD_Para_Convertir]: ").strip().strip('"') or "ACD_Para_Convertir"

    if not os.path.isdir(dir_dist):
        print(f"No existe: {dir_dist}")
        return

    print("=" * 78)
    print("  FILTRO DE CODIGO FRESCO (Jul/Ago 2026) -> ACD_Para_Convertir")
    print("=" * 78)
    print(f"Corte de frescura: {datetime.fromtimestamp(FECHA_CORTE):%Y-%m-%d} en adelante")

    frescos, cuarentena = clasificar(dir_dist)
    print(f"\nArchivos individuales frescos (Jul/Ago 2026): {len(frescos)}")
    print(f"Familias en cuarentena (2023-2025, sin nada fresco): {len(cuarentena)}")

    copiados, errores, ruta_frescos_csv = copiar_frescos(frescos, dir_destino)
    ruta_cuarentena_csv = escribir_cuarentena(cuarentena, dir_destino)

    print("\n--- Copiados a ACD_Para_Convertir ---")
    familias_frescas = sorted(set(f["grupo"] for f in frescos))
    for fam in familias_frescas:
        n = sum(1 for f in frescos if f["grupo"] == fam)
        print(f"  {fam:35} {n} archivo(s)")

    print("\n--- En cuarentena (NO copiados, requieren validacion Yanco) ---")
    for fam in sorted(cuarentena):
        f = cuarentena[fam]
        print(f"  {fam:35} mas reciente: {f['archivo']} ({datetime.fromtimestamp(f['mtime']):%Y-%m-%d})")

    print("\n" + "=" * 78)
    print(f"  Copiados: {copiados}   Errores: {errores}")
    print(f"  Carpeta de trabajo: {os.path.abspath(dir_destino)}")
    print(f"  Trazabilidad de lo copiado: {ruta_frescos_csv}")
    print(f"  Lista de cuarentena: {ruta_cuarentena_csv}")
    print("=" * 78)


if __name__ == "__main__":
    main()
