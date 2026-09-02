"""
generar_dashboard_planta.py
=============================
Dashboard final de estado del proyecto: consolida en una sola tabla, por
cada PLC físico que está activamente cruzado contra los Excels de Yanco,
tres cosas que hasta ahora vivian en archivos separados:
  - cuántos tags tiene declarados el programa (.L5X, fuente unica),
  - cuántos de esos tags siguen vivos en el PLC real (Estado_Planta='En Uso'
    en resultados_cruzados/, via cruzar_planta_viva.py),
  - de los que siguen vivos, cuántos ya quedaron estandarizados bajo ISA-5.1
    (auditar_l5x.py). Este ultimo ratio excluye del numerador Y del
    denominador a los tags de "higiene de sistema" (bloques Logix nativos,
    canales de I/O libres) -- estan fuera del alcance de la norma por
    diseño del motor, incluirlos infla artificialmente el % de efectividad.

"Activamente cruzado" = PLCs NO congelados (ver PROYECTOS_CONGELADOS en
cruzar_planta_viva.py). Los congelados (hoy: DESTILERIA_RECUPERADO, vinaza)
quedan afuera del dashboard porque su Estado_Planta es Sin_Relevamiento_Vivo
para el 100% de sus tags -- no hay match de vida que medir todavia.

Genera:
  1. L5X_Auditados_Finales/  -- copia (shutil.copy2, no destructivo) de los
     .L5X canonicos de los PLCs activamente cruzados. Es la "carpeta de
     produccion": el set de fuentes que respalda las metricas del
     dashboard, para que quede trazable de donde salio cada numero.
  2. Dashboard_Planta.csv    -- la tabla completa, en auto_agustin/.
  3. Salida por consola de la misma tabla.

Uso:
    python generar_dashboard_planta.py
"""

import os
import sys
import csv
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import procesar_todos_l5x as orquestador   # noqa: E402
import cruzar_planta_viva as cruce         # noqa: E402

DIR_L5X = orquestador.DIR_L5X
DIR_RESULTADOS = orquestador.DIR_OUT
DIR_CRUZADOS = cruce.DIR_SALIDA
DIR_PRODUCCION = os.path.join(DIR_L5X, "L5X_Auditados_Finales")
RUTA_DASHBOARD = os.path.join(DIR_L5X, "Dashboard_Planta.csv")

CAMPOS = ["PLC", "Tags_Totales", "Match_Vida", "Pct_Match_Vida",
          "Efectividad_Normativa_Pct"]


def proyectos_activos():
    """Nombres de proyecto (PLC canonico) que tienen CSV cruzado Y no
    estan en la lista de congelados de cruzar_planta_viva.py."""
    todos = cruce.descubrir_proyectos(DIR_RESULTADOS)
    return sorted(p for p in todos if p not in cruce.PROYECTOS_CONGELADOS)


def armar_carpeta_produccion(activos, canonicos):
    os.makedirs(DIR_PRODUCCION, exist_ok=True)
    copiados = []
    for proyecto in activos:
        filename = canonicos.get(proyecto)
        if not filename:
            print(f"  [AVISO] {proyecto}: no se encontro su .L5X canonico en {DIR_L5X}, no se copia")
            continue
        origen = os.path.join(DIR_L5X, filename)
        destino = os.path.join(DIR_PRODUCCION, filename)
        shutil.copy2(origen, destino)
        copiados.append(filename)
    return copiados


CLASES_HIGIENE = {"INTERNA_SISTEMA", "RESERVADO", "EQUIPOS_LOGICA"}


def _es_pendiente(fila):
    tn = fila.get("tag_nuevo_propuesto") or ""
    return "PENDIENTE" in tn or "???" in tn


