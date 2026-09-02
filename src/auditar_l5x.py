"""
auditar_l5x.py
==============
Auditor de solo lectura para exportaciones .L5X de Studio 5000 (RSLogix).
NO modifica el PLC ni el archivo original. Lee el L5X, clasifica cada tag
segun el estandar del Ingenio La Florida y propone un tag normalizado
[AREA_3][_FUNCION_][NUMERO], generando un CSV de mapeo auditable:

    tag_viejo ; clase ; funcion_ISA ; area_detectada ; tag_nuevo ; validacion

Clasificacion (3 criterios del estandar):
  1. FISICO_ISA        -> Tag Alias vinculado a una tarjeta de I/O fisica.
  2. FUNCIONAL_ISA     -> Funcion real de proceso con identificacion ISA-5.1.
  3. INTERNA           -> Variable de software (convencion corporativa del PLC).
  4. SIN_CLASIFICAR    -> No encaja: requiere revision humana.

Uso:
    python auditar_l5x.py "FAB_ESCALADOS_Program.L5X"  -> genera mapeo_<archivo>.csv
"""

import sys
import os
import re
import csv
import xml.etree.ElementTree as ET
from collections import defaultdict

# Los CSV de salida siempre se guardan junto a este script (files/),
# sin importar desde donde se pase el .L5X de entrada.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Este script vive en <PROYECTO>/src/. Las salidas de una corrida individual
# no deben ensuciar el codigo fuente: van a <PROYECTO>/resultados/.
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DIR_SALIDA_INDIVIDUAL = os.path.join(PROJECT_ROOT, "resultados")

# ------------------------------------------------------------------
# Tabla OFICIAL seccion alfabetica -> codigo de area (3 digitos).
# Confirmada por el Ingenio (2026-07-22 / 2026-07-23), version final:
#   CAL  (Calderas)                   -> 300
#   CLA  (Clarificacion y Encalado)   -> 400
#   EVAP (Evaporacion)                -> 500
#   COC  (Cocimiento / Tachos)        -> 600
#   CEN  (Centrifugado)               -> 700  (comparte serie con CCV a
#                                               proposito: misma etapa de
#                                               purga/centrifugas, igual
#                                               que EVA/EVAP comparten 500)
#   CCV  (Purga / Centrifugas)        -> 700
#   SEC  (Secado y Envase)            -> 800
#   FM   (Fuerza Motriz/Turbogener.)  -> 900  (etapa Usina/Generacion)
#   TAS  (Tratamiento Agua/Servicios) -> 950  (reasignado: 900 paso a FM)
# ------------------------------------------------------------------
MAPEO_AREA = {
    "RCP":  "000",   # Recepcion y Preparacion de Cana
    "MOL":  "100",   # Molienda
    "DES":  "200",   # Destileria (alcohol 96%)
    # Bioetanol / alcohol anhidro: planta FISICAMENTE DISTINTA de
    # Destileria. Correccion del ingeniero de planta (2026-07-30): no
    # pueden compartir el area 200.
    "BIO":  "250",   # Biodestileria
    "BIOETANOL": "250",
    "CAL":  "300",   # Calderas / Generacion de Vapor
    "CLA":  "400",   # Clarificacion y Encalado
    "CLAR": "400",   # alias visto en el L5X (CLAR_S11_...)
    "COC":  "600",   # Cocimiento / Tachos
    "EVAP": "500",   # Evaporacion
    "EVA":  "500",
    "CEN":  "700",   # Centrifugado (misma etapa de purga que CCV)
    "SEC":  "800",   # Secado y Envase
    "CCV":  "700",   # Purga / Centrifugas
    "FM":   "900",   # Fuerza Motriz / Turbogeneradores (Usina)
    "TAS":  "950",   # Tratamiento de Agua y Servicios
}

# ------------------------------------------------------------------
# AREA POR DEFECTO A NIVEL CONTROLADOR (PLC mono-area).
# Tabla oficial del Ingenio (confirmada 2026-07-24). Varios PLCs sirven a
# UNA sola etapa del proceso: sus tags internos genericos (BNOT_30, MUL_12,
# B_xxx, MSG_5...) no tienen ninguna palabra de area ni en su nombre ni en
# la rutina que los contiene, por lo que ningun diccionario los alcanza.
# Para esos PLCs, el area del controlador es dato duro: se aplica como
# ULTIMO recurso, solo si el tag no pudo resolverse por nombre propio,
# herencia de Scope ni palabras clave (nunca pisa una deteccion previa).
#
# La clave se matchea contra el nombre del archivo .L5X (case-insensitive,
# por prefijo), de modo que los backups .BAK del mismo PLC tambien heredan.
# ------------------------------------------------------------------
AREA_DEFECTO_POR_PLC = {
    "CENTRIFUGA":               "700",  # Centrifugado / Purga (cubre el nombre
                                         # viejo 'CENTRIFUGA_2_de_primera' y el
                                         # nuevo canonico 'CENTRIFUGA_DE_PRIMERA')
    "USINA_LA_FLORIDA":        "900",  # Fuerza Motriz / Usina
    "DIBACCO":                 "000",  # Recepcion y Preparacion de Cana
    "CALD_LA_FLORIDA":         "300",  # Calderas / Generacion de Vapor
    "cenizas2020":             "300",  # Calderas (manejo de cenizas)
    "vinaza":                  "200",  # Destileria (vinaza)
    "DESTILERIA":              "200",  # Destileria -- PLC principal, IP
                                        # 192.168.10.128. Confirmado con
                                        # Ingenieria 28/08/2026: es el mismo
                                        # equipo que se venia mal-identificando
                                        # como 'jw2013' (nombre de un tacho
                                        # viejo, no el equipo real).
    "Painel_Ctr_Turb_Moenda":  "100",  # Molienda (turbina/reductores de
                                        # accionamiento, panel PT-BR, confirmado
                                        # por Ingenieria 27/08/2026)
    "TRAPICHE2022":            "100",  # Molienda. Confirmado por distribucion real:
                                        # 1451/1596 tags con area ya resuelta caen en
                                        # 100, el resto es cola dispersa (800/300/200/
                                        # 400/900) que NO se pisa -- el default solo
                                        # entra cuando no hay ninguna otra pista
                                        # (Ingenieria 27/08/2026).
}


def area_defecto_para(nombre_archivo):
    """Devuelve el codigo de area por defecto del PLC segun el nombre del
    archivo .L5X, o None si ese controlador no tiene default asignado."""
    base_name = os.path.basename(nombre_archivo).upper()
    for clave, cod in AREA_DEFECTO_POR_PLC.items():
        if base_name.startswith(clave.upper()):
            return cod
    return None


# ------------------------------------------------------------------
# COLISIONES DE PREFIJO DE AREA POR PLC: 'DES' es ambiguo en la planta --
# en la mayoria de los PLCs significa Destileria (200, MAPEO_AREA global),
# pero en Calderas_8_9_10_Desaireador significa Desaireador (equipo de
# calderas, 300). Override SCOPED solo a este controlador, sin tocar el
# mapeo global (Ingenieria 27/08/2026, confirmado por alias real:
# 'DES_2_S5_BBA_11_ESTADO' -> Desaireador_2:5:I.Data.0).
# ------------------------------------------------------------------
MAPEO_AREA_OVERRIDE_POR_PLC = {
    "Calderas_8_9_10_Desaireador": {"DES": "300"},
}


def mapeo_area_para_plc(nombre_archivo):
    """Devuelve el diccionario MAPEO_AREA efectivo para este PLC: el global,
    con el override especifico del controlador aplicado encima (si tiene)."""
    efectivo = dict(MAPEO_AREA)
    base_name = os.path.basename(nombre_archivo).upper()
    for clave, override in MAPEO_AREA_OVERRIDE_POR_PLC.items():
        if base_name.startswith(clave.upper()):
            efectivo.update(override)
    return efectivo


# ------------------------------------------------------------------
# Diccionario ISA-5.1 (subconjunto corporativo del Ingenio)
# Primera letra = variable medida ; letras sucesivas = funcion.
# ------------------------------------------------------------------
VARIABLE_INICIAL = set("PTLFASWCDQHIVZEJMBRUGKN")  # amplio; se valida despues
FUNCION_SUCESIVA = set("TICRSHLAVEGQDPZF")

# Codigos ISA validos curados (para no confundir con prefijos internos como B_, SCL_)
ISA_VALIDOS = {
    # Presion
    "PT", "PIT", "PI", "PIC", "PC", "PG", "PSH", "PSL", "PAH", "PAL", "PDT", "PDIT", "PV", "PCV",
    # Temperatura
    "TT", "TIT", "TI", "TIC", "TC", "TG", "TE", "TSH", "TSL", "TAH", "TAL", "TS",
    # Nivel
    "LT", "LIT", "LI", "LIC", "LC", "LG", "LSH", "LSL", "LAH", "LAL", "LV",
    # Flujo / Caudal
    "FT", "FIT", "FI", "FIC", "FC", "FQ", "FQI", "FD", "FDT", "FV", "FE", "FFC",
    # Analisis
    "AT", "AIT", "AI", "AIC", "AE", "AR",
    # Velocidad / Peso / otros del uso corporativo
    "ST", "SI", "SIC", "SC", "WT", "WI", "WIC",
    "CT", "CI", "CIC",  # Conductividad/Control local
    "DT", "DIT", "DI",  # Densidad
    "IT", "II",         # Corriente / Indicacion sucesiva ('IS' removido: invalido, ver validar_reglas)
    "ZT", "ZS", "ZI",   # Posicion / SIS
    "ZSH", "ZSL",       # Switch de posicion Alto/Bajo (fin de carrera) - visto en CALD_LA_FLORIDA
    "ET", "EI",         # Voltaje / Elemento
    "VT", "VI",         # Vibracion
    "MT", "MI",         # Humedad (uso local)
    "HS", "HIC", "HV",  # Manual / Valvula manual
    "QT", "QI", "QQ",   # Cantidad / Totalizador
    "XV", "SV",         # Valvula todo/nada (on-off) y solenoide - visto en CALD/TRAPICHE
}

# Reglas semanticas locales (Nota 3a del estandar del Ingenio): cuando el
# nombre no trae un token ISA literal pero describe una variable de uso
# local, se infiere la letra correspondiente. Orden importa (mas especifico
# primero). El sufijo de funcion se decide segun el datatype (T = Transmisor
# si es analogico).
KEYWORDS_VARIABLE_LOCAL = [
    ("HUMEDAD", "M"),    # Humedad -> primera letra M
    ("BRIX", "D"),       # Brix -> Densidad -> primera letra D
    ("DENSIDAD", "D"),   # Densidad -> primera letra D
    # --- R4: vocabulario de funcion escrito en palabras (ES/PT) ---
    # Varios integradores nombraron la magnitud en castellano/portugues en
    # lugar del codigo ISA (NIVEL_TANQUE_3 en vez de LT_301). Se traduce a
    # la letra de variable ISA correspondiente. Orden: mas especifico
    # primero (PRESION_DIFERENCIAL antes que PRESION).
    ("PRESION_DIFERENCIAL", "PD"), ("PRESSAO_DIFERENCIAL", "PD"),
    ("TEMPERATURA", "T"), ("TEMPERAT", "T"),
    ("PRESION", "P"), ("PRESSAO", "P"),
    ("NIVEL", "L"),
    ("CAUDAL", "F"), ("VAZAO", "F"), ("FLUJO", "F"),
    ("VIBRACION", "V"), ("VIBRACAO", "V"),
    # Dialecto PT abreviado del panel de turbina (Ingenieria 27/08/2026):
    # VIB_/IMP_/DESB_ son abreviaturas de planta para Analisis Mecanico /
    # Vibracion (sonda de vibracion, sonda de impedancia/desplazamiento
    # axial, desbalanceamento). Se exige guion bajo de cierre para no
    # matchear substrings sueltos en otro contexto.
    ("VIB_", "V"), ("IMP_", "V"), ("DESB_", "V"),
    # TRAPICHE2022 (Ingenieria 27/08/2026):
    ("FLOTACION_", "Z"),   # rodillo flotante del molino -> Transmisor de Posicion/Desplazamiento
    ("IC_CINTA_", "I"),    # corriente de motor de cinta transportadora -> Indicador de Corriente
    ("CORRIENTE", "I"), ("AMPERAJE", "I"),
    ("VELOCIDAD", "S"), ("VELOCIDADE", "S"), ("RPM", "S"),
    ("CONDUCTIVIDAD", "C"), ("CONDUC", "C"),
    ("PESO", "W"), ("BALANZA", "W"),
    ("POSICION", "Z"),
]

