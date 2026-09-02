"""Validador ISA-5.1 para la Tags App.

Audita un tag recién guardado contra las reglas de lazo cerrado y de
indicadores locales definidas en REGLAS_VALIDACION.
"""

REGLAS_VALIDACION = {
    "LAZOS_CERRADOS": {
        "SENSOR": "T",
        "CONTROLADOR": "C",
        "ACTUADOR": "V",
    },
    "INDICADORES_LOCALES": ("I", "R"),
}

_ETIQUETA_ROL = {"T": "T", "C": "IC", "V": "V"}
_NOMBRE_ROL = {
    "SENSOR": "Transmisor (sensor)",
    "CONTROLADOR": "Controlador",
    "ACTUADOR": "Actuador (válvula)",
}


def _rol_de_funcion(funcion):
    if "C" in funcion:
        return "CONTROLADOR"
    if "T" in funcion:
        return "SENSOR"
    if "V" in funcion:
        return "ACTUADOR"
    return None


def _tag_completo_de(tag):
    if isinstance(tag, str):
        return tag
    try:
        return tag["tag_completo"]
    except (KeyError, TypeError):
        return None


def _parsear_tag(tag):
    tag_completo = _tag_completo_de(tag)
    if not tag_completo:
        return None
    partes = tag_completo.split("_")
    if len(partes) != 3:
        return None
    area, nucleo, lazo = partes
    if not nucleo or not lazo:
        return None
    variable, funcion = nucleo[0], nucleo[1:]
    if not funcion:
        return None
    return area, variable, funcion, lazo


def auditar_tag_recien_guardado(tag_guardado, lista_tags_existentes):
    datos = _parsear_tag(tag_guardado)
    if datos is None:
        return (), ()
    area, variable, funcion, lazo = datos

    rol = _rol_de_funcion(funcion)
    if rol is None:
        return (), ()

    mismo_lazo = []
    for t in lista_tags_existentes:
        d = _parsear_tag(t)
        if d and d[0] == area and d[1] == variable and d[3] == lazo:
            mismo_lazo.append(d)

    faltantes_obligatorios = []
    for rol_requerido, letra in REGLAS_VALIDACION["LAZOS_CERRADOS"].items():
        if rol_requerido == rol:
            continue
        cubierto = any(letra in d[2] for d in mismo_lazo)
        if not cubierto:
            tag_meta = f"{area}_{variable}{_ETIQUETA_ROL[letra]}_{lazo}"
            faltantes_obligatorios.append(
                f"Falta {_NOMBRE_ROL[rol_requerido]} ({tag_meta})"
            )

    sugerencias_locales = []
    hay_indicador = any(
        _rol_de_funcion(d[2]) is None
        and any(il in d[2] for il in REGLAS_VALIDACION["INDICADORES_LOCALES"])
        for d in mismo_lazo
    )
    if not hay_indicador:
        tag_sugerido = f"{area}_{variable}I_{lazo}"
        sugerencias_locales.append(f"Sugerencia: indicador local {tag_sugerido}")

    return faltantes_obligatorios, sugerencias_locales
