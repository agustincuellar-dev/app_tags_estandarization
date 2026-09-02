"""
recolector_fuentes_plc.py
==========================
Recolector y Organizador de codigo fuente de PLC, para correr en cada PC
de ingenieria dispersa (5 equipos hoy). Objetivo: centralizar en un
repositorio temporal todos los .ACD / .L5X que haya en el disco, sin
tocar el original, clasificados por equipo/PLC real y con trazabilidad
completa de donde salio cada copia -- insumo para un futuro sistema de
control de versiones tipo FactoryTalk AssetCentre.

Es un script STANDALONE (solo libreria estandar de Python: os, re, shutil,
csv, sys, datetime) para poder copiarlo y correrlo en cualquier PC de
ingenieria sin instalar dependencias.

Reglas de diseno (pedidas explicitamente):
  1. Deep scan recursivo desde un directorio que el usuario ingresa
     (ej. C:\\ o D:\\), ignorando carpetas de sistema operativo.
  2. NO DESTRUCTIVO: nunca se mueve ni se borra nada del origen. Todo se
     copia con shutil.copy2 (preserva fecha de modificacion original --
     esa fecha es la metrica de verdad para decidir despues cual version
     es la mas nueva).
  3. Clasificacion inteligente: se limpia el nombre de archivo de sufijos
     basura (versiones, fechas, "final", "viejo", backups de Rockwell,
     etc.) para agrupar todas las copias del mismo equipo en una misma
     subcarpeta de destino.
  4. Trazabilidad: un trazabilidad_extraccion.csv en el destino, con
     Nombre_Archivo_Destino, Nombre_Equipo_Clasificado,
     Fecha_Modificacion_Original, Ruta_Absoluta_Original -- por cada
     archivo copiado.

Manejo de errores: un archivo bloqueado por permisos, en uso por Studio
5000, o una carpeta sin acceso NUNCA frena el barrido completo. Cada
fallo se seteos aparte, no se pierde silenciosamente ni se cae el script
(ver errores_extraccion.log en el destino).

Uso:
    python recolector_fuentes_plc.py
    (pide interactivamente el directorio de inicio y el de destino)
"""

import os
import re
import csv
import sys
import shutil
from datetime import datetime

# ------------------------------------------------------------------
# Carpetas de sistema operativo a ignorar durante el deep scan (match
# EXACTO del nombre de carpeta, case-insensitive -- no substring, para no
# saltarnos por error una carpeta legitima del Ingenio que contenga una de
# estas palabras).
CARPETAS_SISTEMA_IGNORAR = {
    "windows", "windows.old", "program files", "program files (x86)",
    "programdata", "$recycle.bin", "system volume information",
    "recovery", "perflogs", "msocache", "boot", "config.msi",
    "documents and settings", "$windows.~bt", "$windows.~ws",
    "intel", "nvidia", "amd", "drivers", "dell", "hp",
    # Detectado en la corrida real del 06-07/08/2026 sobre 4 PCs: sin este
    # filtro, la biblioteca de ejemplos que instala Studio 5000 (samples,
    # AOIs de demo, DriveLogix) se cuela en el barrido y ensucia el
    # resultado con cientos de archivos que no son PLCs de la planta.
    "samples", "rockwell software", "studio 5000", "rslogix 5000",
    "factorytalk", "add-on instructions", "aoi library",
}

EXTENSIONES_VALIDAS = (".acd", ".l5x")

CAMPOS_CSV = ["Nombre_Archivo_Destino", "Nombre_Equipo_Clasificado",
              "Fecha_Modificacion_Original", "Ruta_Absoluta_Original", "Corrida"]


# ------------------------------------------------------------------
# Limpieza de nombre -> nombre de equipo real
# ------------------------------------------------------------------
# Sufijos de backup automatico de Studio 5000, ej.
# 'TRAPICHE2022.DESKTOP-1LCQM96.PC-STDIO500v33.BAK010' -> se corta desde
# el primer '.DESKTOP-' (todo lo que sigue es metadata de la maquina que
# hizo el backup, no del equipo).
_RE_BACKUP_STUDIO5000 = re.compile(r"\.DESKTOP-.*$", re.IGNORECASE)

# Fechas incrustadas en el nombre: YYYYMMDD, YYYY-MM-DD / YYYY_MM_DD,
# DD-MM-YYYY / DD_MM_YYYY, y timestamps largos tipo YYYYMMDD_HHMMSS.
_RE_FECHAS = [
    re.compile(r"\d{8}_\d{6}"),                    # 20260806_085228
    re.compile(r"\d{4}[-_]\d{2}[-_]\d{2}"),         # 2026-08-06 / 2026_08_06
    re.compile(r"\d{2}[-_]\d{2}[-_]\d{4}"),         # 06-08-2026 / 06_08_2026
    re.compile(r"(?<!\d)\d{8}(?!\d)"),              # 20260806 / 06082026 sueltos
    re.compile(r"(?<!\d)\d{6}(?!\d)"),              # 060826 (DDMMAA corto)
]