# Nombres de materiales de proceso: prohibido usarlos como parte del tag
# funcional ISA (el material no identifica al instrumento, identifica al
# fluido medido; eso va en la descripcion, no en el tag).
MATERIALES_PROHIBIDOS = ["JUGO", "MELADO", "CACHAZA", "BAGAZO", "MIEL", "MASA"]

# Sufijos de variable interna (convencion corporativa)
SUFIJOS_INTERNOS = ("_RAW", "_PV", "_SIM", "_FAULT", "_SP", "_HH", "_LL",
                    "_MAN", "_AUT", "_CMD", "_STS", "_FBK", "_ESC", "_SCL")

# Prefijos / datatypes que denotan logica interna (no instrumento fisico)
PREFIJOS_INTERNOS = {"B", "SCL", "ACUM", "ACUMULADOR", "TOTALIZADOR", "BAND",
                     "BNOT", "FALLA", "ARRANQUE", "BMUL", "MUL", "LPF", "MV",
                     "RESET", "ESTADO", "MSG", "ons", "out", "HORA", "input",
                     "Input", "output", "Output", "ST", "CONTROL", "STRATIX"}
DATATYPES_INTERNOS = {"ACUMULADOR", "TOTALIZADOR", "B_CONCATENADO", "FBD_MATH",
                      "FBD_BOOLEAN_NOT", "FBD_BOOLEAN_AND", "FILTER_LOW_PASS",
                      "FBD_MATH_ADVANCED", "FBD_COMPARE",
                      # ARRANQUE_MOTOR_2 se maneja aparte como EQUIPOS_LOGICA
                      # (ver clasificar(), filtro al inicio) -- no como INTERNA.
                      "MESSAGE", "CONTROL_NIVEL", "B_STR", "B_STRATIX",
                      "NET_AB_Stratix_All", "Stratix_HMI", "BOOL", "DINT", "STRING",
                      # Temporizadores/contadores nativos de Logix, y bloque de
                      # compensacion por tiempo muerto (DEADTIME: misma familia
                      # de acondicionamiento de senal que FILTER_LOW_PASS/
                      # HIGH_PASS, confirmado por su estructura interna
                      # In/Out/Gain/Bias/Deadtime -- no es un temporizador
                      # TON/CTU). "Solo se tagea lo que se controla" (correccion
                      # de Ingenieria, 27/08/2026): estos son logica interna,
                      # nunca el instrumento.
                      "TIMER", "COUNTER", "DEADTIME",
                      # FBD_COUNTER: bloque de conteo FBD (distinto del
                      # datatype "COUNTER" nativo ya cubierto arriba) --
                      # misma logica de programa, no un instrumento.
                      # INT: en este universo de tags, "INT" identifica
                      # setpoints/consignas de receta cargados por el
                      # operador (ej. Velocidad_carga, Tiempo_velocidad_interm),
                      # no la PV medida por un transmisor -- "se tagea el
                      # instrumento que mide, no la consigna que se escribe"
                      # (Ingenieria, 27/08/2026).
                      "FBD_COUNTER", "INT",
                      # FBD_ONESHOT (ej. OSRI_01/OSFI_01): bloque de flanco
                      # (one-shot rising/falling), pura logica de programa,
                      # no un instrumento (TRAPICHE2022, Ingenieria 27/08/2026).
                      "FBD_ONESHOT"}
DATATYPES_ANALOGICOS = {"REAL", "SCALE", "SCL_10", "SCL_11", "SCL_67"}

# Datatypes que son la INSTANCIA de un bloque de escalado (SCP/SCL_xx) en el
# diagrama FBD, no el valor de proceso ya escalado. El tag con este datatype
# es la estructura de configuracion/estado del bloque (In/Out/InRawMax/
# InRawMin/InEUMax/InEUMin/...); si se deja pasar, el Criterio 2 lo aceptaria
# igual como FUNCIONAL_ISA en cuanto el nombre trajera un token ISA literal
# (ej. 'B_LT_101' sin el prefijo B_ que hoy lo salva, o cualquier variante sin
# ese prefijo), duplicando el tag real del instrumento -- el que recibe el pin
# Out del bloque, con su propio nombre en unidades de ingenieria. "Solo se
# tagea lo que se controla": el bloque de escalado es logica de
# acondicionamiento, no el instrumento.
DATATYPES_INSTANCIA_ESCALADO = {"SCALE", "SCP", "SCL_10", "SCL_11", "SCL_67"}

# ------------------------------------------------------------------
# Dialecto luso-espanol (DIBACCO y otros PLCs con integrador brasilero):
# UDTs propias del programador cuyo NOMBRE no trae ningun token ISA
# reconocible (ej. 'PIDFIT202' no matchea 'FIT' porque no hay separador),
# pero cuyo DATATYPE si identifica inequivocamente el rol del tag. Se
# resuelven por datatype como ultimo recurso (Criterio 2c en clasificar()),
# solo cuando el nombre no aporto ya una funcion ISA mas especifica.
#
# Comparacion case-insensitive: se observaron variantes de mayuscula
# distintas para el mismo UDT ('PID' / 'PIDs', 'MOTOR' / 'motores').
# ------------------------------------------------------------------
DATATYPES_UDT_ANALOGICO_PT = {"EA_VARIAVEIS", "IN_ANALOGICO"}  # Entrada Analogica (dialecto PT)
# NOTA: se usa el codigo 'AI' en su sentido coloquial de PLC ("Analog
# Input"), no el sentido ISA-5.1 formal (A=Analisis, I=Indicador). 'AI' ya
# es un codigo valido en ISA_VALIDOS por esa segunda razon; se reutiliza a
# proposito para no inflar el diccionario con un codigo nuevo no normado.

# Las 3 variantes de UDT de lazo de control PID que aparecen en DIBACCO
# (mismo rol, distinto nombre segun la version del programa) se funden en
# una sola familia: Controlador generico (letra 'C', ya en el catalogo de
# funciones de Tags App como 'C: Controlador').
DATATYPES_UDT_CONTROLADOR = {"PID", "PIDS", "UD_PIDS"}

# Valvula con sensor de posicion integrado: es un actuador de proceso con
# loop ISA propio -> Valvula de Control ('V', ya en el catalogo).
DATATYPES_UDT_VALVULA = {"VALVULA_SENSOR"}

# Motor (UDT de EQUIPO completo, no un bit discreto de estado): a
# diferencia de la valvula, un motor NO es un instrumento de medicion/
# control con numero de lazo ISA -- es equipo, igual que la UDT corporativa
# Motor_AC que ya usa este motor para los bits ESTADO_/MARCHA_/FALLA_ (ver
# PREFIJOS_EQUIPO_DISCRETO mas abajo). Por consistencia con ese criterio ya
# establecido, se clasifica como INTERNA (convencion corporativa, fuera del
# alcance de numeracion ISA) en vez de forzarlo a un FUNCIONAL_ISA sin
# letra ISA real que lo represente.
DATATYPES_UDT_MOTOR = {"MOTOR", "MOTORES"}

# ------------------------------------------------------------------
# R1 - HIGIENE DE SISTEMA: bloques de instruccion nativos de Logix.
# No son variables de proceso ni instrumentos: son temporizadores,
# contadores, comparadores y operadores logicos generados por el
# programador (TONR_5, SEL_12, BOR_3...). Se clasifican como INTERNA,
# pero se marcan aparte para NO inflar la metrica de exito ISA.
# ------------------------------------------------------------------
BLOQUES_LOGIX = {
    # Temporizadores / contadores
    "TONR", "TOFR", "RTOR", "TON", "TOF", "RTO",
    "CTUD", "CTU", "CTD", "CTUD_1",
    # Comparadores / selectores / logica
    "SEL", "SETD", "BOR", "BAND", "BNOT", "BXOR", "GRT", "LES", "GEQ",
    "LEQ", "EQU", "NEQ", "LIM", "MEQ", "ESEL", "MUX",
    # Matematica
    "ADD", "SUB", "MUL", "DIV", "MOD", "SQR", "NEG", "ABS", "CPT",
    # Movimiento de datos / control de flujo
    "MOV", "COP", "CPS", "FLL", "JSR", "SBR", "RET", "ONS", "OSR", "OSF",
    "RES", "LES_1", "DBJSC",
    # Infraestructura / diagnostico de chasis
    "SLOT", "SLOTS", "MSG",
}
# Otras variables de puro mantenimiento/diagnostico (no son de proceso).
PALABRAS_HIGIENE = {"HORIMETRO", "HORIMETROS", "HRS", "HORAS_SERVICIO"}

# ------------------------------------------------------------------
# R2 - CANALES DE I/O LIBRES: alias declarados sobre canales de tarjeta
# sin instrumento conectado (repuesto/reserva). No son tags fallidos:
# son capacidad instalada disponible. Clase propia: RESERVADO.
# ------------------------------------------------------------------
RE_CANAL_LIBRE = re.compile(r"(?:^|_)(?:LIBRE|SPARE|RESERVA|RESERVADO|NO_?USADO|SIN_?USO)(?:_|\d|$)",
                            re.IGNORECASE)

# Patron de I/O fisico dentro de AliasFor (ej. ISLA_FAB_AI:10:I.Ch[0].Data)
RE_IO_FISICO = re.compile(r":\d+:[IO][.:]", re.IGNORECASE)

# ------------------------------------------------------------------
# R3 - ALIAS ANALOGICO vs DISCRETO.
# Un canal analogico (Ch[0].Data / Ch0Data) transporta una medicion de
# proceso -> es un instrumento ISA-5.1.
# Un bit discreto (:I.Data.5 / :I.Data[2].3 / modulo digital sin miembro)
# transporta un estado ON/OFF de equipo (marcha de bomba, falla de motor)
# -> NO es un instrumento: es un equipo, y se modela con la UDT Motor_AC.
# ------------------------------------------------------------------
RE_IO_ANALOGICO = re.compile(r"Ch\[?\d+\]?\.?Data", re.IGNORECASE)

# Prefijo del tag de estado discreto -> miembro de la UDT Motor_AC.
PREFIJOS_EQUIPO_DISCRETO = [
    ("ESTADO_",    "Sts_Running"),
    ("STS_",       "Sts_Running"),
    ("MARCHA_",    "Sts_Running"),
    ("FUNCIONA_",  "Sts_Running"),
    ("FALLA_",     "Flt_Overload"),
    ("FALHA_",     "Flt_Overload"),
    ("TRIP_",      "Flt_Overload"),
    ("ALM_",       "Flt_Overload"),
    ("ALARMA_",    "Flt_Overload"),
    ("LOCAL_",     "Mode_Auto"),
    ("REMOTO_",    "Mode_Auto"),
    ("AUTO_",      "Mode_Auto"),
    ("PERMISO_",   "Permissive"),
    ("PERMISIVO_", "Permissive"),
    ("ENCLAV_",    "Permissive"),
]
PREFIJOS_EQUIPO_DISCRETO.sort(key=lambda par: -len(par[0]))


