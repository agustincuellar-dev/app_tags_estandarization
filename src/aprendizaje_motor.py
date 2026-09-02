"""
aprendizaje_motor.py
----------------------
Puente entre el motor de auditoria ISA (auditar_l5x.py, sin estado, solo
lee .L5X y escribe CSV) y la capa de Aprendizaje por Excepcion de la Tags
App (app_etiquetas/aprendizaje.py, con estado en tags_ingenio.db).

Se mantiene como modulo separado a proposito: auditar_l5x.py sigue siendo
reutilizable de forma standalone (su propio docstring lo dice: se puede
correr sin la Tags App). Este puente es la UNICA pieza que conoce a los
dos lados.

Uso tipico (dentro del loop de procesar() en auditar_l5x.py, o en
procesar_todos_l5x.py):

    from aprendizaje_motor import clasificar_con_aprendizaje

    clase, funcion, area, notas = clasificar_con_aprendizaje(
        nombre, tagtype, aliasfor, datatype, plc_nombre,
        operandos_crudos_escalado,
    )

En vez de llamar a auditar_l5x.clasificar() directamente. El resultado es
identico salvo en un caso: cuando el motor por codigo devuelve
SIN_CLASIFICAR, este puente consulta la base antes de rendirse -- y si
tampoco hay nada ahi, archiva el tag en la bandeja de pendientes para que
alguien lo resuelva desde la Tags App.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "app_etiquetas"))

import auditar_l5x as motor      # noqa: E402
import aprendizaje as aprend     # noqa: E402
import database                  # noqa: E402


def abrir_conexion():
    """Devuelve una conexion nueva a tags_ingenio.db, con el schema ya
    aplicado (init_db() es idempotente -- seguro llamarla siempre, no
    duplica ni pisa datos existentes). Punto de entrada unico para que
    procesar_todos_l5x.py (u otro orquestador) no necesite saber nada de
    rutas de app_etiquetas/ ni de database.py directamente."""
    database.init_db()
    return database.get_connection()


def clasificar_con_aprendizaje(nombre, tagtype, aliasfor, datatype, plc_nombre,
                                operandos_crudos_escalado=None, conn=None):
    """Igual que auditar_l5x.clasificar(), pero con una segunda pasada
    contra la base de datos cuando el motor no reconoce el tag:

      1. Corre las reglas de codigo de siempre (auditar_l5x.clasificar).
      2. Si el resultado es SIN_CLASIFICAR, busca una regla ya aprendida
         para este tag (buscar_regla) -- si existe, la aplica y el tag
         queda resuelto SIN tocar codigo Python.
      3. Si tampoco hay regla aprendida, archiva el tag en la bandeja de
         pendientes (archivar_pendiente) para revision humana futura, y
         lo deja como SIN_CLASIFICAR en esta corrida (comportamiento
         identico al de hoy -- no se inventa una clasificacion).

    Devuelve la misma tupla (clase, funcion, area, notas) que
    auditar_l5x.clasificar(), para que sea un reemplazo directo (drop-in)
    en cualquier lugar que hoy llame a clasificar()."""
    clase, funcion, area, notas = motor.clasificar(
        nombre, tagtype, aliasfor, datatype, operandos_crudos_escalado
    )

    if clase != "SIN_CLASIFICAR":
        return clase, funcion, area, notas

    regla = aprend.buscar_regla(nombre, plc_nombre, datatype, conn=conn)
    if regla:
        notas = list(notas) + [
            f"Resuelto por regla aprendida #{regla['regla_id']} "
            f"(Tags App, sin tocar auditar_l5x.py)"
        ]
        if regla["accion"] == "FUNCION_ISA":
            return "FUNCIONAL_ISA", regla["funcion_isa"], area, notas
        # INTERNA / EQUIPOS_LOGICA / FISICO_ISA: la accion es la clase.
        return regla["accion"], funcion, area, notas

    # Nadie lo reconoce todavia: a la bandeja de pendientes, no al olvido
    # de un CSV que nadie vuelve a abrir.
    motivo = " | ".join(notas) if notas else "No encaja en ningun criterio"
    aprend.archivar_pendiente(
        nombre, plc_nombre, datatype=datatype, alias_for=aliasfor or "",
        motivo_no_clasificado=motivo, conn=conn,
    )
    return clase, funcion, area, notas
