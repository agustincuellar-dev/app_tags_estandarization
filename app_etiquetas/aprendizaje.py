"""
aprendizaje.py
----------------
Aprendizaje por Excepción: reemplaza el patrón de "parche global en
Python" (agregar una constante nueva a auditar_l5x.py y volver a correr
el motor sobre los 12 PLCs) por reglas que viven en la base de datos.

Flujo:
  1. El motor de auditoría clasifica un tag con sus reglas de código
     (auditar_l5x.clasificar()). Si el tag queda SIN_CLASIFICAR, se
     consulta esta tabla ANTES de darlo por perdido (buscar_regla()).
  2. Si tampoco hay regla aprendida, el tag se archiva en la bandeja de
     pendientes (archivar_pendiente()) en vez de morir en un CSV que
     nadie vuelve a abrir.
  3. Un usuario revisa la bandeja (agrupada por prefijo/datatype, igual
     análisis que se hace hoy a mano), y con un clic define la regla
     (resolver_pendiente()). Esa regla queda persistida: la PRÓXIMA
     corrida del motor la aplica sola, sin que nadie toque código.

Reutiliza database.get_connection() -- misma base de datos
(tags_ingenio.db) que el resto de la Tags App. Import típico desde el
motor de auditoría (src/), ver src/aprendizaje_motor.py para el puente.
"""

import re
import sqlite3
from datetime import datetime

import database


# ------------------------------------------------------------------
# 1. Consultar si un tag desconocido ya tiene una excepción aprendida
# ------------------------------------------------------------------
def buscar_regla(tag_original, plc_nombre, datatype="", conn=None):
    """Busca si `tag_original` ya fue catalogado antes en
    `reglas_aprendidas`. Devuelve un dict con la accion a aplicar, o
    None si no hay ninguna regla que lo cubra.

    Orden de prioridad (de más a menos específico):
      1. Match EXACTO scoped a este PLC.
      2. Match EXACTO global (plc_nombre IS NULL, aplica a cualquier PLC).
      3. Match por PREFIJO scoped a este PLC (el patrón más largo gana).
      4. Match por PREFIJO global (el patrón más largo gana).

    Devuelve, por ejemplo:
        {"accion": "FUNCION_ISA", "funcion_isa": "F", "regla_id": 12}
        {"accion": "INTERNA", "funcion_isa": None, "regla_id": 7}
    o None si el tag no está cubierto por ninguna regla todavía.
    """
    cerrar = conn is None
    conn = conn or database.get_connection()
    try:
        tag_up = tag_original.upper()

        # 1-2: EXACTO, scoped primero, luego global.
        for scope_sql, params in (
            ("plc_nombre = ?", (tag_up, plc_nombre)),
            ("plc_nombre IS NULL", (tag_up,)),
        ):
            fila = conn.execute(
                f"""
                SELECT id, accion, funcion_isa FROM reglas_aprendidas
                WHERE activo = 1 AND tipo_match = 'EXACTO'
                  AND patron = ? AND {scope_sql}
                LIMIT 1
                """,
                params,
            ).fetchone()
            if fila:
                return {"accion": fila["accion"], "funcion_isa": fila["funcion_isa"], "regla_id": fila["id"]}

        # 3-4: REGEX, scoped primero, luego global. Va ANTES que PREFIJO
        # porque es la forma mas especifica de las dos: una familia que
        # comparte prefijo pero se parte por sufijo (ME*_CORRENTE -> IT vs
        # ME*_Reference -> INTERNA) necesita que el regex gane sobre
        # cualquier regla de prefijo 'ME' mas general.
        for scope_sql, params in (
            ("plc_nombre = ?", (plc_nombre,)),
            ("plc_nombre IS NULL", ()),
        ):
            candidatas = conn.execute(
                f"""
                SELECT id, patron, accion, funcion_isa FROM reglas_aprendidas
                WHERE activo = 1 AND tipo_match = 'REGEX' AND {scope_sql}
                """,
                params,
            ).fetchall()
            for f in candidatas:
                try:
                    if re.match(f["patron"], tag_original, re.IGNORECASE):
                        return {"accion": f["accion"], "funcion_isa": f["funcion_isa"], "regla_id": f["id"]}
                except re.error:
                    # Regex invalida cargada a mano: se ignora en vez de
                    # tumbar toda la corrida del motor.
                    continue

        # 5-6: PREFIJO, scoped primero, luego global. Entre varios
        # prefijos que matchean, gana el más largo (más específico) --
        # ej. si existiera 'FIT10' y 'FIT100', 'FIT100' pisa a 'FIT10'.
        for scope_sql, params in (
            ("plc_nombre = ?", (plc_nombre,)),
            ("plc_nombre IS NULL", ()),
        ):
            candidatas = conn.execute(
                f"""
                SELECT id, patron, accion, funcion_isa FROM reglas_aprendidas
                WHERE activo = 1 AND tipo_match = 'PREFIJO' AND {scope_sql}
                """,
                params,
            ).fetchall()
            matches = [f for f in candidatas if tag_up.startswith(f["patron"].upper())]
            if matches:
                mejor = max(matches, key=lambda f: len(f["patron"]))
                return {"accion": mejor["accion"], "funcion_isa": mejor["funcion_isa"], "regla_id": mejor["id"]}

        return None
    finally:
        if cerrar:
            conn.close()