def es_bloque_sistema(nombre):
    """R1: True si el tag es un bloque de instruccion Logix o una variable
    de mantenimiento/diagnostico (higiene de sistema, no proceso)."""
    tokens = re.split(r"[_\-.]", nombre.upper())
    primero = tokens[0] if tokens else ""
    if primero in BLOQUES_LOGIX:
        return True
    if primero in PALABRAS_HIGIENE:
        return True
    if any(t in PALABRAS_HIGIENE for t in tokens):
        return True
    return False


def es_canal_libre(nombre):
    """R2: True si el nombre indica un canal de I/O de reserva/sin uso."""
    return RE_CANAL_LIBRE.search(nombre) is not None


def detectar_miembro_equipo(nombre):
    """R3: dado un tag de estado discreto, devuelve (prefijo, miembro
    Motor_AC) o (None, None) si el prefijo no es reconocido."""
    up = nombre.upper()
    for prefijo, miembro in PREFIJOS_EQUIPO_DISCRETO:
        if up.startswith(prefijo):
            return prefijo, miembro
    return None, None


# Codigo ISA PEGADO al numero de lazo, sin separador: 'FIT100', 'PIT101A',
# 'XV106', 'TT10109D1RB'. Es la nomenclatura ISA clasica y la usa toda la
# isla de vapor de CALD_LA_FLORIDA (integrador brasileno) -- el split por
# _/-/. nunca la alcanzaba, asi que ~218 instrumentos reales de planta
# quedaban en SIN_CLASIFICAR (Ingenieria 27/08/2026).
#
# Se exigen 3 o 4 digitos a proposito: los lazos ISA de la planta se
# numeran con 3+ digitos (100-999), mientras que los EQUIPOS se numeran
# con 1-2 (TC01, TC02, TT01). Ese solo requisito separa limpiamente los
# termopares reales (TT100, TT105, TIT111) de los transportadores de
# correa (TC01 'esteira', SD_TC01A = sensor de desalineacion de cinta),
# sin depender de la descripcion -- que en muchos de estos tags esta vacia.
RE_ISA_PEGADO = re.compile(r"^([A-Z]{2,4})(\d{3,4})([A-Z0-9]{0,6})$")

# Codigos que en esta planta identifican EQUIPO, nunca un lazo ISA, aunque
# coincidan con una sigla de la norma. 'TC' = Transportador de Correa
# (confirmado por descripcion: "MOTOR ESTEIRA DE DISTRIBUICAO"), no
# Temperature Controller. Refuerza el criterio de digitos de arriba.
CODIGOS_EQUIPO_NO_ISA = {"TC"}


def detectar_funcion_isa(nombre):
    """Busca en el nombre un token que sea un codigo ISA valido.

    Dos formas: token exacto separado ('PT_DOMO_C10' -> PT) y codigo
    pegado al numero de lazo ('FIT100' -> FIT), ver RE_ISA_PEGADO."""
    tokens = [t.upper() for t in re.split(r"[_\-.]", nombre)]

    # 1) Token exacto (forma con separador). Tiene prioridad: es la
    #    deteccion historica y la mas inequivoca.
    for tok in tokens:
        if tok in ISA_VALIDOS:
            return tok

    # 2) Codigo pegado al numero de lazo.
    for tok in tokens:
        m = RE_ISA_PEGADO.match(tok)
        if not m:
            continue
        codigo = m.group(1)
        if codigo in CODIGOS_EQUIPO_NO_ISA:
            continue
        if codigo in ISA_VALIDOS:
            return codigo
    return None


def detectar_funcion_semantica(nombre, datatype):
    """Regla local (Nota 3a): infiere la letra ISA por palabra clave cuando
    no hay token literal (ej. 'SENSOR_HUMEDAD_ESTE' -> M). Devuelve
    (funcion, palabra_clave) o (None, None) si no aplica."""
    up = nombre.upper()
    for kw, letra in KEYWORDS_VARIABLE_LOCAL:
        if kw in up:
            sufijo = "T" if datatype in DATATYPES_ANALOGICOS else ""
            return letra + sufijo, kw
    return None, None


def detectar_area(nombre):
    """Devuelve el prefijo de seccion si coincide con la tabla de areas."""
    primero = re.split(r"[_\-.]", nombre)[0].upper()
    if primero in MAPEO_AREA:
        return primero
    # buscar seccion en cualquier posicion (ej. TAG sin area al inicio)
    for tok in re.split(r"[_\-.]", nombre.upper()):
        if tok in MAPEO_AREA:
            return tok
    return None


def es_interna(nombre, datatype):
    pref = re.split(r"[_\-.]", nombre)[0]
    if pref in PREFIJOS_INTERNOS:
        return True
    if datatype in DATATYPES_INTERNOS:
        return True
    if nombre.upper().endswith(SUFIJOS_INTERNOS):
        return True
    return False


