#!/usr/bin/env python3
"""Genera el addendum Mieles y las fichas pendientes del 23/09/2026.

No escribe SQLite. Las bases se abren con mode=ro + PRAGMA query_only=ON.
Por defecto valida y muestra el plan sin escribir; requiere --write para crear
los dos CSV dedicados y se niega a sobrescribirlos.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXPORTS = ROOT / "exports"
L5X_DIR = ROOT / "L5X_Produccion"
FRONTERA = EXPORTS / "frontera_210_controladores_v4.csv"
PLANTILLA = EXPORTS / "propuesta_numeracion_masiva_v5_210926.csv"
ADDENDUM = EXPORTS / "addendum_propuesta_mieles_230926.csv"
FICHAS = EXPORTS / "fichas_area_pendientes_230926.csv"

sys.path.insert(0, str(SRC))
import generar_propuesta_masiva as propuesta  # noqa: E402
import identificadores_vigentes as ids  # noqa: E402
import trazador_lazos_profundo as trazador  # noqa: E402

INSTANCIAS_MIEL_CONTROL = {
    "CONTROL_NIVEL_TK_MIEL1",
    "CONTROL_NIVEL_TK_MIEL_2",
}
CAMPOS_FICHA = [
    "Caso", "PLC", "Programa", "Rutina", "Identidades_del_lazo",
    "Area_asignada", "Numero_ISA", "Candidatos_de_area_sin_asignar",
    "Prefijos_o_identidades_en_conflicto", "Manual_por_candidato",
    "Canales_fisicos", "Evidencia_de_trazado", "Dato_faltante_para_cerrar",
    "Estado", "Escritura_SQLite",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def db_state(path: Path) -> dict:
    """Hash + integridad en modo estrictamente solo lectura."""
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.execute("PRAGMA query_only=ON")
        assert con.execute("PRAGMA query_only").fetchone()[0] == 1
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        count = con.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    return {"path": str(path), "sha256": sha256(path), "integrity": integrity, "tags": count}


def strict_l5x_numbers(variables: set[str], functions: set[str]) -> tuple[set[int], dict[int, list[str]]]:
    """U4 estricto según identificadores_vigentes, escaneo global conservador.

    La regla es morfema al inicio + número inmediato, no cualquier token dentro
    de nombres de equipos como B_*_TC_07. Global se declara conservador porque
    el proyecto contiene PLCs con varias áreas.
    """
    numbers: set[int] = set()
    evidence: dict[int, list[str]] = defaultdict(list)
    attr_re = re.compile(r'(?:Name|Operand)="([^"]+)"')
    for path in sorted(L5X_DIR.glob("*.L5X")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in attr_re.finditer(text):
            raw = m.group(1)
            n = ids.numero_de_identificador(raw, variables, functions)
            if n is not None:
                numbers.add(n)
                evidence[n].append(f"{path.name}:{raw}")
    return numbers, evidence


def exact_raw_token_hits(number: int) -> list[str]:
    """Escaneo literal de Name/Operand para el número candidato (evidencia, no ISA)."""
    tokens = {str(number), f"{number:03d}"}
    patterns = [re.compile(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])") for token in tokens]
    attr_re = re.compile(r'(?:Name|Operand)="([^"]+)"')
    hits: set[str] = set()
    for path in sorted(L5X_DIR.glob("*.L5X")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in attr_re.finditer(text):
            raw = match.group(1)
            if any(pattern.search(raw) for pattern in patterns):
                hits.add(f"{path.name}:{raw}")
    return sorted(hits)


def inventarios_online() -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for item in ids.extraer_todo():
        out[str(item["area"]).zfill(3)] = {int(n) for n in item["numeros"]}
    return out


def comprimir_numeros(values: set[int]) -> str:
    if not values:
        return "—"
    ordered = sorted(values)
    ranges = []
    start = prev = ordered[0]
    for n in ordered[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append((start, prev))
        start = prev = n
    ranges.append((start, prev))
    return ",".join(f"{a:03d}" if a == b else f"{a:03d}-{b:03d}" for a, b in ranges)


def endpoint_pairs(text: str) -> list[tuple[str, str]]:
    """Devuelve (identidad mostrada, terminal físico) para una lista del trazador."""
    out = []
    for item in (text or "").split(" | "):
        item = item.strip()
        if not item:
            continue
        m = re.match(r"^(.*?)\s+\((.*?)\)$", item)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
        else:
            out.append((item, item))
    return out


def invocation_inventory() -> list[dict]:
    """Invocaciones AOI ejecutables en rutinas de Program de los L5X."""
    found = []
    for path in sorted(L5X_DIR.glob("*.L5X")):
        root = ET.parse(path).getroot()
        programs = root.find(".//Controller/Programs")
        if programs is None:
            continue
        for program in programs.findall("./Program"):
            for routine in program.findall(".//Routine"):
                for node in routine.iter("AddOnInstruction"):
                    name = node.get("Name", "")
                    operand = node.get("Operand", "")
                    if "MIEL" in (name + " " + operand).upper():
                        found.append({
                            "plc": path.stem,
                            "program": program.get("Name", ""),
                            "routine": routine.get("Name", ""),
                            "name": name,
                            "operand": operand,
                        })
    return found


def physical_ref_counts(targets: set[str]) -> dict[str, list[str]]:
    """Busca escrituras FBD y referencias textuales RLL/ST a terminales exactos."""
    found: dict[str, list[str]] = {t: [] for t in targets}
    for path in sorted(L5X_DIR.glob("*.L5X")):
        root = ET.parse(path).getroot()
        programs = root.find(".//Controller/Programs")
        if programs is None:
            continue
        for program in programs.findall("./Program"):
            for routine in program.findall(".//Routine"):
                scope = f"{path.stem}/{program.get('Name','')}/{routine.get('Name','')}"
                for node in routine.iter("ORef"):
                    operand = node.get("Operand", "")
                    if operand in targets:
                        found[operand].append("ORef:" + scope)
                # Structured Text / Ladder CDATA references are not ORef elements.
                for node in routine.iter():
                    if node.tag not in {"Text", "Line"} or not node.text:
                        continue
                    for target in targets:
                        if target in node.text:
                            found[target].append("RLL/ST:" + scope)
    return found


def read_frontier_and_trace() -> tuple[list[dict], dict[str, dict]]:
    with FRONTERA.open("r", encoding="utf-8-sig", newline="") as f:
        frontier = list(csv.DictReader(f, delimiter=";"))
    if len(frontier) != 210:
        raise AssertionError(f"La frontera debía contener 210 filas; contiene {len(frontier)}")
    results = trazador.analizar_filas(frontier)
    target = {r.get("Instancia", ""): r for r in results if r.get("Instancia") in INSTANCIAS_MIEL_CONTROL}
    if set(target) != INSTANCIAS_MIEL_CONTROL:
        raise AssertionError(f"Faltan instancias de control Mieles: {INSTANCIAS_MIEL_CONTROL - set(target)}")
    pendientes = {
        "B_Ctrol_FT_JUGO_SECUNDARIO", "B_Ctrol_LT_TK_ENCALADO", "B_Ctrol_LT_TK_PESADO",
        "COC_LC_MELADO_T", "CONTROL_PRESION_BIO", "CONTROL_CAUDAL_JUGO_DEST",
    }
    encontrados = {r.get("Instancia", "") for r in results}
    if not pendientes.issubset(encontrados):
        raise AssertionError(f"La traza fresca no cubre los casos pendientes: {pendientes - encontrados}")
    for r in results:
        if r.get("Instancia") in pendientes and propuesta.area_del_lazo(r)[0]:
            raise AssertionError(f"Un caso pendiente recibió área: {r.get('Instancia')} -> {propuesta.area_del_lazo(r)}")
    return results, target


def inspect_area700_number() -> dict:
    # U1: lectura directa de producción para comprobar un número NUEVO; no se
    # regenera ni se renumera ninguna fila congelada. Ambos accesos son mode=ro.
    prod_pairs, prod_tags = propuesta.ocupacion_db(propuesta.DB_PRODUCCION)
    hist_pairs, _hist_tags = propuesta.ocupacion_db(propuesta.BACKUP_693)
    online = inventarios_online()
    variables, functions = ids.cargar_catalogos_isa(propuesta.DB_PRODUCCION)
    u4_numbers, u4_evidence = strict_l5x_numbers(variables, functions)
    u5 = propuesta.ocupacion_docs()
    occupied_700 = {n for area, n in prod_pairs | hist_pairs if area == "700"}
    occupied_700 |= online.get("700", set())
    occupied_700 |= u5.get("700", set())
    # U4 es global y estricto (conservador entre áreas); se declara explícitamente.
    occupied_for_new = occupied_700 | u4_numbers
    number = next((n for n in range(1, 1000) if n not in occupied_for_new), None)
    if number is None:
        raise RuntimeError("No se halló número libre en 1..999")
    if number in u4_evidence:
        raise AssertionError("El candidato aparece como identificador ISA válido en U4")
    tags = [f"700_LT_{number:03d}", f"700_LIC_{number:03d}", f"700_LY_{number:03d}"]
    if any(tag in prod_tags for tag in tags):
        raise AssertionError("Algún Tag_Propuesto ya existe en U1")
    return {
        "number": number,
        "occupied_700": occupied_700,
        "u1_700": {n for area, n in prod_pairs if area == "700"},
        "u2_700": {n for area, n in hist_pairs if area == "700"},
        "u3_700": online.get("700", set()),
        "u4_all_strict": u4_numbers,
        "u4_evidence": u4_evidence,
        "u5_700": u5.get("700", set()),
        "tags": tags,
    }


def build_rows() -> tuple[list[str], list[dict], list[dict], dict]:
    with PLANTILLA.open("r", encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f, delimiter=";"))
    if "Requiere_Autorizacion" not in header:
        header.append("Requiere_Autorizacion")
    trace_rows, miel = read_frontier_and_trace()
    t1 = miel["CONTROL_NIVEL_TK_MIEL1"]
    t2 = miel["CONTROL_NIVEL_TK_MIEL_2"]
    area1 = propuesta.area_del_lazo(t1)
    area2 = propuesta.area_del_lazo(t2)
    if area1[0] != "700" or area2[0] != "700":
        raise AssertionError(f"El override explícito no resolvió Mieles a 700: {area1}, {area2}")

    input2 = endpoint_pairs(t2.get("Entrada_Fisica", ""))
    output2 = endpoint_pairs(t2.get("Salida_Fisica", ""))
    if len(input2) != 1 or "FLEX5000_MIELES:1:I.Ch01.Data" not in input2[0][1]:
        raise AssertionError(f"Entrada física de Miel_2 no cerrada: {input2}")
    if len(output2) != 2:
        raise AssertionError(f"Se esperaban dos salidas físicas para Miel_2: {output2}")
    output_names = [name for name, _ in output2]
    if not all(name.startswith("WEG_MIEL_") and ":O.Data[1]" in name for name in output_names):
        raise AssertionError(f"Las salidas no son los dos módulos WEG esperados: {output_names}")

    # El módulo es un terminal físico declarado; conservar su CatalogNumber tal
    # como está en XML y no inventar el modelo del variador.
    xml = ET.parse(L5X_DIR / "FABRICA.L5X").getroot()
    module_catalog = {}
    for node in xml.iter("Module"):
        name = node.get("Name", "")
        if name in {out.split(":O.", 1)[0] for out in output_names}:
            module_catalog[name] = node.get("CatalogNumber", "")
    catalogs = [module_catalog.get(out.split(":O.", 1)[0], "") for out in output_names]
    if len(catalogs) != 2 or not catalogs[0] or catalogs[0] != catalogs[1]:
        raise AssertionError(f"R-C no probado por tipo de módulo común: {catalogs}")

    # Índice inverso global de los 210 controladores: no aceptar extremos usados
    # por otro lazo. También verificar ORef alternativos en todos los L5X.
    endpoint_users: dict[str, set[str]] = defaultdict(set)
    for result in trace_rows:
        instancia = result.get("Instancia", "")
        for _name, physical in endpoint_pairs(result.get("Entrada_Fisica", "")):
            endpoint_users[physical].add(instancia)
        for _name, physical in endpoint_pairs(result.get("Salida_Fisica", "")):
            endpoint_users[physical].add(instancia)
    target_physical = {physical for _name, physical in output2}
    for _name, physical in input2:
        if endpoint_users.get(physical, set()) - {"CONTROL_NIVEL_TK_MIEL_2"}:
            raise AssertionError(f"PV físico compartido con otro controlador: {physical}")
    for physical in target_physical:
        if endpoint_users.get(physical, set()) - {"CONTROL_NIVEL_TK_MIEL_2"}:
            raise AssertionError(f"Salida física compartida con otro controlador: {physical}")
    refs = physical_ref_counts(set(output_names))
    for name in output_names:
        if len(refs[name]) != 1 or not refs[name][0].startswith("ORef:"):
            raise AssertionError(f"Escritura alternativa o ambigua en {name}: {refs[name]}")

    occupied = inspect_area700_number()
    number = occupied["number"]
    num3 = f"{number:03d}"
    occupied_summary = comprimir_numeros(occupied["occupied_700"])
    u4_global_only = []
    for n in sorted(occupied["u4_evidence"]):
        if n < number and n not in occupied["occupied_700"]:
            values = sorted(set(occupied["u4_evidence"][n]))
            u4_global_only.append(f"{n:03d}: {', '.join(values[:3])}")
    u4_blocker_note = "; ".join(u4_global_only) if u4_global_only else "ninguno"
    raw_token_hits = exact_raw_token_hits(number)
    raw_examples = [x for x in raw_token_hits if x.startswith(("CENTRIFUGA_DE_PRIMERA.L5X:", "FABRICA.L5X:"))][:8]
    raw_token_note = (
        f"Escaneo literal Name/Operand del token {number:03d}: {len(raw_token_hits)} identidades XML con coincidencia; "
        f"ejemplos en PLC/área objetivo: {', '.join(raw_examples) if raw_examples else 'ninguno'}. "
        "Los ejemplos son tokens de bloque/slot; el conjunto literal también contiene nombres de equipo/canales. "
        "Se informan como evidencia, no como números de lazo: no tienen morfema ISA válido."
    )
    free_sources = (
        "U1_DB_produccion (mode=ro; solo colisión de alta nueva) | U2_backup_693 | "
        "U3_inventario_online | U4_identificadores_L5X (morfema estricto, global conservador) | "
        "U5_documentacion | U4 global-only previos: " + u4_blocker_note + f"; {number:03d} sin coincidencia U4 estricta"
    )
    area_criterion = "Decisión explícita de usuario 23/09/2026: TK_MIEL*, *MIEL_CENT*, *MIEL_RICA* y canales FLEX5000_MIELES → área 700; regla acotada a FABRICA."
    variable_criterion = "LT_TK_MIEL_RICA_2 (REAL) alimenta PV por SCL desde el canal físico; variable L, confirmada por el morfema LT."
    pin = t2.get("Pin_Salida", "MV_VALV_NC") or "MV_VALV_NC"
    if pin != "MV_VALV_NC":
        raise AssertionError(f"Pin de salida inesperado: {pin}")
    path_in = t2.get("Entrada_Camino", "") or t2.get("Camino_XML", "")
    input_address = input2[0][1]
    output_members = " | ".join(output_names)
    catalog_note = f"Ambos terminales son module-owned; CatalogNumber={catalogs[0]} en el L5X. El modelo concreto del drive no está declarado; no se infiere."
    invocation_list = invocation_inventory()
    counts = defaultdict(list)
    for item in invocation_list:
        counts[item["name"]].append(item["operand"])
    controls = {x for x in counts.get("CONTROL_NIVEL", [])}
    motor_starts = sorted(counts.get("ARRANQUE_MOTOR_2", []))
    limiters = sorted(counts.get("LIMITADOR", []))
    if not {"CONTROL_NIVEL_TK_MIEL1", "CONTROL_NIVEL_TK_MIEL_2"}.issubset(controls):
        raise AssertionError(f"Invocaciones de control no verificadas: {controls}")
    if len(motor_starts) != 15 or len(limiters) != 2 or len(invocation_list) != 19:
        raise AssertionError(f"Inventario Mieles inesperado: AOI={len(invocation_list)}, motores={len(motor_starts)}, limitadores={len(limiters)}")
    other_calls_note = (
        "Inventario adicional XML (no se numeran como lazos): 15 ARRANQUE_MOTOR_2 sin PV de proceso: "
        + ", ".join(motor_starts)
        + "; 2 LIMITADOR (timer-only): " + ", ".join(limiters)
        + ". CONTROL_NIVEL_TK_MIEL y CONTROL_NIVEL_TK_MIEL2 son declaraciones sin invocación. "
        "Los LIMITADOR solo alimentan tiempos de cambio; no son lazos con PV/MV físicos."
    )

    rows = []
    def proposal_row(**values):
        row = {key: "" for key in header}
        row.update(values)
        row["Estado_Propuesta"] = "NO_INSERTAR"
        row["Escritura_SQLite"] = "NO"
        row["Requiere_Autorizacion"] = "SI"
        return row

    lazo2 = "FABRICA/FAB_ESCALADOS/CONTROL_NIVEL_TK_MIEL_2"
    common = {
        "Lazo": lazo2, "PLC": "FABRICA", "Program": "FAB_ESCALADOS",
        "Routine": "AGITADORES_JUGO_DESTIL_PID", "Instancia_AOI": "CONTROL_NIVEL_TK_MIEL_2",
        "Tipo_AOI": "CONTROL_NIVEL", "Prioridad_Frontera": "4", "Area": "700",
        "Variable_ISA": "L", "Numero_Propuesto": num3,
        "Area_Criterio": area_criterion, "Area_Confianza": "ALTA",
        "Variable_Criterio": variable_criterion,
        "Numeros_Ocupados_Area_Resumen": occupied_summary,
        "Numero_Libre_En": free_sources,
        "Clasificacion_Trazado": "CERRABLE_HOY_R-A+R-C",
        "Camino_XML": (
            f"FABRICA.L5X/Program:FAB_ESCALADOS/Routine:AGITADORES_JUGO_DESTIL_PID; "
            f"{input_address} -> SCL -> LT_TK_MIEL_RICA_2 -> {lazo2}.PV; "
            f"{lazo2}.{pin} (REAL) -> {output_members}"
        ),
    }
    rows.append(proposal_row(**common, Rol="ENTRADA", Funcion_ISA="T", Tag_Propuesto=f"700_LT_{num3}",
        Migrado_De="LT_TK_MIEL_RICA_2", Nota_Migrado_De="Tag base REAL conectado al PV; el canal es la fuente física cruda, no un AliasFor.",
        AliasFor_Direccion_Fisica=f"CANAL_CRUDO:{input_address}", Pin_Salida="",
        Descripcion_Propuesta=f"Transmisor de nivel de tanque de miel; PV PLC LT_TK_MIEL_RICA_2; número propuesto para revisión.",
        Fluido_Proceso="Miel", Tipo_Senal="Analógico", Entrada_Salida_BD="Entrada", DataType_BD="REAL",
        Nota_Convencion="Variable L confirmada por LT; área por decisión explícita Mieles=700.",
        Entrada_Operando="LT_TK_MIEL_RICA_2", Nota_Trazado=path_in + "; " + raw_token_note))
    rows.append(proposal_row(**common, Rol="CONTROLADOR", Funcion_ISA="IC", Tag_Propuesto=f"700_LIC_{num3}",
        Migrado_De="CONTROL_NIVEL_TK_MIEL_2", Nota_Migrado_De="Instancia AOI ejecutada; recibe PV desde LT_TK_MIEL_RICA_2.",
        AliasFor_Direccion_Fisica="", Pin_Salida="",
        Descripcion_Propuesta="Controlador indicador de nivel para el tanque de miel; número propuesto para revisión.",
        Fluido_Proceso="Miel", Tipo_Senal="Analógico", Entrada_Salida_BD="Memoria / Red", DataType_BD="REAL",
        Nota_Convencion="Función IC según convención de propuesta masiva; no es escritura en SQLite.",
        Entrada_Operando="LT_TK_MIEL_RICA_2", Nota_Trazado=("PV físico único; extremos sin compartir en el índice inverso global de 210 controladores. " + raw_token_note)))
    rows.append(proposal_row(**common, Rol="SALIDA", Funcion_ISA="Y", Tag_Propuesto=f"700_LY_{num3}",
        Migrado_De=output_members, Nota_Migrado_De=catalog_note,
        AliasFor_Direccion_Fisica=output_members, Pin_Salida=pin,
        Descripcion_Propuesta="Elemento final motriz WEG en paralelo; función Y propuesta por regla R-A; dos destinos agrupados por R-C.",
        Fluido_Proceso="Miel", Tipo_Senal="Analógico", Entrada_Salida_BD="Salida", DataType_BD="REAL",
        Nota_Convencion="R-A aprobada: final no-válvula motriz → Y; R-C: dos destinos WEG con el mismo CatalogNumber declarado.",
        Entrada_Operando="LT_TK_MIEL_RICA_2", Nota_Trazado=catalog_note + " " + raw_token_note))

    # El primer lazo Mieles tiene área resuelta, pero no supera R-C: mezcla un
    # canal crudo sin identidad de equipo y dos destinos module-owned WEG.
    input1 = endpoint_pairs(t1.get("Entrada_Fisica", ""))
    output1 = endpoint_pairs(t1.get("Salida_Fisica", ""))
    if len(output1) != 3 or not any("FLEX5000_MIELES:2:O.Ch00.Data" in x[1] for x in output1):
        raise AssertionError(f"Topología de MIEL1 cambió; requiere revisión: {output1}")
    rows.append(proposal_row(
        Lazo="FABRICA/FAB_ESCALADOS/CONTROL_NIVEL_TK_MIEL1", PLC="FABRICA", Program="FAB_ESCALADOS",
        Routine="AGITADORES_JUGO_DESTIL_PID", Instancia_AOI="CONTROL_NIVEL_TK_MIEL1", Tipo_AOI="CONTROL_NIVEL",
        Prioridad_Frontera="4", Rol="PENDIENTE_R-C", Area="700", Variable_ISA="L", Funcion_ISA="",
        Numero_Propuesto="", Tag_Propuesto="", Migrado_De="LT_TK_MIEL_CENT_1ERA",
        Nota_Migrado_De="PV de nivel trazado; no se propone tag porque los finales no son todos del mismo tipo demostrado.",
        AliasFor_Direccion_Fisica=" | ".join(("CANAL_CRUDO:" + x[1] if "FLEX5000_MIELES" in x[1] else x[0] for x in output1)),
        Pin_Salida=t1.get("Pin_Salida", "MV_VALV_NC"),
        Descripcion_Propuesta="En espera: salida a un canal crudo sin identidad de equipo y dos módulos WEG; no se asigna número.",
        Fluido_Proceso="Miel", Tipo_Senal="Analógico", Entrada_Salida_BD="Salida", DataType_BD="REAL",
        Nota_Convencion="R-C no permite agrupar destinos de tipo distinto o no demostrado.",
        Entrada_Operando="LT_TK_MIEL_CENT_1ERA", Area_Criterio=area_criterion, Area_Confianza="ALTA",
        Variable_Criterio="LT_TK_MIEL_CENT_1ERA alimenta PV; variable L.",
        Numeros_Ocupados_Area_Resumen=occupied_summary, Numero_Libre_En=free_sources,
        Clasificacion_Trazado="PENDIENTE_R-C_NO_NUMERAR",
        Nota_Trazado="Salida con 3 terminales: FLEX5000_MIELES:2:O.Ch00.Data + WEG_MIEL_DE_2DA:O.Data[1] + WEG_MIEL_POBRE_DE_1ERA:O.Data[1]. El canal crudo no identifica el equipo final; R-C no queda probado.",
        Camino_XML=("FABRICA.L5X/Program:FAB_ESCALADOS/Routine:AGITADORES_JUGO_DESTIL_PID; "
                    + (input1[0][1] if input1 else "entrada física no resuelta") + " -> PV; MV_VALV_NC -> "
                    + " | ".join(x[0] for x in output1)),
        Estado_Propuesta="PENDIENTE_R-C — NO_INSERTAR", Escritura_SQLite="NO"))

    # El resto de invocaciones AOI con MIEL en operand son equipos/limitadores,
    # no se convierten en lazos instrumentales sin PV físico.
    rows[1]["Nota_Trazado"] += " " + other_calls_note

    fichas = [
        {
            "Caso": "SULFO_ENCALADO", "PLC": "FABRICA", "Programa": "SULFO_ENCALADO",
            "Rutina": "PID / ESCALADO_AI",
            "Identidades_del_lazo": "B_Ctrol_FT_JUGO_SECUNDARIO; B_Ctrol_LT_TK_ENCALADO; B_Ctrol_LT_TK_PESADO",
            "Area_asignada": "", "Numero_ISA": "", "Candidatos_de_area_sin_asignar": "400 (candidato, no asignado)",
            "Prefijos_o_identidades_en_conflicto": "SULFO_ENCALADO / ENCALADO; no existe override de área específico para esa identidad PLC.",
            "Manual_por_candidato": "Manual_Estandarizacion.md, línea 91: área 400 = Clarificación y Encalado. El Manual no relaciona explícitamente el identificador PLC SULFO_ENCALADO con esa área; por eso 400 sigue siendo candidato, no asignación.",
            "Canales_fisicos": "FT_JUGO_SECUNDARIO: alias Slot_FT_JUGO_SECUNDARIO -> SULFO_ENCALADO:3:I.Ch0Data; otra señal escalada FT_JUGO_SECUNDARIO_REAL usa SULFO_ENCALADO:3:I.Ch1Data. LT_JUGO_ENCALADO: SULFO_ENCALADO:1:I.Ch[1].Data; salidas SULFO_ENCALADO:8:O.Ch2Data/SULFO_ENCALADO:8:O.Ch3Data. LT_JUGO_PESADO: SULFO_ENCALADO:1:I.Ch[0].Data; salidas SULFO_ENCALADO:8:O.Ch0Data/SULFO_ENCALADO:8:O.Ch1Data. FT secundario sale por SULFO_ENCALADO:8:O.Ch4Data/SULFO_ENCALADO:8:O.Ch5Data.",
            "Evidencia_de_trazado": "Los tres controladores invocados están bajo Program SULFO_ENCALADO/Routine PID y usan instancias CONTROL_NIVEL_SULFOENCALADO. En FT_JUGO_SECUNDARIO, el PID referencia SCL_07.Out pero el L5X no demuestra un Wire de esa salida hacia el PV; además existen dos candidatos físicos de escala (:3:I.Ch0Data y :3:I.Ch1Data), así que no se elige uno. Los dos lazos de nivel sí tienen aliases de entrada y dos salidas físicas cada uno, pero su pertenencia de área continúa sin prueba documental suficiente. No se asigna área ni número a ninguno.",
            "Dato_faltante_para_cerrar": "Documento de proceso/P&ID o registro de áreas que asigne explícitamente estos equipos a 400 y relacione cada tag SULFO_ENCALADO con el área. Para FT_JUGO_SECUNDARIO falta además el Wire PV exacto y la selección documentada entre los canales de entrada 0 y 1.",
            "Estado": "PENDIENTE_EVIDENCIA; SIN_AREA; SIN_NUMERO; NO_INSERTAR", "Escritura_SQLite": "NO",
        },
        {
            "Caso": "COC_LC_MELADO_T", "PLC": "FABRICA", "Programa": "FAB_COC",
            "Rutina": "COC_LC_PULMON_MELADO_T",
            "Identidades_del_lazo": "Instancia CONTROL_NIVEL COC_LC_MELADO_T; PV COC_LT_MELADO_TRATADO; salida EVAP_S12_FCV_MELADO_TRATADO; pin MV_VALV_NA.",
            "Area_asignada": "", "Numero_ISA": "", "Candidatos_de_area_sin_asignar": "500 (EVAP) / 600 (COC)",
            "Prefijos_o_identidades_en_conflicto": "COC_LT_MELADO_TRATADO / COC_NIVELES apuntan a 600; EVAP_S12_FCV_MELADO_TRATADO apunta a 500.",
            "Manual_por_candidato": "Manual_Estandarizacion.md, línea 92: área 500 = Evaporación. Línea 93: área 600 = Cocimiento / Tachos. Ambos candidatos tienen definición en el Manual, pero el lazo cruza identidades de ambas áreas.",
            "Canales_fisicos": "Entrada alias COC_S6_LT_MELADO_TRATADO -> ISLA_FAB_AI:6:I.Ch3Data; salida alias EVAP_S12_FCV_MELADO_TRATADO -> ISLA_FAB_AI:12:O.Ch[5].Data.",
            "Evidencia_de_trazado": "En FABRICA.L5X, Program FAB_COC/Routine COC_LC_PULMON_MELADO_T, el PV interno COC_LT_MELADO_TRATADO se resuelve por SCL a COC_S6_LT_MELADO_TRATADO; el MV_VALV_NA llega al alias EVAP_S12_FCV_MELADO_TRATADO. La evidencia física cierra, pero los prefijos de origen y salida discrepan entre COC y EVAP; no se decide el límite de área por inferencia.",
            "Dato_faltante_para_cerrar": "P&ID/lista de equipos con la ubicación de COC_LC_PULMON_MELADO_T y el vínculo de área oficial, o corrección/aprobación documentada del prefijo que indique si el lazo pertenece a Cocimiento (600) o Evaporación (500).",
            "Estado": "PENDIENTE_EVIDENCIA; SIN_AREA; SIN_NUMERO; NO_INSERTAR", "Escritura_SQLite": "NO",
        },
        {
            "Caso": "CONTROL_PRESION_BIO", "PLC": "FABRICA", "Programa": "SULFO_ENCALADO",
            "Rutina": "PID",
            "Identidades_del_lazo": "Instancia CONTROL_PRESION_BIO de tipo CONTROL_PRESION_CASCADA; PV PRESION_VAPOR_BIO.",
            "Area_asignada": "", "Numero_ISA": "", "Candidatos_de_area_sin_asignar": "250 (solo por identidad BIO; sin definición en el Manual) / 400 (programa SULFO_ENCALADO)",
            "Prefijos_o_identidades_en_conflicto": "BIO en PRESION_VAPOR_BIO frente a SULFO_ENCALADO en el programa y en los módulos físicos.",
            "Manual_por_candidato": "Manual_Estandarizacion.md, línea 91: área 400 = Clarificación y Encalado. La tabla oficial del Manual no contiene área 250 ni una definición Biodestilería; por tanto, 250 no queda respaldado por ese Manual.",
            "Canales_fisicos": "Entrada física SULFO_ENCALADO:1:I.Ch[7].Data -> PRESION_VAPOR_BIO; salida física SULFO_ENCALADO:7:O.Ch[0].Data.",
            "Evidencia_de_trazado": "La instancia ejecutada está en FABRICA.L5X/Program SULFO_ENCALADO/Routine PID. El tag de PV es PRESION_VAPOR_BIO y resuelve a la entrada analógica del módulo SULFO_ENCALADO; el controlador escribe al canal físico de salida del mismo programa. La evidencia PLC sugiere 400 por el contexto SULFO_ENCALADO, mientras BIO sugiere una posible 250 que el Manual no define. Se dejan Area_asignada y Numero_ISA vacíos.",
            "Dato_faltante_para_cerrar": "P&ID/registro de proceso que identifique si PRESION_VAPOR_BIO pertenece a la etapa SULFO/Encalado o a otra unidad, y una fuente normativa oficial para el candidato 250 si ese área existe.",
            "Estado": "PENDIENTE_EVIDENCIA; SIN_AREA; SIN_NUMERO; NO_INSERTAR", "Escritura_SQLite": "NO",
        },
        {
            "Caso": "CONTROL_CAUDAL_JUGO_DEST", "PLC": "FABRICA", "Programa": "FAB_ESCALADOS",
            "Rutina": "AGITADORES_JUGO_DESTIL_PID",
            "Identidades_del_lazo": "Instancia CONTROL_CAUDAL_JUGO_DEST; PV B_FT_JUGO_DEST.Out (REAL interno); salida MV_VALV_NC hacia dos canales FLEX5000_MIELES.",
            "Area_asignada": "", "Numero_ISA": "", "Candidatos_de_area_sin_asignar": "200 (DESTIL/Destilería) / 700 (canal FLEX5000_MIELES, por decisión de usuario)",
            "Prefijos_o_identidades_en_conflicto": "JUGO_DESTIL / DEST frente a FLEX5000_MIELES. La regla de usuario resuelve el canal MIELES a 700, pero no prueba que todo el lazo pertenezca a esa área.",
            "Manual_por_candidato": "Manual_Estandarizacion.md, línea 89: área 200 = Destilería. Línea 94: área 700 = Centrifugado / Purga. El usuario asignó explícitamente Mieles y los canales FLEX5000_MIELES a 700; el nombre de lazo DESTIL mantiene abierta la alternativa 200.",
            "Canales_fisicos": "No se resolvió dirección física de entrada: B_FT_JUGO_DEST.Out carece de escritor trazable en ORef, Ladder o ST. Salidas: FLEX5000_MIELES:2:O.Ch01.Data y FLEX5000_MIELES:2:O.Ch02.Data.",
            "Evidencia_de_trazado": "La invocación está en FABRICA.L5X/Program FAB_ESCALADOS/Routine AGITADORES_JUGO_DESTIL_PID. El PV es un REAL interno sin cadena a transmisor/canal físico; el MV alcanza dos canales de salida crudos de FLEX5000_MIELES. La decisión 23/09 determina el área de esos canales, pero no sustituye la entrada faltante ni demuestra la frontera de proceso del lazo.",
            "Dato_faltante_para_cerrar": "Dirección física/alias y cadena de escritor que alimenta B_FT_JUGO_DEST.Out, más P&ID o registro de equipos que confirme si el lazo completo es Destilería (200) o Mieles/Centrifugado (700).",
            "Estado": "PENDIENTE_EVIDENCIA; SIN_AREA; SIN_NUMERO; NO_INSERTAR", "Escritura_SQLite": "NO",
        },
    ]
    if len(fichas) != 4 or any(f["Area_asignada"] or f["Numero_ISA"] for f in fichas):
        raise AssertionError("Las cuatro fichas deben quedar sin área y sin número")
    if any(f["Escritura_SQLite"] != "NO" for f in fichas):
        raise AssertionError("Las fichas deben indicar Escritura_SQLite=NO")

    return header, rows, fichas, {
        "number": number,
        "tags": occupied["tags"],
        "occupied_summary": occupied_summary,
        "invocations": len(invocation_list),
        "motor_starts": len(motor_starts),
        "limiters": len(limiters),
        "closed_loops": 1,
        "fichas": len(fichas),
        "u4_candidate_hits": occupied["u4_evidence"].get(number, []),
        "u4_global_only_blockers": u4_global_only,
        "raw_token_hits": len(raw_token_hits),
        "raw_token_examples": raw_examples,
    }


def write_csv_exclusive(path: Path, fields: list[str], rows: list[dict], replace_generated: bool = False) -> None:
    if path.exists():
        if not replace_generated:
            raise FileExistsError(f"No se sobrescribe un entregable existente: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            old = list(csv.DictReader(f, delimiter=";"))
        if path == ADDENDUM:
            old_tags = {r.get("Tag_Propuesto", "") for r in old if r.get("Tag_Propuesto")}
            new_tags = {r.get("Tag_Propuesto", "") for r in rows if r.get("Tag_Propuesto")}
            if len(old) != 4 or old_tags != new_tags:
                raise RuntimeError(f"El addendum existente no coincide con esta misma generación: {path}")
        elif path == FICHAS:
            old_cases = {r.get("Caso", "") for r in old}
            new_cases = {r.get("Caso", "") for r in rows}
            if len(old) != 4 or old_cases != new_cases or any(r.get("Area_asignada") or r.get("Numero_ISA") for r in old):
                raise RuntimeError(f"Las fichas existentes no corresponden a esta generación segura: {path}")
        else:
            raise RuntimeError(f"Ruta de reemplazo no autorizada: {path}")
        mode = "w"
    else:
        mode = "x"
    with path.open(mode, encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";", extrasaction="raise", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="crear exclusivamente los dos CSV solicitados")
    parser.add_argument("--replace-generated", action="store_true", help="reemplazar solo los dos CSV que esta herramienta ya generó")
    args = parser.parse_args()
    if args.replace_generated and not args.write:
        parser.error("--replace-generated requiere --write")
    before = {str(p): db_state(p) for p in (propuesta.DB_PRODUCCION, propuesta.BACKUP_693)}
    header, rows, fichas, summary = build_rows()
    if not args.write:
        print(json.dumps({"mode": "dry-run", **summary}, ensure_ascii=False, sort_keys=True))
        return 0
    write_csv_exclusive(ADDENDUM, header, rows, replace_generated=args.replace_generated)
    write_csv_exclusive(FICHAS, CAMPOS_FICHA, fichas, replace_generated=args.replace_generated)
    # Read-back every requested output and enforce row/status/no-number invariants.
    with ADDENDUM.open("r", encoding="utf-8-sig", newline="") as f:
        out_rows = list(csv.DictReader(f, delimiter=";"))
    with FICHAS.open("r", encoding="utf-8-sig", newline="") as f:
        ficha_rows = list(csv.DictReader(f, delimiter=";"))
    if len(out_rows) != 4 or len([r for r in out_rows if r["Tag_Propuesto"]]) != 3:
        raise AssertionError("El addendum debe incluir 3 tags del único lazo cerrable y 1 fila bloqueada")
    if any(r["Escritura_SQLite"] != "NO" for r in out_rows):
        raise AssertionError("Alguna fila del addendum permite escritura SQLite")
    if any("NO_INSERTAR" not in r["Estado_Propuesta"] for r in out_rows):
        raise AssertionError("Alguna fila del addendum no está marcada NO_INSERTAR")
    if any(r["Estado_Propuesta"] != "NO_INSERTAR" for r in out_rows):
        raise AssertionError("Estado_Propuesta debe ser exactamente NO_INSERTAR")
    if any(r["Requiere_Autorizacion"] != "SI" for r in out_rows):
        raise AssertionError("Todas las filas requieren autorización explícita")
    if len(ficha_rows) != 4 or any(r["Area_asignada"] or r["Numero_ISA"] for r in ficha_rows):
        raise AssertionError("Read-back de fichas: se esperaba 4 sin área ni número")
    after = {str(p): db_state(p) for p in (propuesta.DB_PRODUCCION, propuesta.BACKUP_693)}
    if before != after or any(v["integrity"] != "ok" for v in after.values()):
        raise AssertionError(f"Cambió una base o falló integrity_check: before={before}; after={after}")
    print(json.dumps({"mode": "written", "addendum": str(ADDENDUM), "fichas_path": str(FICHAS),
                      "database_state_unchanged": True, "database_state": after, **summary},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