# ------------------------------------------------------------------
# 2. Archivar un tag sin clasificar en la bandeja de pendientes
# ------------------------------------------------------------------
def archivar_pendiente(tag_original, plc_nombre, datatype="", alias_for="",
                        motivo_no_clasificado="", conn=None):
    """Si el tag no existe todavía en la bandeja para este PLC, lo
    inserta con estado 'Pendiente'. Si ya existe (misma corrida anterior
    ya lo detectó, o ya fue resuelto/descartado), NO lo toca -- evita
    resetear a 'Pendiente' un tag que un usuario ya resolvió a mano.

    Devuelve True si se archivó un registro nuevo, False si ya existía."""
    cerrar = conn is None
    conn = conn or database.get_connection()
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO tags_no_clasificados
                (plc_nombre, tag_original, datatype, alias_for, motivo_no_clasificado)
            VALUES (?, ?, ?, ?, ?)
            """,
            (plc_nombre, tag_original, datatype, alias_for, motivo_no_clasificado),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        if cerrar:
            conn.close()


def listar_pendientes(plc_nombre=None, estado="Pendiente", conn=None):
    """Devuelve la bandeja de pendientes, opcionalmente filtrada por PLC
    y estado. Pensada para que la pantalla de la Tags App la agrupe por
    datatype/prefijo del mismo modo que se hizo a mano en las sesiones
    de auditoría (ver Roadmap_Arquitectura_Inteligente.md, sección 3)."""
    cerrar = conn is None
    conn = conn or database.get_connection()
    try:
        sql = "SELECT * FROM tags_no_clasificados WHERE 1=1"
        params = []
        if plc_nombre:
            sql += " AND plc_nombre = ?"
            params.append(plc_nombre)
        if estado:
            sql += " AND estado = ?"
            params.append(estado)
        sql += " ORDER BY plc_nombre, tag_original"
        return conn.execute(sql, params).fetchall()
    finally:
        if cerrar:
            conn.close()


# ------------------------------------------------------------------
# 3. Resolver un pendiente: crear la regla y aplicarla retroactivamente
#    a todo lo que ya estaba archivado con ese mismo patrón
# ------------------------------------------------------------------
def resolver_pendiente(patron, accion, funcion_isa=None, tipo_match="EXACTO",
                        plc_nombre=None, motivo="", usuario="", conn=None):
    """Punto de entrada para el clic del usuario en la Tags App
    ("mapear FIT100 a la función F de flujo", o "marcar todo lo que
    empiece con PROTEC_ como INTERNA").

    patron       : el tag exacto ('FIT100') o el prefijo ('FIT') según
                   tipo_match.
    accion       : 'FUNCION_ISA' | 'INTERNA' | 'EQUIPOS_LOGICA' | 'FISICO_ISA'.
    funcion_isa  : letra ISA (ej. 'F', 'PT', 'D') -- obligatorio si
                   accion == 'FUNCION_ISA', ignorado en el resto.
    tipo_match   : 'EXACTO' (un tag puntual) o 'PREFIJO' (una familia
                   completa, ej. todo lo que empieza con 'PROTEC_').
    plc_nombre   : None = la regla vale para TODOS los PLCs; si se pasa
                   un nombre, la regla queda scoped a ese PLC (mismo
                   criterio que el caso 'DES' de Calderas_8_9_10:
                   incluso un homónimo problemático se resuelve sin
                   afectar al resto de la planta).
    usuario      : quién resolvió (queda en auditoría / trazabilidad).

    Efecto:
      1. Crea (o reactiva si ya existía inactiva) la fila en
         reglas_aprendidas.
      2. Marca como 'Regla_Creada' TODAS las filas de
         tags_no_clasificados que matchean este patrón -- no solo la
         que disparó el clic, sino cualquier otra ya archivada con el
         mismo prefijo/tag. Así un solo clic resuelve un grupo entero,
         igual que las "reglas por lote" que se armaron a mano durante
         las sesiones de limpieza (ver TRAPICHE2022, Calderas_8_9_10).

    Devuelve (regla_id, cantidad_de_pendientes_resueltos).
    """
    if accion == "FUNCION_ISA" and not funcion_isa:
        raise ValueError("accion='FUNCION_ISA' requiere especificar funcion_isa (ej. 'F', 'PT').")
    if tipo_match not in ("EXACTO", "PREFIJO", "REGEX"):
        raise ValueError(f"tipo_match debe ser 'EXACTO', 'PREFIJO' o 'REGEX', recibido: {tipo_match!r}")
    if tipo_match == "REGEX":
        try:
            re.compile(patron)
        except re.error as e:
            raise ValueError(f"El patron REGEX {patron!r} no es una expresion regular valida: {e}") from e

    cerrar = conn is None
    conn = conn or database.get_connection()
    try:
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # EXACTO/PREFIJO se guardan en mayuscula (el match es
        # case-insensitive por esa via). REGEX se guarda TAL CUAL: pasarlo
        # por .upper() romperia el patron -- '\d' (digito) se convertiria
        # en '\D' (NO-digito), que significa exactamente lo contrario. El
        # match de REGEX ya usa re.IGNORECASE en buscar_regla().
        patron_guardado = patron if tipo_match == "REGEX" else patron.upper()

        try:
            cur = conn.execute(
                """
                INSERT INTO reglas_aprendidas
                    (patron, tipo_match, plc_nombre, accion, funcion_isa, motivo, creado_por)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (patron_guardado, tipo_match, plc_nombre, accion, funcion_isa, motivo, usuario),
            )
            regla_id = cur.lastrowid
        except sqlite3.IntegrityError:
            # La regla ya existia (mismo patron/tipo_match/plc_nombre) --
            # la reactivamos y actualizamos en vez de duplicar.
            conn.execute(
                """
                UPDATE reglas_aprendidas
                SET accion = ?, funcion_isa = ?, motivo = ?, activo = 1,
                    creado_por = ?, fecha_creacion = ?
                WHERE patron = ? AND tipo_match = ?
                  AND (plc_nombre IS ? OR plc_nombre = ?)
                """,
                (accion, funcion_isa, motivo, usuario, ahora,
                 patron_guardado, tipo_match, plc_nombre, plc_nombre),
            )
            regla_id = conn.execute(
                "SELECT id FROM reglas_aprendidas WHERE patron = ? AND tipo_match = ? "
                "AND (plc_nombre IS ? OR plc_nombre = ?)",
                (patron_guardado, tipo_match, plc_nombre, plc_nombre),
            ).fetchone()["id"]

        # Aplicar retroactivamente a todo lo que ya estaba en la bandeja y
        # matchea el patron (scoped al mismo PLC si la regla es scoped).
        # REGEX no se puede resolver en SQL (SQLite no trae REGEXP nativo),
        # asi que se filtra en Python y se actualiza por id.
        if plc_nombre:
            filtro_plc, params_plc = "AND plc_nombre = ?", (plc_nombre,)
        else:
            filtro_plc, params_plc = "", ()

        if tipo_match == "REGEX":
            candidatos = conn.execute(
                f"SELECT id, tag_original FROM tags_no_clasificados "
                f"WHERE estado = 'Pendiente' {filtro_plc}",
                params_plc,
            ).fetchall()
            rx = re.compile(patron, re.IGNORECASE)
            ids = [f["id"] for f in candidatos if rx.match(f["tag_original"])]
            resueltos = 0
            for _id in ids:
                conn.execute(
                    """
                    UPDATE tags_no_clasificados
                    SET estado = 'Regla_Creada', regla_aplicada_id = ?,
                        resuelto_por = ?, fecha_resolucion = ?
                    WHERE id = ?
                    """,
                    (regla_id, usuario, ahora, _id),
                )
                resueltos += 1
        else:
            if tipo_match == "EXACTO":
                filtro_tag, params_tag = "UPPER(tag_original) = ?", (patron.upper(),)
            else:
                filtro_tag, params_tag = "UPPER(tag_original) LIKE ?", (patron.upper() + "%",)
            cur = conn.execute(
                f"""
                UPDATE tags_no_clasificados
                SET estado = 'Regla_Creada', regla_aplicada_id = ?,
                    resuelto_por = ?, fecha_resolucion = ?
                WHERE estado = 'Pendiente' AND {filtro_tag} {filtro_plc}
                """,
                (regla_id, usuario, ahora, *params_tag, *params_plc),
            )
            resueltos = cur.rowcount

        conn.commit()
        return regla_id, resueltos
    finally:
        if cerrar:
            conn.close()


def descartar_pendiente(tag_id, usuario="", conn=None):
    """Marca un pendiente puntual como 'Descartado' (revisado a mano,
    no amerita una regla general -- ej. un tag de prueba/debug que no
    se va a repetir). No crea ninguna regla."""
    cerrar = conn is None
    conn = conn or database.get_connection()
    try:
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            UPDATE tags_no_clasificados
            SET estado = 'Descartado', resuelto_por = ?, fecha_resolucion = ?
            WHERE id = ?
            """,
            (usuario, ahora, tag_id),
        )
        conn.commit()
    finally:
        if cerrar:
            conn.close()