def clasificar(nombre, tagtype, aliasfor, datatype, operandos_crudos_escalado=None):
    """Aplica los 3 criterios del estandar. Devuelve (clase, funcion, area, nota).

    operandos_crudos_escalado: set (mayuscula) de Operands que alimentan
    directamente el pin In de un bloque de escalado FBD (Type=='SCL') en
    algun lado del archivo -- ver operandos_crudos_a_escalado(). Opcional
    (default None) para no romper otros callers."""
    notas = []
    funcion = detectar_funcion_isa(nombre)
    area = detectar_area(nombre)

    # R2: canal de I/O de reserva (sin instrumento conectado). Se evalua
    # ANTES que el aliasing, porque un canal libre tambien es un Alias.
    if es_canal_libre(nombre):
        notas.append("Canal de I/O de reserva (sin instrumento conectado): capacidad disponible, no requiere tag ISA")
        return "RESERVADO", funcion, area, notas

    # Correccion de Ingenieria 27/08/2026 (2da pasada, 8:25 AM): filtros
    # masivos de "basura de software" aplicados AL INICIO, con prioridad
    # sobre el aliasing fisico (Criterio 1) y cualquier otro criterio -- el
    # ingeniero determino que estos patrones de nombre son siempre logica
    # de programa/flags/consignas, nunca el instrumento, sin excepcion.
    tokens_nombre_full = set(re.split(r"[_\-.]", nombre.upper()))
    primer_token = re.split(r"[_\-.]", nombre.upper())[0] if nombre else ""

    # EQUIPOS_LOGICA: arranque/logica de motores. Se separa de INTERNA
    # (no se mezcla con timers/flags) porque el proyecto paralelo de
    # Mantenimiento Mecanico necesita esta bolsa propia y prolija para
    # mapear equipos de fuerza motriz. Igual que INTERNA_SISTEMA: no
    # computa exito ISA ni entra al universo/denominador de proceso.
    if (datatype or "").upper() == "ARRANQUE_MOTOR_2" or "ARRANQUE" in tokens_nombre_full:
        notas.append("EQUIPOS_LOGICA: arranque/logica de motor -- mapeo de equipo de fuerza motriz (Mantenimiento Mecanico), no es un lazo ISA")
        return "EQUIPOS_LOGICA", funcion, area, notas

    # INTERNA: flags booleanos de falla/disparo/bit sueltos, banderas de
    # modo local/remoto (auto/manual) y consignas (setpoints) -- software
    # puro, nunca el instrumento. Coincidencia por PRIMER token (prefijo),
    # NO en cualquier posicion del nombre: asi no se arrastra al filtro
    # nombres compuestos como 'DES_..._FALLA' o 'EVAP_...' (Grupo 3, zona
    # de cuarentena -- puede tener tokens ISA validos ocultos como FCV,
    # no tocar hasta revision manual).
    PREFIJOS_FLAG_SETPOINT = {"FALLA", "TRIP", "BIT", "IS", "SLOT", "LOC", "MAR", "SP",
                               # PROTEC_*: logica de proteccion de maquina (ej.
                               # PROTEC_MAX_IC), no es una medicion directa
                               # (TRAPICHE2022, Ingenieria 27/08/2026).
                               "PROTEC",
                               # ALM_*: alarma logica suelta, sin instrumento
                               # propio nombrado. PROPORCION_AM_*: parametro/
                               # consigna de relacion aire-combustible de
                               # calderas -- receta, no medicion directa
                               # (Calderas_8_9_10, Ingenieria 27/08/2026).
                               "ALM", "PROPORCION"}
    if primer_token in PREFIJOS_FLAG_SETPOINT:
        notas.append(f"INTERNA: flag/consigna de software (prefijo '{primer_token}'), no es la variable de proceso medida")
        return "INTERNA", funcion, area, notas

    # INTERNA: alias discreto generico sin nombre de equipo (TRAPICHE2022,
    # Ingenieria 27/08/2026) -- 'SENSOR_1', 'SENSOR_2' con datatype vacio no
    # traen ninguna pista de a que instrumento pertenecen; se descartan como
    # logica de maquina en vez de quedar SIN_CLASIFICAR indefinidamente.
    if primer_token == "SENSOR" and not (datatype or "").strip():
        notas.append("INTERNA: alias 'SENSOR_N' generico sin datatype, sin nombre de equipo identificable")
        return "INTERNA", funcion, area, notas

    # INTERNA: estado/falla de equipo del Desaireador (Calderas_8_9_10,
    # Ingenieria 27/08/2026) -- 'DES_2_S5_BBA_11_ESTADO'/'..._FALLA' son
    # aliases discretos de equipo con sufijo de estado (no prefijo, por
    # eso R3/detectar_miembro_equipo no los reconoce). Match especifico
    # por prefijo 'DES' + sufijo _ESTADO/_FALLA, no 'DES' generico, para
    # no tocar otros tags de Destileria (DES = area 200 en otros PLCs).
    if primer_token == "DES" and nombre.upper().endswith(("_ESTADO", "_FALLA")):
        notas.append("INTERNA: estado/falla de equipo del Desaireador (alias discreto con sufijo de estado)")
        return "INTERNA", funcion, area, notas

    # INTERNA: calculo derivado interno del panel de turbina (Ingenieria
    # 27/08/2026) -- "arraste" (arrastre) es un valor calculado por
    # software, no una medicion directa de instrumento. Prefijo especifico
    # (no 'AUX' generico) para no arrastrar otras variables auxiliares
    # legitimas.
    if nombre.upper().startswith("AUX_CALCULO_ARRASTE"):
        notas.append("INTERNA: calculo derivado interno ('arraste'), no es la variable medida por un instrumento")
        return "INTERNA", funcion, area, notas

    # Criterio 1: fisico por aliasing a I/O
    if tagtype == "Alias" and aliasfor and RE_IO_FISICO.search(aliasfor):
        # R3: analogico (medicion de proceso) vs discreto (estado de equipo)
        if RE_IO_ANALOGICO.search(aliasfor):
            # "Solo se tagea lo que se controla" (correccion de Ingenieria,
            # 27/08/2026): si ESTE alias (senal cruda) alimenta directamente
            # el pin In de un bloque de escalado (SCL), es la entrada
            # PRE-escalado -- duplicado del instrumento real, cuyo valor ya
            # escalado sale del bloque con su propio tag (que se clasifica
            # FUNCIONAL_ISA por su propio nombre, sin intervencion de esta
            # regla). No se auto-promueve ese tag de salida aca: solo se
            # suprime la clasificacion competidora del crudo.
            if operandos_crudos_escalado and nombre.upper() in operandos_crudos_escalado:
                notas.append("Alias fisico crudo: alimenta un bloque de escalado (SCL) -> senal pre-escalado, no el instrumento")
                return "INTERNA", funcion, area, notas
            clase = "FISICO_ISA"
            if not funcion:
                # Intentar traducir la magnitud escrita en palabras (R4)
                funcion_sem, kw = detectar_funcion_semantica(nombre, datatype)
                if funcion_sem:
                    notas.append(f"Funcion asignada por regla semantica local: '{kw}' -> {funcion_sem}")
                    return clase, funcion_sem, area, notas
                notas.append("Alias fisico sin funcion ISA reconocible: revisar nombre")
            return clase, funcion, area, notas

        # Alias a bit discreto -> estado/comando de EQUIPO (no instrumento).
        _pref, miembro = detectar_miembro_equipo(nombre)
        if miembro:
            notas.append(f"Alias discreto de equipo: se modela como miembro '.{miembro}' de la UDT Motor_AC")
            return "EQUIPO_DISCRETO", funcion, area, notas
        notas.append("Alias discreto sin prefijo de estado reconocible (ESTADO_/MARCHA_/FALLA_...): revisar")
        return "EQUIPO_DISCRETO", funcion, area, notas

    # R1: bloque de instruccion Logix / variable de mantenimiento.
    # Se clasifica INTERNA (es software), pero marcado como higiene de
    # sistema para excluirlo de la metrica de exito ISA.
    if es_bloque_sistema(nombre):
        notas.append("HIGIENE DE SISTEMA: bloque de instruccion Logix / variable de diagnostico (no es tag de proceso)")
        return "INTERNA_SISTEMA", funcion, area, notas

    # Criterio 3: interna (convencion corporativa).
    #
    # EXCEPCION "el nombre gana sobre el datatype" (Ingenieria 27/08/2026):
    # 'DINT' esta en DATATYPES_INTERNOS porque la mayoria de los enteros
    # son contadores/logica, pero en Calderas_8_9_10 el integrador guarda
    # variables de proceso REALES como enteros escalados
    # ('DES_2_LT_TK_ALCOHOL_1' = NIVEL TANQUE DE ALCOHOL,
    #  'C8_FT_AGUA_SCRUBBER' = CAUDAL DE AGUA A SCRUBBER). Cuando el nombre
    # trae un codigo ISA explicito, esa evidencia es mas fuerte que el tipo
    # de dato: el datatype describe COMO se almacena, el nombre describe
    # QUE se mide.
    #
    # Acotado a DINT a proposito. NO se generaliza a los otros datatypes
    # internos: BOOL/INT/TIMER siguen cortando siempre, para no revertir
    # las decisiones ya tomadas (INT = setpoints de receta, BOOL = flags).
    # Los prefijos de flag/consigna (FALLA_, TRIP_, SP_...) ya cortaron
    # mas arriba, asi que no llegan hasta aca.
    if es_interna(nombre, datatype):
        # Solo se perdona cuando el UNICO motivo de ser interna es el
        # datatype DINT. Si el NOMBRE tambien lo marca como interno
        # (prefijo 'B_'/'SCL_'..., sufijo '_RAW'/'_SP'...), ese nombre es
        # justamente la evidencia contraria y manda igual que siempre:
        # 'B_IT_BBA_...' es el bloque interno de un instrumento, no el
        # instrumento.
        interna_por_nombre = es_interna(nombre, datatype="")
        if (datatype or "").upper() == "DINT" and funcion and not interna_por_nombre:
            notas.append(
                f"Nombre gana sobre datatype: codigo ISA '{funcion}' explicito en el "
                f"nombre; 'DINT' es entero escalado de proceso, no logica interna"
            )
        else:
            return "INTERNA", funcion, area, notas

    # Criterio 3b: instancia de bloque de escalado (SCP/SCALE/SCL_xx). Se
    # evalua ANTES del Criterio 2 a proposito, para que corte el camino
    # tanto de 2 (token literal) como de 2b (semantica) y 2c (datatype UDT)
    # de una sola vez, sin importar cual de los tres hubiera aceptado el tag.
    if (datatype or "").upper() in DATATYPES_INSTANCIA_ESCALADO:
        notas.append(f"Instancia de bloque de escalado (datatype '{datatype}'): logica de acondicionamiento de senal, no el instrumento -> INTERNA")
        return "INTERNA", funcion, area, notas

    # Criterio 3c: tag derivado (acumulado/promedio/periodo), no
    # instrumento. Sin este corte, un tag como 'PT_VAPOR_ENTRADA_ACUM_DIA_ACT'
    # pasaria como FUNCIONAL_ISA solo por contener tambien el token 'PT' --
    # el Criterio 2 no distingue instrumento de reporte derivado. Busca el
    # token completo (separado por _/-/.) en CUALQUIER posicion del nombre,
    # no solo como prefijo (a diferencia de PREFIJOS_UDT_TOT, que exige el
    # token al inicio y solo se consulta para tags ya clasificados INTERNA).
    tokens_nombre = set(re.split(r"[_\-.]", nombre.upper()))
    tokens_derivados = tokens_nombre & TOKENS_TAG_DERIVADO
    if tokens_derivados:
        notas.append(f"Tag derivado (acumulado/promedio/periodo): token(s) {sorted(tokens_derivados)} -> INTERNA, no es el instrumento (ver Fase 4 para reconectar como .Tot)")
        return "INTERNA", funcion, area, notas

    # Criterio 3d: damper (persiana/compuerta de aire o gases de calderas)
    # -- elemento final de control, igual jerarquia que una valvula de
    # control (V). Letra propia 'D', SIN el sufijo T automatico que usa
    # detectar_funcion_semantica (no es un transmisor, es el actuador)
    # (Calderas_8_9_10, Ingenieria 27/08/2026).
    if not funcion and "DAMP" in nombre.upper():
        notas.append("Damper (elemento final de control de caudal de aire/gases) -> D")
        return "FUNCIONAL_ISA", "D", area, notas

    # Criterio 2: funcional ISA (proceso)
    if funcion and datatype in DATATYPES_ANALOGICOS:
        return "FUNCIONAL_ISA", funcion, area, notas

    if funcion:
        notas.append(f"Funcion ISA '{funcion}' con datatype '{datatype}' no analogico: revisar")
        return "FUNCIONAL_ISA", funcion, area, notas

    # Criterio 2b: regla semantica local (Humedad -> M, Brix/Densidad -> D)
    funcion_sem, kw = detectar_funcion_semantica(nombre, datatype)
    if funcion_sem:
        notas.append(f"Funcion asignada por regla semantica local: '{kw}' -> {funcion_sem}")
        return "FUNCIONAL_ISA", funcion_sem, area, notas

    # Criterio 2c: dialecto luso-espanol por DATATYPE (UDT), cuando el
    # nombre del tag no trajo ningun token ISA reconocible (tipico de
    # DIBACCO: 'PIDFIT202', 'EQ_SV01' no matchean por nombre, pero su UDT
    # si identifica el rol). Ultimo recurso antes de SIN_CLASIFICAR.
    datatype_up = (datatype or "").upper()
    if datatype_up in DATATYPES_UDT_ANALOGICO_PT:
        notas.append(f"Funcion asignada por UDT del dialecto PT ('{datatype}'): Entrada Analogica -> AI")
        return "FUNCIONAL_ISA", "AI", area, notas
    if datatype_up in DATATYPES_UDT_CONTROLADOR:
        notas.append(f"Funcion asignada por UDT de lazo de control ('{datatype}', familia PID/PIDs/UD_PIDS unificada): Controlador -> C")
        return "FUNCIONAL_ISA", "C", area, notas
    if datatype_up in DATATYPES_UDT_VALVULA:
        notas.append(f"Funcion asignada por UDT de actuador ('{datatype}'): Valvula de Control -> V")
        return "FUNCIONAL_ISA", "V", area, notas
    if datatype_up in DATATYPES_UDT_MOTOR:
        notas.append(f"UDT de equipo ('{datatype}'): Motor -> convencion corporativa (INTERNA, no es un lazo ISA numerado, igual que Motor_AC)")
        return "INTERNA", funcion, area, notas

    return "SIN_CLASIFICAR", funcion, area, ["No encaja en ningun criterio: revision manual"]


def validar_reglas(nombre, funcion, notas, clase):
    """Chequeos del diccionario de restricciones (ampliable)."""
    up = nombre.upper()
    # Prohibicion estricta: J jamas para Jugo
    if funcion and funcion.startswith("J"):
        notas.append("VIOLACION: 'J' no se usa como funcion (prohibido para Jugo)")
    # Visor local: PI deberia ser PG, TI local deberia ser TG (aviso, no bloqueo)
    if funcion == "PI":
        notas.append("AVISO ISA: visor local de presion es PG, no PI")
    if funcion == "TI":
        notas.append("AVISO ISA: visor local de temperatura es TG, no TI")
    # Diferencial de presion es PD/FD, no confundir
    if "DIFEREN" in up and funcion and funcion.startswith("P") and "D" not in funcion:
        notas.append("AVISO ISA: diferencial deberia usar D (PDT/FD)")

    # 'IS' no es un codigo ISA-5.1 valido (removido de ISA_VALIDOS): senalar
    # explicitamente cuando aparece como primer token, para revision manual.
    primer_token = re.split(r"[_\-.]", up)[0]
    if primer_token == "IS":
        notas.append("VIOLACION: 'IS' no es un codigo ISA-5.1 valido; identificar la funcion real del instrumento")

    # Prohibicion de nombres de materiales de proceso en el tag funcional/fisico.
    # No se aplica a INTERNA: son variables de convencion corporativa propia,
    # fuera del alcance de la norma ISA (alcance acordado con el Ingenio).
    if clase != "INTERNA":
        for mat in MATERIALES_PROHIBIDOS:
            if mat in up:
                notas.append(f"VIOLACION: nombre de material '{mat}' en el tag (prohibido; el material va en la descripcion, no en el tag)")
                break
    return notas


# ------------------------------------------------------------------
# Fase 2: agrupamiento de tags INTERNA como miembros de UDT (ISA-88 /
# IEC 61131-3). Un tag interno suelto (ej. FALLA_PT_101) se transforma en
# miembro con punto del tag base ISA ya numerado (ej. 300_PT_001.Fault),
# siempre que se pueda probar a que instrumento pertenece. Dos metodos:
#   A) Coincidencia de nombre (tokens compartidos tras quitar el prefijo).
#   B) Trazado de cableado FBD (para bloques como SCL_NN, cuyo nombre no
#      lleva ninguna referencia al instrumento; se sigue el Wire que
#      alimenta su pin de entrada hasta encontrar el Operand de origen).
# ------------------------------------------------------------------