def metricas_por_proyecto(proyecto):
    """Lee los 2 CSV cruzados (mapeo_exitoso + sin_clasificar) de un
    proyecto y devuelve:
      total          -- tags declarados en el .L5X (todas las clases)
      en_uso         -- de esos, cuantos siguen vivos segun Yanco
      en_uso_isa_ok  -- de los vivos, cuantos quedaron ESTANDARIZADOS BAJO
                        LA NORMA ISA especificamente (excluye higiene de
                        sistema / canales de reserva del numerador Y del
                        denominador de este ratio en particular -- mismo
                        criterio que usa procesar_todos_l5x.py para la
                        'Efectividad ISA global', solo que aca re-cortado
                        al subconjunto de tags vivos).
      en_uso_universo_isa -- denominador de ese ratio (vivos, sin higiene).
    """
    total = 0
    en_uso = 0
    en_uso_universo_isa = 0
    en_uso_isa_ok = 0

    for sufijo in ("mapeo_exitoso", "sin_clasificar"):
        path = os.path.join(DIR_CRUZADOS, f"{proyecto}_{sufijo}.csv")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for fila in csv.DictReader(fh, delimiter=";"):
                total += 1
                if fila.get("Estado_Planta") != "En Uso":
                    continue
                en_uso += 1
                if fila.get("clase") in CLASES_HIGIENE:
                    continue  # fuera de alcance ISA (higiene de sistema)
                en_uso_universo_isa += 1
                if not _es_pendiente(fila):
                    en_uso_isa_ok += 1

    return total, en_uso, en_uso_universo_isa, en_uso_isa_ok


def main():
    if not os.path.isdir(DIR_CRUZADOS):
        print(f"No existe {DIR_CRUZADOS} -- correr cruzar_planta_viva.py primero.")
        return

    canonicos, _ = orquestador.seleccionar_canonicos(DIR_L5X)
    activos = proyectos_activos()

    print("=" * 78)
    print("  DASHBOARD FINAL DE PLANTA - Ingenio La Florida")
    print("=" * 78)
    print(f"PLCs activamente cruzados contra Yanco: {len(activos)}  "
          f"(congelados excluidos: {sorted(cruce.PROYECTOS_CONGELADOS)})")

    print("\n--- Paso 1: armando carpeta de produccion L5X_Auditados_Finales/ ---")
    copiados = armar_carpeta_produccion(activos, canonicos)
    print(f"  {len(copiados)} archivo(s) .L5X copiados a {DIR_PRODUCCION}")

    print("\n--- Paso 2: calculando metricas ---")
    filas = []
    tot_tags = tot_en_uso = tot_universo_isa = tot_isa_ok = 0
    for proyecto in activos:
        total, en_uso, universo_isa, isa_ok = metricas_por_proyecto(proyecto)
        pct_match = (100 * en_uso / total) if total else 0.0
        pct_efect = (100 * isa_ok / universo_isa) if universo_isa else 0.0
        filas.append({
            "PLC": proyecto, "Tags_Totales": total, "Match_Vida": en_uso,
            "Pct_Match_Vida": round(pct_match, 1),
            "Efectividad_Normativa_Pct": round(pct_efect, 1),
        })
        tot_tags += total
        tot_en_uso += en_uso
        tot_universo_isa += universo_isa
        tot_isa_ok += isa_ok

    # Fila de totales: agregado PONDERADO de toda la planta (suma de tags,
    # no promedio simple de porcentajes) -- un PLC de 2.500 tags no puede
    # pesar lo mismo que uno de 600 en el numero "global" de la planta.
    pct_match_total = (100 * tot_en_uso / tot_tags) if tot_tags else 0.0
    pct_efect_total = (100 * tot_isa_ok / tot_universo_isa) if tot_universo_isa else 0.0
    fila_total = {
        "PLC": "TOTAL PLANTA (ponderado)", "Tags_Totales": tot_tags,
        "Match_Vida": tot_en_uso, "Pct_Match_Vida": round(pct_match_total, 1),
        "Efectividad_Normativa_Pct": round(pct_efect_total, 1),
    }

    with open(RUTA_DASHBOARD, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS, delimiter=";")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
        w.writerow(fila_total)

    print("\n" + "=" * 100)
    print(f"{'PLC':30} {'Tags totales':>13} {'Match de vida':>14} {'% Match vida':>13} "
          f"{'% Efectividad ISA (sobre vivos)':>33}")
    print("-" * 100)
    for fila in filas:
        print(f"{fila['PLC']:30} {fila['Tags_Totales']:>13} {fila['Match_Vida']:>14} "
              f"{fila['Pct_Match_Vida']:>12.1f}% {fila['Efectividad_Normativa_Pct']:>32.1f}%")
    print("-" * 100)
    print(f"{fila_total['PLC']:30} {fila_total['Tags_Totales']:>13} {fila_total['Match_Vida']:>14} "
          f"{fila_total['Pct_Match_Vida']:>12.1f}% {fila_total['Efectividad_Normativa_Pct']:>32.1f}%")
    print("=" * 100)
    print(f"\nDashboard: {RUTA_DASHBOARD}")
    print(f"Carpeta de produccion: {DIR_PRODUCCION}")


if __name__ == "__main__":
    main()
