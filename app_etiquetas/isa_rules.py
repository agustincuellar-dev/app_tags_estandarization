"""Reglas ISA reutilizables para el asistente obligatorio de Tags App.

Las funciones de este módulo no modifican la UI ni la base: concentran las
reglas que permiten filtrar el catálogo y mantener el orden de las letras.
"""

# Orden de columnas funcionales de ANSI/ISA-5.1.  Una función de lectura
# (I/R/G/S/A) debe preceder a una función activa (T/C/V/K/Q/Y).
_FUNCIONES_PASIVAS = frozenset({"I", "R", "G", "S", "A", "U", "E"})
_FUNCIONES_ACTIVAS = frozenset({"T", "C", "V", "K", "Q", "Y"})

# Restricciones corporativas conservadoras: para Densidad/Brix se habilitan
# únicamente funciones de medición/lectura y alarma. No se propone control o
# válvula porque su semántica depende de una ingeniería de lazo específica.
_RESTRINGIDAS_POR_VARIABLE = {
    "D": frozenset({"T", "IT", "I", "R", "G", "S", "SH", "SL", "A", "AH", "AL", "E", "Q"}),
}


def funcion_sugerida_por_asistente(funcion, tiene_display_local=None, es_visor_directo=None):
    """Devuelve la función canónica resuelta por las respuestas ISA.

    Un transmisor con display local requiere I antes de T (IT). Para un
    dispositivo local sin transmisión, un visor directo usa G y no I.
    """
    codigo = (funcion or "").upper().strip()
    if codigo == "T" and tiene_display_local is not None:
        return "IT" if tiene_display_local else "T"
    if codigo == "I" and es_visor_directo is not None:
        return "G" if es_visor_directo else "I"
    return codigo


def funciones_permitidas_para_variable(variable, funciones_catalogo):
    """Filtra el catálogo a combinaciones autorizadas para la variable.

    El resultado está ordenado para que la lista sea estable y comprobable.
    Las variables sin regla específica conservan el catálogo completo: no se
    inventan prohibiciones cuando el estándar local todavía no las definió.
    """
    disponibles = {str(f).upper().strip() for f in funciones_catalogo}
    permitidas = _RESTRINGIDAS_POR_VARIABLE.get((variable or "").upper().strip())
    if permitidas is not None:
        disponibles &= permitidas
    return tuple(sorted(disponibles))


def validar_funcion_isa(funcion):
    """Valida el orden pasiva -> activa dentro de un bloque funcional.

    Los modificadores H/L/O/C que siguen a una función base quedan admitidos
    como parte de su código de catálogo. La validación evita la inversión
    inequívoca (por ejemplo TI o CI) sin bloquear códigos locales no
    clasificados por esta versión.
    """
    codigo = (funcion or "").upper().strip()
    if not codigo:
        return False, "Seleccione una función ISA."

    indice_activa = next((i for i, letra in enumerate(codigo) if letra in _FUNCIONES_ACTIVAS), None)
    if indice_activa is None:
        return True, ""
    if any(letra in _FUNCIONES_PASIVAS for letra in codigo[indice_activa + 1:]):
        return False, (
            "El orden ISA es inválido: una función pasiva/de lectura debe ir "
            "antes de una función activa/de salida (por ejemplo IT, no TI)."
        )
    return True, ""