# Prefijo -> miembro de UDT, segun las 3 UDT corporativas definidas en
# UDTs_Ingenio_La_Florida.L5X (Transmisor_Analogo, Motor_AC, Valvula_Control).
# Cubre tanto los prefijos originales de la Fase 2 como los prefijos viejos
# adicionales que aparecen en el codigo heredado para alarmas, motores y
# valvulas. IMPORTANTE: varios prefijos especificos empiezan igual que uno
# generico (ej. 'FALLA_SOBRECARGA_' vs 'FALLA_', 'FLT_TRANSITO_' vs 'FLT_'):
# detectar_prefijo_udt() los ordena por longitud descendente para que el
# especifico se evalue siempre antes que el generico.
PREFIJOS_UDT_FIJOS = [
    # --- Transmisor_Analogo: Fault / Raw ---
    ("FALLA_",  "Fault"),
    ("FALHA_",  "Fault"),   # portugues (falla)
    ("DEFEITO_", "Fault"),  # portugues (defecto)
    ("ERR_",    "Fault"),
    ("FLT_",    "Fault"),
    ("SCL_",    "Raw"),
    ("RAW_",    "Raw"),
    ("CRUDA_",  "Raw"),
    # --- Transmisor_Analogo: alarmas (prefijos viejos ALM_*) ---
    ("ALM_MUY_ALTA_",  "Alm_HH"),
    ("ALM_ALTA_ALTA_", "Alm_HH"),
    ("ALM_ALTA_",      "Alm_H"),
    ("ALM_MUY_BAJA_",  "Alm_LL"),
    ("ALM_BAJA_BAJA_", "Alm_LL"),
    ("ALM_BAJA_",      "Alm_L"),

    # --- Motor_AC ---
    ("CMD_ARRANQUE_",     "Cmd_Run"),
    ("CMD_PARADA_",       "Cmd_Stop"),
    ("CMD_PARO_",         "Cmd_Stop"),
    ("STS_MARCHA_",       "Sts_Running"),
    ("STS_RUN_",          "Sts_Running"),
    ("ESTADO_MARCHA_",    "Sts_Running"),
    ("FALLA_SOBRECARGA_", "Flt_Overload"),
    ("FLT_SOBRECARGA_",   "Flt_Overload"),
    ("MODO_AUTO_",        "Mode_Auto"),
    ("PERMISIVO_",        "Permissive"),
    ("REF_VELOCIDAD_",    "Speed_Ref"),
    ("FBK_VELOCIDAD_",    "Speed_Fbk"),

    # --- Valvula_Control ---
    ("CMD_POSICION_",   "Cmd_Pos"),
    ("FBK_POSICION_",   "Fbk_Pos"),
    ("CMD_ABRIR_",      "Cmd_Open"),
    ("CMD_APERTURA_",   "Cmd_Open"),
    ("CMD_CERRAR_",     "Cmd_Close"),
    ("CMD_CIERRE_",     "Cmd_Close"),
    ("STS_ABIERTA_",    "Sts_Opened"),
    ("FCA_",            "Sts_Opened"),  # convencion vieja: Fin de Carrera Abierta
    ("STS_CERRADA_",    "Sts_Closed"),
    ("FCC_",            "Sts_Closed"),  # convencion vieja: Fin de Carrera Cerrada
    ("FALLA_TRANSITO_", "Flt_Transit"),
    ("FLT_TRANSITO_",   "Flt_Transit"),
]
PREFIJOS_UDT_FIJOS_ORDENADOS = sorted(PREFIJOS_UDT_FIJOS, key=lambda par: -len(par[0]))

# Prefijos AMBIGUOS: el miembro destino no se puede fijar solo con el
# prefijo, depende del datatype del tag o de una palabra clave adicional
# en su nombre. Se resuelven aparte, despues de los fijos.
PREFIJOS_UDT_SIM = ("SIM_", "PRUEBA_", "FRZ_")      # -> Sim_Cmd (BOOL) o Sim_PV (REAL)
PREFIJOS_UDT_TOT = ("ACUM_", "TOTAL_", "TOT_")      # -> Tot o Tot_Prev (si es periodo anterior)

# Tokens que indican un TAG DERIVADO (acumulado/promediado/de periodo), no
# la medicion instantanea del instrumento. Patron real de planta:
# '<FUNCION>_<PROCESO>_ACUM_<PERIODO>' (ej. PT_VAPOR_ENTRADA_ACUM_DIA_ACT) --
# el token ISA va PRIMERO, por eso PREFIJOS_UDT_TOT (que exige el token al
# INICIO del nombre) no lo agarra: se usa en clasificar() (Criterio 3c) para
# buscarlo como token completo en CUALQUIER posicion. "Solo se tagea lo que
# se controla": un acumulado diario no es un lazo de control, es un reporte
# -> INTERNA (la Fase 4 ya sabe reconectarlo como miembro '.Tot'/'.Tot_Prev'
# via PREFIJOS_UDT_TOT si corresponde).
TOKENS_TAG_DERIVADO = {"ACUM", "TOTAL", "TOT", "HR", "DIA", "TURNO", "PROM", "MEDIA"}
PALABRAS_PERIODO_ANTERIOR = ("ANTERIOR", "DIA_AYER", "_AYER")

# Palabras de relleno que no aportan identidad al instrumento: se ignoran
# al comparar tokens entre un tag interno y un posible tag base.
PALABRAS_VACIAS_MATCH = {
    "BLOQUE", "DATOS", "DE", "DEL", "LA", "EL", "DIA", "AYER", "HORA",
    "HORAS", "MINUTOS", "SERV", "SERVICIO",
}


def detectar_prefijo_udt(nombre, datatype):
    """Devuelve (prefijo, miembro) si el nombre matchea un prefijo de
    convencion interna (Transmisor_Analogo / Motor_AC / Valvula_Control),
    si no (None, None). Para SIM_/ACUM_ y variantes, el miembro exacto se
    resuelve segun datatype (Sim_Cmd vs Sim_PV) o palabra clave de periodo
    (Tot vs Tot_Prev)."""
    up = nombre.upper()

    for prefijo, miembro in PREFIJOS_UDT_FIJOS_ORDENADOS:
        if up.startswith(prefijo):
            return prefijo, miembro

    for prefijo in PREFIJOS_UDT_SIM:
        if up.startswith(prefijo):
            miembro = "Sim_Cmd" if datatype == "BOOL" else "Sim_PV"
            return prefijo, miembro

    for prefijo in PREFIJOS_UDT_TOT:
        if up.startswith(prefijo):
            es_periodo_anterior = any(kw in up for kw in PALABRAS_PERIODO_ANTERIOR)
            miembro = "Tot_Prev" if es_periodo_anterior else "Tot"
            return prefijo, miembro

    return None, None


def construir_grafo_fbd(root):
    """Indexa cada hoja (Sheet) de los diagramas de bloques de funcion:
    id de nodo -> Operand, id de bloque -> Type (instruccion FBD, ej. 'SCL',
    'SQR', 'MUL'), y la lista de cables (Wire) FromID->ToID.
    Se usa para trazar el origen real de un bloque cuando su nombre no
    lo revela (tipico de los bloques SCL_NN), y para detectar que operandos
    alimentan un bloque de escalado (ver operandos_crudos_a_escalado)."""
    grafo = []
    for sheet in root.iter("Sheet"):
        id2op = {}
        id2tipo_bloque = {}
        for tag_nodo in ("IRef", "ORef", "Block"):
            for el in sheet.findall(tag_nodo):
                op = el.get("Operand")
                if op is not None:
                    id2op[el.get("ID")] = op
                if tag_nodo == "Block":
                    tipo = el.get("Type")
                    if tipo is not None:
                        id2tipo_bloque[el.get("ID")] = tipo
        wires = [(w.get("FromID"), w.get("ToID")) for w in sheet.findall("Wire")]
        grafo.append({"id2op": id2op, "wires": wires, "id2tipo_bloque": id2tipo_bloque})
    return grafo


def operandos_crudos_a_escalado(grafo):
    """Devuelve el conjunto (en mayuscula) de Operands que alimentan
    directamente (1 salto) el pin de entrada de un bloque Type=='SCL' en
    cualquier hoja FBD. "Solo se tagea lo que se controla" (correccion de
    Ingenieria, 27/08/2026): esa senal es la entrada CRUDA (pre-escalado),
    no el instrumento -- el valor ya escalado sale del pin Out del bloque
    con su propio tag, que se clasifica FUNCIONAL_ISA por su propio merito,
    sin intervencion de esta funcion (no se auto-promueve nada aca).

    Alcance: solo rastrea 1 salto (Alias -> SCL.In). No sigue cadenas
    SCL -> SQR -> MUL ni bloques que entregan directo a un pin de AOI sin
    pasar por un ORef con nombre propio -- ver limitaciones documentadas
    en el plan de esta correccion."""
    crudos = set()
    for hoja in grafo:
        id2op = hoja["id2op"]
        ids_scl = {bid for bid, tipo in hoja["id2tipo_bloque"].items()
                   if (tipo or "").upper() == "SCL"}
        if not ids_scl:
            continue
        for (fid, tid) in hoja["wires"]:
            if tid in ids_scl:
                origen = id2op.get(fid)
                if origen:
                    crudos.add(origen.upper())
    return crudos


_RE_LITERAL = re.compile(r"^-?\d+(\.\d+)?$")


def rastrear_origen_por_cableado(nombre_tag, grafo):
    """Busca un Block cuyo Operand == nombre_tag y devuelve la lista de
    Operands que alimentan alguno de sus pines de entrada (candidatos a
    ser el instrumento de origen). Ignora literales numericos."""
    candidatos = []
    for hoja in grafo:
        id2op = hoja["id2op"]
        ids_bloque = [i for i, op in id2op.items() if op == nombre_tag]
        if not ids_bloque:
            continue
        for bid in ids_bloque:
            for (fid, tid) in hoja["wires"]:
                if tid == bid:
                    origen = id2op.get(fid)
                    if origen and not _RE_LITERAL.match(origen):
                        candidatos.append(origen)
    return candidatos


def emparejar_interno_con_base(nombre, resto, indice_base, indice_pendiente, grafo):
    """Intenta ubicar el tag base (ya clasificado) al que pertenece un tag
    INTERNA. Devuelve (fila_base_o_None, metodo, confianza)."""
    tokens_resto = set(re.split(r"[_\-.]", resto.upper())) - PALABRAS_VACIAS_MATCH
    tokens_resto.discard("")

    def mejor_coincidencia(indice):
        mejor, mejor_score = None, 0
        for tag_base, fila in indice.items():
            tokens_base = set(re.split(r"[_\-.]", tag_base)) - PALABRAS_VACIAS_MATCH
            score = len(tokens_resto & tokens_base)
            if score > mejor_score:
                mejor, mejor_score = fila, score
        return mejor, mejor_score

    if tokens_resto:
        fila, score = mejor_coincidencia(indice_base)
        if score >= 2:
            return fila, "coincidencia de nombre", ("ALTA" if score >= 3 else "MEDIA")

    # Metodo B: trazado de cableado FBD (tipico para SCL_NN sin nombre util)
    for origen in rastrear_origen_por_cableado(nombre, grafo):
        origen_up = origen.upper()
        if origen_up in indice_base:
            return indice_base[origen_up], "cableado FBD", "ALTA"
        if origen_up in indice_pendiente:
            return indice_pendiente[origen_up], "cableado FBD", "ALTA"

    if tokens_resto:
        fila, score = mejor_coincidencia(indice_pendiente)
        if score >= 2:
            return fila, "coincidencia de nombre (base sin clasificar)", ("ALTA" if score >= 3 else "MEDIA")

    return None, None, None