# Duplicado tipico de Windows al copiar: "archivo (2).L5X"
_RE_COPIA_WINDOWS = re.compile(r"\s*\(\d+\)$")

# Palabras sueltas (separadas por _, -, espacio o pegadas a un separador)
# que son "basura" de versionado manual, no parte del nombre del equipo.
# Incluye variantes ES/PT vistas en la planta.
PALABRAS_BASURA = {
    "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9",
    "ver1", "ver2", "ver3", "version1", "version2",
    "final", "definitivo", "definitiva", "ultimo", "ultima", "last",
    "viejo", "vieja", "old", "antigua", "antiguo",
    "nuevo", "nueva", "new",
    "copia", "copy", "duplicado", "duplicate",
    "bak", "backup", "respaldo", "resguardo",
    "temp", "tmp", "test", "prueba", "borrar", "descartar",
    "recuperado", "recovered", "recuperada",
    "original", "actual", "vigente",
}

_RE_SEPARADORES = re.compile(r"[_\-\s]+")


def limpiar_nombre_equipo(nombre_archivo):
    """De un nombre de archivo .ACD/.L5X (con o sin extension) extrae el
    nombre del equipo/PLC real, sacando sufijos de backup de Studio 5000,
    fechas, duplicados de Windows tipo '(2)' y palabras sueltas de
    versionado manual (v2, final, viejo, copia, etc.).

    No es magia: es un pipeline de limpieza best-effort. Si el nombre
    limpio queda vacio (archivo nombrado solo con basura, ej.
    '20260806_v2.L5X'), se usa 'SIN_CLASIFICAR' como equipo y la fila del
    CSV de trazabilidad sigue teniendo la ruta original completa -- nada
    se pierde, solo queda pendiente de que un humano lo agrupe a mano.
    """
    base = os.path.splitext(nombre_archivo)[0]

    base = _RE_BACKUP_STUDIO5000.sub("", base)
    base = _RE_COPIA_WINDOWS.sub("", base)
    for patron in _RE_FECHAS:
        base = patron.sub("", base)

    tokens = [t for t in _RE_SEPARADORES.split(base) if t]
    tokens_limpios = [t for t in tokens if t.lower() not in PALABRAS_BASURA]

    equipo = "_".join(tokens_limpios).strip("_- ")
    equipo = equipo.upper()

    return equipo if equipo else "SIN_CLASIFICAR"


# ------------------------------------------------------------------
def debe_ignorar_carpeta(nombre_carpeta):
    return nombre_carpeta.strip().lower() in CARPETAS_SISTEMA_IGNORAR


def nombre_destino_unico(carpeta_destino, nombre_archivo, usados):
    """Evita pisar un archivo ya copiado en la misma subcarpeta cuando dos
    PCs distintas tienen un archivo con el mismo nombre. El nombre real
    de origen no se pierde -- queda en el CSV de trazabilidad de todas
    formas, asi que el nombre de destino solo necesita ser unico, no
    'lindo'."""
    clave = (carpeta_destino, nombre_archivo.lower())
    if clave not in usados:
        usados[clave] = 0
        return nombre_archivo
    usados[clave] += 1
    base, ext = os.path.splitext(nombre_archivo)
    return f"{base}__dup{usados[clave]}{ext}"