def transformar_interna_a_miembro(fila_interna, indice_base, indice_pendiente, grafo, cod_area_heredado_por_tag, mapeo_area=None):
    """Aplica el patron UDT/ISA-88 a un tag INTERNA: si referencia un
    instrumento ya numerado, lo convierte en miembro con punto
    (300_PT_001.Fault); si no, lo deja como logica de estado con prefijo
    de area en UPPER_SNAKE_CASE (300_ARRANQUE_PLANTA).

    mapeo_area: dict de area efectivo para el PLC actual (default: el
    global MAPEO_AREA), ver mapeo_area_para_plc()."""
    nombre = fila_interna["tag_viejo"]
    prefijo, miembro = detectar_prefijo_udt(nombre, fila_interna["datatype"])

    if prefijo:
        resto = nombre[len(prefijo):]
        fila_base, metodo, confianza = emparejar_interno_con_base(
            nombre, resto, indice_base, indice_pendiente, grafo
        )
        if fila_base is not None:
            base_tag_nuevo = fila_base["tag_nuevo_propuesto"]
            base_resuelta = (fila_base["clase"] in ("FUNCIONAL_ISA", "FISICO_ISA")
                              and "???" not in base_tag_nuevo and "PENDIENTE" not in base_tag_nuevo)

            # Regla fisica: .Tot/.Tot_Prev (acumulador/totalizador, corriente
            # o de periodo anterior) solo tiene sentido sobre variables de
            # Caudal o Cantidad (F/Q). Un PT, TT, LT, etc. no se acumula: si
            # el prefijo mapeo a .Tot/.Tot_Prev pero la variable base no es
            # F/Q, es una inconsistencia fisica -> requiere validacion de
            # ingenieria de campo, no se auto-enlaza ni se ofrece como
            # candidato.
            if miembro in ("Tot", "Tot_Prev") and base_resuelta and fila_base["funcion_ISA"][:1] not in ("F", "Q"):
                return (f"PENDIENTE (inconsistencia fisica: '.{miembro}' no aplica sobre '{fila_base['tag_viejo']}', funcion '{fila_base['funcion_ISA']}' no es Caudal/Cantidad)",
                        f"VIOLACION: acumulador (.{miembro}) referenciando una variable no-F/Q ('{fila_base['funcion_ISA']}' en '{fila_base['tag_viejo']}'); validar con ingenieria de campo")

            if base_resuelta and confianza == "ALTA":
                return (f"{base_tag_nuevo}.{miembro}",
                        f"Miembro de UDT ({miembro}) enlazado a '{fila_base['tag_viejo']}' por {metodo}, confianza {confianza}")
            if base_resuelta and confianza == "MEDIA":
                # Confianza MEDIA no se auto-aplica: riesgo de colision entre
                # variantes del mismo instrumento (ej. ESTE/OESTE, N/S) que
                # comparten tokens pero son equipos fisicos distintos.
                return (f"PENDIENTE (candidato: '{base_tag_nuevo}.{miembro}' via '{fila_base['tag_viejo']}')",
                        f"Coincidencia de nombre solo MEDIA confianza (posible ambiguedad, ej. variantes ESTE/OESTE/N/S): confirmar manualmente antes de enlazar a '{fila_base['tag_viejo']}'")
            return (f"PENDIENTE (miembro .{miembro} de '{fila_base['tag_viejo']}', que aun no tiene area/tag base resuelto)",
                    f"Enlazado por {metodo} a un tag base todavia sin clasificar/pendiente: revisar '{fila_base['tag_viejo']}' primero")
        else:
            return (f"PENDIENTE (parece miembro .{miembro} pero no se hallo el instrumento base: revisar manualmente)",
                    "No se encontro tag base por nombre ni por cableado FBD")

    # Regla 3: pura logica de estado, sin instrumento asociado.
    area = detectar_area(nombre)
    mapeo_area_efectivo = mapeo_area if mapeo_area is not None else MAPEO_AREA
    cod_area = mapeo_area_efectivo.get(area) if area else None
    nombre_norm = re.sub(r"[^A-Z0-9_]", "_", nombre.upper())
    if cod_area:
        return f"{cod_area}_{nombre_norm}", "Logica de estado / arranque (area por nombre propio)"

    # Sin area en el propio nombre: intentar herencia por Scope (Program/Routine)
    cod_area_heredado, metodo_scope = cod_area_heredado_por_tag.get(nombre, (None, None))
    if cod_area_heredado:
        return f"{cod_area_heredado}_{nombre_norm}", f"Logica de estado / arranque (area heredada por Scope: {metodo_scope})"

    return f"???_{nombre_norm}", "Logica de estado sin area detectable en el nombre ni heredable por Scope: asignar area manualmente"


# ------------------------------------------------------------------
# Fase 3: herencia de area por Scope (Program/Routine), para tags que no
# traen ningun token de area en su propio nombre. En Studio 5000 un tag
# vive dentro de un Scope (Program local o Controller global) y su logica
# vive dentro de Routines que pertenecen a un Program. Dos reglas:
#   1) Program (alcance local): el tag hereda el area del <Program Name=...>
#      que lo contiene, si ese nombre matchea la tabla de areas.
#   2) Routine (alcance global / Program sin area propia): se busca en que
#      Routine(s) se referencia el tag (texto de rungs RLL + operandos FBD)
#      y se hereda el area de esa rutina (por nombre), o si el nombre de la
#      rutina tampoco es concluyente, por mayoria de votos entre los demas
#      tags de esa rutina que SI tienen area propia por nombre.
# ------------------------------------------------------------------

# Sinonimos de nombres de Program/Routine que no son clave literal de
# MAPEO_AREA pero identifican inequivocamente una etapa del proceso.
# Se buscan como SUB-CADENA dentro del nombre de la rutina/programa (ej.
# 'GRELHA' matchea en 'CTRL_Pressao_Vapor_Grelhas'), asi que solo se
# incluyen terminos largos e inequivocos para evitar falsos positivos.
# Multi-idioma: la planta tiene PLCs de distintos integradores (español y
# portugués). Estos terminos habilitan el voto por vecindad de rutinas,
# que es la palanca de mayor cobertura en PLCs sin prefijo de area (ej.
# CALD_LA_FLORIDA, cuyas rutinas describen la funcion de caldera en PT).
PROGRAMA_KEYWORDS = {
    "ENCALADO": "400",  # Clarificacion y Encalado
    "DESTIL":   "200",  # Destileria
    # --- Calderas / Generacion de Vapor (300) - vocabulario PT/ES ---
    "GRELHA":    "300",  # parrilla (grate)
    "CALDEIRA":  "300",  # caldera (PT)
    "COMBUSTAO": "300",  # combustion (PT)
    "FULIGEM":   "300",  # hollin / sopladores de hollin
    "BALAO":     "300",  # domo de vapor (steam drum, PT)
    "TIRAGEM":   "300",  # tiro/tiraje (PT)
    "FORNALHA":  "300",  # hogar/fornalla
    "DESAERADOR": "300", "DESAIREADOR": "300",  # desaireador
    "VAPOR":     "300",
    # --- Molienda (100) - vocabulario PT/ES ---
    "MOENDA":       "100",  # molienda (PT)
    "MOLINO":       "100",
    "MACERACION":   "100",
    "PREPARACION_CANA": "100",
    "TRAPICHE":     "100",
    "INMIBICION":   "100", "IMBIBICION": "100",  # imbibicion (con typo comun)
}

# ------------------------------------------------------------------
# Fase 3.5: inferencia semantica por palabras clave de proceso ("segundo
# filtro"), para tags huerfanos que no resolvieron area ni por su propio
# nombre ni por herencia de Scope. Palabras clave del Ingenio, agrupadas
# por area. Se buscan como TOKEN o FRASE COMPLETA (separada por "_"), no
# como sub-cadena libre: una busqueda de substring ingenua haria que
# 'CAL' matchee dentro de 'ESCALADO' (es-CAL-ado), que es precisamente
# el nombre de la mitad de las rutinas de este PLC piloto. Ese falso
# positivo se evita exigiendo limites de token (_CAL_, no libre).
# ------------------------------------------------------------------
PALABRAS_CLAVE_AREA = {
    "100": ["CANA", "TRAPICHE", "MOL", "MOENDA", "MOLINO", "MACERACION",  # Molienda
            "MESA", "ROLO", "MAZA",
            # R5 - dialecto TRAPICHE2022
            "COLADO", "COLAR", "INTERMEDIARIO", "INTERMEDIARIOS",
            "ALIMENTADOR", "ZARANDA", "CUCHILLA", "CUCHILLAS", "DESFIBRADOR"],
    "200": ["DEST", "DESTIL", "DESTILERIA",  # Destileria (alcohol 96%)
            # R5 - dialecto DESTILERIA
            "CUBA", "CUBAS", "MOSTO", "FERMENT", "FERMENTACION",
            "MELAZA", "ALCOHOL", "VINAZA", "LEVADURA"],
    # Biodestileria (alcohol anhidro). Planta distinta de Destileria: sus
    # palabras clave son las de deshidratacion por tamices moleculares,
    # que es lo que la diferencia del proceso de 96%.
    "250": ["BIO", "BIOETANOL", "ANHIDRO", "TAMIZ", "TAMICES",
            "DESHIDRATACION", "DESHIDRATADOR"],
    "300": ["CAL", "VAPOR", "AGUA_ALIMENTACION", "PURGA_CALD",            # Calderas / Vapor
            "GRELHA", "GRELHAS", "CALDEIRA", "COMBUSTAO", "FULIGEM",
            "BALAO", "TIRAGEM", "FORNALHA",  # vocabulario PT
            # R5 - dialecto Calderas_8_9_10 / CALD_LA_FLORIDA
            "DOMO", "HOGAR", "DAMPER", "ESPARCIDOR", "BAGAZO", "CINTA",
            "RASTRA", "RASTRAS", "DESAIREADOR", "DESAERADOR", "CENIZA",
            "CENIZAS", "ECONOMIZADOR", "SOBRECALENTADOR", "CHIMENEA"],
    "400": ["JUGO_CLARO", "CLARIFICADOR", "SULFITACION", "DEFECADOR",   # Clarificacion
            # Correccion de falsos positivos: los tags de "jugo encalado"
            # eran arrastrados a 100/800 por el voto de vecindad de rutina.
            "ENCAL", "ENCALADO", "JUGO_ENCAL", "CAL_APAGADA", "LECHADA"],
    "500": ["MELADO", "EVAP", "VACIO", "CONDENSADOR", "JARABE"],        # Evaporacion
    "600": ["TACHO", "MASCOCIDA", "CRISTALIZADOR", "PIE_DE_CUBA"],      # Cocimiento / Tachos
    "700": ["CENTRIFUGA", "MAGMA", "MIEL_RICA", "MIEL_POBRE", "MIEL_POGRE", "CCV"],  # Centrifugas/Purga
    "800": ["SECADOR", "AZUCAR", "TOLVA", "ENVASE", "BALANZA"],         # Secado / Envasado
    # Nota: el pedido agrupaba 900/950 en un solo bloque "Usina/Servicios",
    # pero ya existe una distincion oficial confirmada en esta misma sesion
    # (FM=900 Fuerza Motriz/Turbogeneradores, TAS=950 Tratamiento de Agua y
    # Servicios). Se respeta esa distincion en vez de fusionarlas:
    "900": ["TURBINA", "GENERADOR"],                # Fuerza Motriz / Usina
    "950": ["AGUA_FRIA", "TORRE_ENFRIAMIENTO"],      # Tratamiento de Agua y Servicios
}

# ------------------------------------------------------------------
# REGLA DE ESPECIFICIDAD (decision del ingeniero de planta, 2026-07-30).
# Palabras que pertenecen en EXCLUSIVA a un area: si aparecen en el nombre
# de un tag, esa area gana con prioridad absoluta y se ignora cualquier
# coincidencia generica de PALABRAS_CLAVE_AREA.
#
# Caso que la motiva: 'ALCOHOL' es generico de Destileria (200), pero el
# alcohol ANHIDRO solo se produce en Biodestileria (250) mediante tamices
# moleculares. Sin esta regla, 'FT_ALCOHOL_ANHIDRO' quedaba AMBIGUO entre
# 200 y 250 y caia a revision manual, cuando en realidad es 250 sin duda.
#
# Criterio para agregar terminos aca: solo vocabulario que NO pueda existir
# en otra area de la planta. Ante la duda, va en PALABRAS_CLAVE_AREA.
# ------------------------------------------------------------------
PALABRAS_CLAVE_EXCLUSIVAS = {
    # Biodestileria: deshidratacion por tamices moleculares. Ningun otro
    # sector de la planta usa este vocabulario.
    "250": ["ANHIDRO", "TAMIZ", "TAMICES", "DESHIDRATACION",
            "DESHIDRATADOR", "BIOETANOL"],
}


def area_por_palabras_clave(nombre):
    """Segundo filtro semantico. Devuelve (cod_area, palabra_encontrada) si
    hay una unica area candidata; ('AMBIGUO', {area: palabra, ...}) si el
    nombre matchea palabras clave de mas de un area (no se auto-aplica,
    requiere revision manual); (None, None) si no matchea ninguna.

    REGLA DE ESPECIFICIDAD: si el nombre contiene una palabra EXCLUSIVA de
    un area (ver PALABRAS_CLAVE_EXCLUSIVAS), esa area gana de forma
    absoluta y no se evalua la ambiguedad. Ej.: 'FT_ALCOHOL_ANHIDRO'
    matchea 'ALCOHOL' (200, generica) y 'ANHIDRO' (250, exclusiva); la
    exclusiva decide -> 250, porque el alcohol anhidro solo se produce en
    Biodestileria."""
    normalizado = "_" + re.sub(r"[^A-Z0-9]", "_", nombre.upper()) + "_"

    # Paso 1: palabras exclusivas (prioridad absoluta sobre las genericas).
    exclusivas = {}
    for cod_area, palabras in PALABRAS_CLAVE_EXCLUSIVAS.items():
        for kw in palabras:
            if f"_{kw}_" in normalizado:
                exclusivas.setdefault(cod_area, kw)
                break
    if len(exclusivas) == 1:
        (cod_area, kw), = exclusivas.items()
        return cod_area, kw
    if len(exclusivas) > 1:
        # Dos areas reclaman exclusividad sobre el mismo tag: es un
        # conflicto real de nomenclatura, no se resuelve automaticamente.
        return "AMBIGUO", exclusivas

    # Paso 2: palabras clave genericas (comportamiento historico).
    encontradas = {}
    for cod_area, palabras in PALABRAS_CLAVE_AREA.items():
        for kw in palabras:
            if f"_{kw}_" in normalizado:
                encontradas.setdefault(cod_area, kw)
                break
    if not encontradas:
        return None, None
    if len(encontradas) > 1:
        return "AMBIGUO", encontradas
    (cod_area, kw), = encontradas.items()
    return cod_area, kw


def area_por_nombre_contenedor(nombre, mapeo_area=None):
    """Intenta inferir el codigo de area a partir del nombre de un
    Program o Routine (no del tag): tokens que sean clave de MAPEO_AREA,
    o palabras clave sinonimas de PROGRAMA_KEYWORDS.

    mapeo_area: dict de area efectivo para el PLC actual (default: el
    global MAPEO_AREA), ver mapeo_area_para_plc()."""
    if mapeo_area is None:
        mapeo_area = MAPEO_AREA
    if not nombre:
        return None
    up = nombre.upper()
    for tok in re.split(r"[_\-.]", up):
        cod = mapeo_area.get(tok)
        if cod:
            return cod
    for kw, cod in PROGRAMA_KEYWORDS.items():
        if kw in up:
            return cod
    return None


def extraer_tags_referenciados(routine_el):
    """Devuelve el conjunto de identificadores mencionados dentro de una
    Routine: texto de rungs RLL (XIC(TAG), OTE(TAG), etc.) y operandos de
    nodos FBD (IRef/ORef/Block)."""
    refs = set()
    for txt in routine_el.iter("Text"):
        if txt.text:
            for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", txt.text):
                refs.add(tok.upper())
    for nodo in ("IRef", "ORef", "Block"):
        for el in routine_el.iter(nodo):
            op = el.get("Operand")
            if op:
                refs.add(op.upper())
    return refs


def construir_indice_scope(root, mapeo_area=None):
    """Recorre la estructura Controller/Program/Routine del L5X y arma:
      tag_a_programa    : NOMBRE_TAG -> nombre de Program que lo declara
                          (None si es Controller Tag / alcance global).
      programa_area     : nombre de Program -> cod_area (o None).
      rutina_info       : lista de {programa, rutina, area, tags} por cada
                          Routine, con el set de tags que referencia.

    mapeo_area: dict de area efectivo para el PLC actual (default: el
    global MAPEO_AREA), ver mapeo_area_para_plc()."""
    tag_a_programa = {}
    programa_area = {}
    rutina_info = []

    controller_tags_el = root.find(".//Controller/Tags")
    if controller_tags_el is not None:
        for tg in controller_tags_el.findall("Tag"):
            tag_a_programa[tg.get("Name", "").upper()] = None

    for prog in root.iter("Program"):
        pname = prog.get("Name", "")
        parea = area_por_nombre_contenedor(pname, mapeo_area)
        programa_area[pname] = parea

        tags_el = prog.find("Tags")
        if tags_el is not None:
            for tg in tags_el.findall("Tag"):
                tag_a_programa[tg.get("Name", "").upper()] = pname

        for rt in prog.findall(".//Routine"):
            rname = rt.get("Name", "")
            rarea = area_por_nombre_contenedor(rname, mapeo_area) or parea
            rutina_info.append({
                "programa": pname, "rutina": rname, "area": rarea,
                "tags": extraer_tags_referenciados(rt),
            })

    return tag_a_programa, programa_area, rutina_info


# Umbral minimo para auto-aplicar el voto por mayoria (Regla 2b): por debajo
# de esto, el area queda como candidata a confirmar, no se aplica sola
# (mismo criterio de prudencia que las coincidencias de nombre MEDIA en el
# enlazado de UDTs: mejor pendiente-y-visible que una mala corrida silenciosa).
UMBRAL_VOTOS_MINIMO = 3
UMBRAL_MAYORIA_MINIMA = 0.6


def heredar_area_por_scope(nombre_tag, tag_a_programa, programa_area, rutina_info, indice_area_por_nombre):
    """Aplica las 2 reglas de herencia por Scope. Devuelve (cod_area, metodo,
    confianza) o (None, None, None) si no se pudo inferir por ningun camino.
    confianza es 'ALTA' (Program/Routine por nombre, o mayoria fuerte) o
    'BAJA' (mayoria debil: no se auto-aplica, queda como candidata)."""
    nombre_up = nombre_tag.upper()

    # Regla 1: Program (alcance local)
    programa = tag_a_programa.get(nombre_up, "__NO_ENCONTRADO__")
    if programa not in (None, "__NO_ENCONTRADO__"):
        area_prog = programa_area.get(programa)
        if area_prog:
            return area_prog, f"heredado del Program '{programa}' que lo declara", "ALTA"

    # Regla 2a: Routine por nombre (alcance global o Program sin area propia)
    rutinas_con_tag = [r for r in rutina_info if nombre_up in r["tags"]]
    for r in rutinas_con_tag:
        if r["area"]:
            return r["area"], f"referenciado en la rutina '{r['rutina']}' (Program '{r['programa']}')", "ALTA"

    # Regla 2b: fallback por mayoria de votos entre tags vecinos de la(s)
    # misma(s) rutina(s) que ya tienen area propia por su nombre.
    conteo = defaultdict(int)
    for r in rutinas_con_tag:
        for vecino in r["tags"]:
            cod = indice_area_por_nombre.get(vecino)
            if cod:
                conteo[cod] += 1
    if conteo:
        mejor = max(conteo, key=conteo.get)
        total = sum(conteo.values())
        nota = f"mayoria de tags vecinos con area propia en la misma rutina ({conteo[mejor]}/{total} votos)"
        if total >= UMBRAL_VOTOS_MINIMO and (conteo[mejor] / total) >= UMBRAL_MAYORIA_MINIMA:
            return mejor, nota, "ALTA"
        return mejor, nota, "BAJA"

    return None, None, None


def proponer_tag(clase, cod_area, funcion, contador):
    """Genera el tag normalizado [AREA]_[FUNCION]_[NUM] con numeracion por lazo.
    Numeracion POC: secuencial por (area, funcion). El numero de lazo COMPARTIDO
    definitivo se consolida en la fase de agrupamiento de lazos."""
    if clase == "EQUIPOS_LOGICA":
        # Bolsa propia para Mantenimiento Mecanico (arranque/logica de
        # motores) -- no se resuelve como miembro UDT en Fase 4, se
        # identifica solo por su clase en el CSV.
        return "N/A (equipo de logica de arranque - Mantenimiento Mecanico)"
    if clase in ("INTERNA", "INTERNA_SISTEMA", "EQUIPO_DISCRETO"):
        # Se resuelven en la Fase 4 (miembros de UDT / logica de estado).
        return "N/A (variable interna - convencion corporativa)"
    if clase == "RESERVADO":
        # R2: canal libre. No lleva tag ISA; se documenta como reserva.
        return "RESERVADO (canal de I/O libre)"
    if not funcion:
        return "PENDIENTE (funcion ISA no detectada)"
    if cod_area is None:
        cod_area = "???"
    clave = (cod_area, funcion)
    contador[clave] += 1
    numero = contador[clave]
    return f"{cod_area}_{funcion}_{numero:03d}"