# ------------------------------------------------------------------
def recolectar(directorio_inicio, directorio_destino):
    os.makedirs(directorio_destino, exist_ok=True)
    destino_abs = os.path.abspath(directorio_destino)

    ruta_csv = os.path.join(directorio_destino, "trazabilidad_extraccion.csv")
    ruta_log_errores = os.path.join(directorio_destino, "errores_extraccion.log")

    encontrados = 0
    copiados = 0
    errores = 0
    equipos = {}
    nombres_usados = {}

    id_corrida = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Modo APPEND, no 'w': si esta misma carpeta destino ya tiene
    # trazabilidad de una corrida anterior (ej. se reutiliza un pendrive
    # entre PCs, o se vuelve a correr sobre el mismo destino), la corrida
    # nueva se suma en vez de borrar el historial de la anterior. La
    # columna 'Corrida' distingue de que pasada vino cada fila cuando se
    # fusionan varios destinos a mano despues.
    csv_existe_con_contenido = os.path.isfile(ruta_csv) and os.path.getsize(ruta_csv) > 0
    with open(ruta_csv, "a", newline="", encoding="utf-8-sig") as f_csv, \
         open(ruta_log_errores, "a", encoding="utf-8") as f_log:

        writer = csv.DictWriter(f_csv, fieldnames=CAMPOS_CSV, delimiter=";")
        if not csv_existe_con_contenido:
            writer.writeheader()

        f_log.write(f"\n=== Corrida {id_corrida} ===\n")
        f_log.write(f"Inicio: {directorio_inicio}  Destino: {directorio_destino}\n")

        def _on_error_walk(err):
            # Carpeta sin permiso de listado: se anota y se sigue.
            nonlocal errores
            errores += 1
            f_log.write(f"[ACCESO DENEGADO carpeta] {err}\n")

        for carpeta_actual, subcarpetas, archivos in os.walk(
                directorio_inicio, topdown=True, onerror=_on_error_walk):

            # Poda del arbol ANTES de bajar: carpetas de sistema y la
            # propia carpeta de destino (evita bucle si el destino queda
            # dentro del arbol que se esta escaneando).
            subcarpetas[:] = [
                d for d in subcarpetas
                if not debe_ignorar_carpeta(d)
                and os.path.abspath(os.path.join(carpeta_actual, d)) != destino_abs
            ]

            for nombre in archivos:
                if not nombre.lower().endswith(EXTENSIONES_VALIDAS):
                    continue
                encontrados += 1
                ruta_origen = os.path.join(carpeta_actual, nombre)

                try:
                    ruta_origen_abs = os.path.abspath(ruta_origen)
                    mtime = os.path.getmtime(ruta_origen)
                    fecha_mod = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                except OSError as e:
                    errores += 1
                    f_log.write(f"[NO SE PUDO LEER METADATA] {ruta_origen}: {e}\n")
                    continue

                equipo = limpiar_nombre_equipo(nombre)
                carpeta_equipo = os.path.join(directorio_destino, equipo)

                try:
                    os.makedirs(carpeta_equipo, exist_ok=True)
                    nombre_final = nombre_destino_unico(carpeta_equipo, nombre, nombres_usados)
                    ruta_destino = os.path.join(carpeta_equipo, nombre_final)

                    # shutil.copy2: copia datos + metadata (incluye
                    # st_mtime) -- la fecha de modificacion original queda
                    # intacta en el archivo copiado, tal como pide la
                    # regla de oro.
                    shutil.copy2(ruta_origen, ruta_destino)

                except (PermissionError, OSError, shutil.Error) as e:
                    # Tipico: archivo abierto en Studio 5000 en ese
                    # momento, o sin permisos de lectura. Se registra y se
                    # sigue con el resto -- nunca frena el barrido.
                    errores += 1
                    f_log.write(f"[NO SE PUDO COPIAR] {ruta_origen}: {e}\n")
                    continue

                writer.writerow({
                    "Nombre_Archivo_Destino": nombre_final,
                    "Nombre_Equipo_Clasificado": equipo,
                    "Fecha_Modificacion_Original": fecha_mod,
                    "Ruta_Absoluta_Original": ruta_origen_abs,
                    "Corrida": id_corrida,
                })
                copiados += 1
                equipos.setdefault(equipo, 0)
                equipos[equipo] += 1
                print(f"  [OK] {equipo:28} <- {ruta_origen}")

    return {
        "encontrados": encontrados, "copiados": copiados, "errores": errores,
        "equipos": equipos, "ruta_csv": ruta_csv, "ruta_log_errores": ruta_log_errores,
    }


# ------------------------------------------------------------------
def main():
    print("=" * 70)
    print("  RECOLECTOR Y ORGANIZADOR DE FUENTES PLC - Ingenio La Florida")
    print("=" * 70)

    directorio_inicio = input(
        r"Directorio origen a escanear (ej. C:\ o D:\): "
    ).strip().strip('"')
    if not directorio_inicio:
        print("No se ingreso un directorio. Se cancela.")
        return
    if not os.path.isdir(directorio_inicio):
        print(f"El directorio no existe o no es accesible: {directorio_inicio}")
        return

    directorio_destino = input(
        r"Directorio destino [Enter = C:\Repositorio_Ingenio_Temp]: "
    ).strip().strip('"') or r"C:\Repositorio_Ingenio_Temp"

    print(f"\nEscaneando {directorio_inicio} ... (puede tardar varios minutos)\n")
    resumen = recolectar(directorio_inicio, directorio_destino)

    print("\n" + "=" * 70)
    print("  RESUMEN")
    print("=" * 70)
    print(f"  Archivos .ACD/.L5X encontrados : {resumen['encontrados']}")
    print(f"  Copiados exitosamente          : {resumen['copiados']}")
    print(f"  Errores (permisos/bloqueos)    : {resumen['errores']}")
    print(f"  Equipos distintos clasificados : {len(resumen['equipos'])}")
    print("-" * 70)
    for equipo, n in sorted(resumen["equipos"].items(), key=lambda x: -x[1]):
        print(f"    {equipo:30} {n:4} archivo(s)")
    print("-" * 70)
    print(f"  Trazabilidad: {resumen['ruta_csv']}")
    if resumen["errores"]:
        print(f"  Detalle de errores: {resumen['ruta_log_errores']}")


if __name__ == "__main__":
    # Envoltura a prueba de cierre-de-golpe: si algo no contemplado
    # revienta (ej. una excepcion no capturada mas arriba), igual se
    # imprime el traceback y se espera Enter antes de cerrar la consola.
    # Critico para el .exe compilado: sin esto, un doble-clic que termina
    # en excepcion cierra la ventana en una fraccion de segundo y no da
    # tiempo a leer nada.
    try:
        main()
    except Exception:
        import traceback
        print("\n" + "=" * 70)
        print("  OCURRIO UN ERROR INESPERADO")
        print("=" * 70)
        traceback.print_exc()
    finally:
        input("\nPresione Enter para salir...")