def procesar(path_l5x, area_defecto=None, plc_nombre=None, conn_aprendizaje=None):
    """Procesa un .L5X completo y devuelve (filas, resumen).

    plc_nombre, conn_aprendizaje: enganche OPCIONAL con la Aprendizaje por
    Excepcion de la Tags App (app_etiquetas/aprendizaje.py). Si
    conn_aprendizaje es None (default), este modulo se comporta exactamente
    igual que siempre -- sigue siendo standalone, sin ninguna dependencia
    de la Tags App ni de su base de datos. Si se pasa una conexion abierta
    (ver aprendizaje_motor.abrir_conexion()), cada tag que las reglas de
    codigo dejarian SIN_CLASIFICAR se consulta primero contra
    reglas_aprendidas antes de rendirse, y si tampoco hay nada ahi, se
    archiva solo en la bandeja de pendientes (tags_no_clasificados) --
    ver aprendizaje_motor.clasificar_con_aprendizaje()."""
    tree = ET.parse(path_l5x)
    root = tree.getroot()

    # Import diferido A PROPOSITO: solo se ejecuta si el caller realmente
    # pidio aprendizaje (conn_aprendizaje != None). auditar_l5x.py no debe
    # tener NUNCA una dependencia dura de la Tags App / app_etiquetas -- es
    # el motor standalone, reutilizable sin esa carpeta (ver docstring del
    # modulo). El import diferido tambien evita el ciclo de imports:
    # aprendizaje_motor ya hace 'import auditar_l5x' por su cuenta.
    _clasificar_con_aprendizaje = None
    if conn_aprendizaje is not None:
        from aprendizaje_motor import clasificar_con_aprendizaje as _clasificar_con_aprendizaje

    # Grafo FBD: se construye una sola vez, ANTES del Paso 1, porque ahora lo
    # necesita clasificar() (Criterio 1: excluir alias crudo que alimenta un
    # bloque de escalado) ademas del Paso 4 (emparejamiento INTERNA <-> base
    # por cableado, mas abajo). Antes se construia solo en el Paso 4; se
    # reutiliza el mismo grafo en los dos lugares.
    grafo_fbd = construir_grafo_fbd(root)
    operandos_crudos_escalado = operandos_crudos_a_escalado(grafo_fbd)

    # Mapeo de area efectivo para ESTE PLC (global + override scoped si
    # corresponde, ej. 'DES' -> 300 en Calderas_8_9_10_Desaireador en vez
    # de 200/Destileria). Ver mapeo_area_para_plc().
    mapeo_area_efectivo = mapeo_area_para_plc(path_l5x)

    # ------------------------------------------------------------
    # Paso 1: clasificar cada tag (clase, funcion, area por NOMBRE propio).
    # Todavia no se numera: el numero de lazo depende del area final, que
    # puede completarse en el Paso 2 por herencia de Scope.
    # ------------------------------------------------------------
    interim = []
    for tag in root.iter("Tag"):
        nombre = tag.get("Name", "")
        tagtype = tag.get("TagType", "Base")
        aliasfor = tag.get("AliasFor", "")
        datatype = tag.get("DataType", "")
        desc_el = tag.find(".//Description")
        descripcion = (desc_el.text or "").strip() if desc_el is not None else ""

        if _clasificar_con_aprendizaje is not None:
            clase, funcion, area, notas = _clasificar_con_aprendizaje(
                nombre, tagtype, aliasfor, datatype, plc_nombre,
                operandos_crudos_escalado, conn=conn_aprendizaje,
            )
        else:
            clase, funcion, area, notas = clasificar(
                nombre, tagtype, aliasfor, datatype, operandos_crudos_escalado
            )
        notas = validar_reglas(nombre, funcion, notas, clase)

        interim.append({
            "tag_viejo": nombre, "clase": clase, "funcion_ISA": funcion or "",
            "area_detectada": area or "", "datatype": datatype, "alias_for": aliasfor,
            "descripcion": descripcion, "notas": notas,
        })

    # Indice auxiliar: tags cuya area SI se detecto por su propio nombre
    # (usado como evidencia para el voto por mayoria del Paso 2).
    indice_area_por_nombre = {
        f["tag_viejo"].upper(): mapeo_area_efectivo[f["area_detectada"]]
        for f in interim if f["area_detectada"] and mapeo_area_efectivo.get(f["area_detectada"])
    }

    # ------------------------------------------------------------
    # Paso 2: herencia de area por Scope (Program/Routine) para los tags
    # que NO tienen ningun token de area en su propio nombre.
    # ------------------------------------------------------------
    tag_a_programa, programa_area, rutina_info = construir_indice_scope(root, mapeo_area_efectivo)
    cod_area_heredado_por_tag = {}
    for fila in interim:
        if fila["area_detectada"]:
            continue
        cod_area, metodo, confianza = heredar_area_por_scope(
            fila["tag_viejo"], tag_a_programa, programa_area, rutina_info, indice_area_por_nombre
        )
        if cod_area and confianza == "ALTA":
            cod_area_heredado_por_tag[fila["tag_viejo"]] = (cod_area, metodo)
            fila["notas"].append(f"Area heredada por Scope: {metodo}")
        elif cod_area:
            cod_area_heredado_por_tag[fila["tag_viejo"]] = (None, None)
            fila["notas"].append(f"Area candidata por Scope (confianza BAJA, confirmar manualmente): {metodo} -> '{cod_area}'")
        else:
            cod_area_heredado_por_tag[fila["tag_viejo"]] = (None, None)

    # ------------------------------------------------------------
    # Paso 2.5: segundo filtro -> inferencia semantica por palabras clave
    # de proceso, solo para los tags que SIGUEN sin area resuelta despues
    # del Paso 2 (ni nombre propio, ni Scope con confianza ALTA).
    # ------------------------------------------------------------
    for fila in interim:
        cod_area_actual, _ = cod_area_heredado_por_tag.get(fila["tag_viejo"], (None, None))
        if fila["area_detectada"] or cod_area_actual:
            continue  # ya resuelto antes: no se pisa
        cod_area_kw, evidencia = area_por_palabras_clave(fila["tag_viejo"])
        if cod_area_kw == "AMBIGUO":
            resumen_amb = ", ".join(f"{a} por '{kw}'" for a, kw in evidencia.items())
            fila["notas"].append(f"Palabra clave AMBIGUA: coincide con mas de un area ({resumen_amb}) - revisar manualmente")
        elif cod_area_kw:
            cod_area_heredado_por_tag[fila["tag_viejo"]] = (cod_area_kw, f"palabra clave de proceso '{evidencia}'")
            fila["notas"].append(f"Area asignada por palabra clave de proceso: '{evidencia}' -> {cod_area_kw}")

    # ------------------------------------------------------------
    # Paso 2.6: ULTIMO RECURSO -> area por defecto del controlador (PLC
    # mono-area). Solo alcanza a los tags que siguen sin area tras todas
    # las capas anteriores; nunca pisa una deteccion previa.
    # ------------------------------------------------------------
    if area_defecto:
        for fila in interim:
            cod_area_actual, _ = cod_area_heredado_por_tag.get(fila["tag_viejo"], (None, None))
            if fila["area_detectada"] or cod_area_actual:
                continue
            cod_area_heredado_por_tag[fila["tag_viejo"]] = (
                area_defecto, f"area por defecto del controlador ({area_defecto})"
            )
            fila["notas"].append(
                f"Area asignada por DEFECTO del controlador (PLC mono-area): {area_defecto}"
            )

    # ------------------------------------------------------------
    # Paso 3: numerar FUNCIONAL_ISA / FISICO_ISA, ya con el area final
    # (propia o heredada), y armar las filas definitivas.
    # ------------------------------------------------------------
    contador = defaultdict(int)
    resumen = defaultdict(int)
    filas = []
    for fila in interim:
        area_label = fila["area_detectada"]
        if area_label:
            cod_area = mapeo_area_efectivo.get(area_label)
        else:
            cod_area, _ = cod_area_heredado_por_tag.get(fila["tag_viejo"], (None, None))

        tag_nuevo = proponer_tag(fila["clase"], cod_area, fila["funcion_ISA"] or None, contador)
        resumen[fila["clase"]] += 1
        filas.append({
            "tag_viejo": fila["tag_viejo"],
            "clase": fila["clase"],
            "funcion_ISA": fila["funcion_ISA"],
            "area_detectada": area_label,
            "cod_area": cod_area or "",
            "datatype": fila["datatype"],
            "alias_for": fila["alias_for"],
            "tag_nuevo_propuesto": tag_nuevo,
            "descripcion": fila["descripcion"],
            "validacion": " | ".join(fila["notas"]),
        })

    # ------------------------------------------------------------
    # Paso 4: agrupar los tags INTERNA como miembros de UDT (o logica de
    # estado con area por nombre/herencia). Requiere que los tags
    # FUNCIONAL_ISA/FISICO_ISA ya tengan numero de lazo (Paso 3).
    # ------------------------------------------------------------
    indice_base = {
        f["tag_viejo"].upper(): f for f in filas
        if f["clase"] in ("FUNCIONAL_ISA", "FISICO_ISA")
    }
    indice_pendiente = {
        f["tag_viejo"].upper(): f for f in filas if f["clase"] == "SIN_CLASIFICAR"
    }
    # grafo_fbd ya se construyo al inicio de procesar() (Paso 1); se reutiliza.

    for fila in filas:
        clase = fila["clase"]

        # R3: alias discreto -> miembro de la UDT Motor_AC del equipo.
        # El nombre del equipo es el resto del tag tras el prefijo de estado
        # (ESTADO_BBA_AGUA_ESTE -> equipo 'BBA_AGUA_ESTE').
        if clase == "EQUIPO_DISCRETO":
            prefijo, miembro = detectar_miembro_equipo(fila["tag_viejo"])
            cod_area = fila["cod_area"]
            if not miembro:
                fila["tag_nuevo_propuesto"] = "PENDIENTE (alias discreto sin prefijo de estado reconocible)"
                continue
            equipo = fila["tag_viejo"][len(prefijo):]
            equipo = re.sub(r"[^A-Z0-9_]", "_", equipo.upper()).strip("_")
            if not equipo:
                fila["tag_nuevo_propuesto"] = "PENDIENTE (no se pudo derivar el nombre del equipo)"
                continue
            if not cod_area:
                fila["tag_nuevo_propuesto"] = f"PENDIENTE (equipo '{equipo}.{miembro}' sin area resuelta)"
                continue
            fila["tag_nuevo_propuesto"] = f"{cod_area}_{equipo}.{miembro}"
            continue

        if clase not in ("INTERNA", "INTERNA_SISTEMA"):
            continue

        tag_nuevo, nota_udt = transformar_interna_a_miembro(
            fila, indice_base, indice_pendiente, grafo_fbd, cod_area_heredado_por_tag,
            mapeo_area_efectivo
        )
        fila["tag_nuevo_propuesto"] = tag_nuevo
        fila["validacion"] = (fila["validacion"] + " | " + nota_udt).strip(" |")

    return filas, resumen


def main():
    if len(sys.argv) < 2:
        print("Uso: python auditar_l5x.py <archivo.L5X>")
        sys.exit(1)
    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"No existe el archivo: {path}")
        sys.exit(1)

    filas, resumen = procesar(path, area_defecto=area_defecto_para(path))

    base = os.path.splitext(os.path.basename(path))[0]
    dir_salida = DIR_SALIDA_INDIVIDUAL
    os.makedirs(dir_salida, exist_ok=True)
    campos = ["tag_viejo", "clase", "funcion_ISA", "area_detectada", "cod_area",
              "datatype", "alias_for", "tag_nuevo_propuesto", "descripcion", "validacion"]

    # Filtro estricto de base de datos limpia: cualquier fila cuyo
    # tag_nuevo_propuesto contenga 'PENDIENTE' o no se haya podido resolver
    # (???) va a la planilla de revision de campo, sin importar su clase.
    # mapeo_<base>.csv queda SOLO con tags mapeados/aprobados con exito.
    def es_pendiente(f):
        return "PENDIENTE" in f["tag_nuevo_propuesto"] or "???" in f["tag_nuevo_propuesto"]

    filas_limpias = [f for f in filas if not es_pendiente(f)]
    filas_pendientes = [f for f in filas if es_pendiente(f)]

    salida = os.path.join(dir_salida, f"mapeo_{base}.csv")
    with open(salida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        w.writeheader()
        w.writerows(filas_limpias)

    salida_sc = os.path.join(dir_salida, "sin_clasificar.csv")
    with open(salida_sc, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        w.writeheader()
        w.writerows(filas_pendientes)

    total = len(filas)
    print(f"\n=== AUDITORIA L5X: {base} ===")
    print(f"Total de tags procesados: {total}")
    print("-" * 42)
    for clase, n in sorted(resumen.items(), key=lambda x: -x[1]):
        print(f"  {clase:18} {n:4}  ({100*n/total:4.1f}%)")
    alertas = sum(1 for x in filas if x["validacion"])
    print("-" * 42)
    print(f"  Tags con alerta/validacion: {alertas}")
    print(f"  Consolidados en mapeo_{base}.csv (sin PENDIENTE/???): {len(filas_limpias)}")
    print(f"  Movidos a sin_clasificar.csv (PENDIENTE/??? de cualquier clase): {len(filas_pendientes)}")
    print(f"\nCSV de mapeo (base limpia) generado: {salida}")
    print(f"Planilla de revision de campo (PENDIENTE/???): {salida_sc}")

    areas_pendientes = sorted(k for k, v in MAPEO_AREA.items() if v is None)
    if areas_pendientes:
        print("\n*** ATENCION: codigo de area PENDIENTE de definir por el Ingenio ***")
        for a in areas_pendientes:
            print(f"    {a}: aparece '???' en tag_nuevo_propuesto hasta confirmar su serie numerica")


if __name__ == "__main__":
    main()
