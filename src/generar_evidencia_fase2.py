"""Genera evidencia auditable de los grupos Fase 2 habilitados.

Solo lee XML y produce CSV. No abre SQLite y no asigna números ISA.
"""
from __future__ import annotations

import argparse
import csv
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

try:
    from . import reconciliador_topologico_v3 as v3
    from . import auditar_l5x as auditor
except ImportError:
    import reconciliador_topologico_v3 as v3
    import auditar_l5x as auditor

EVIDENCIA_CAMPOS = [
    'PLC', 'Program', 'Routine', 'Scope', 'Loop_ID', 'Instancia_Controlador',
    'Tipo_Bloque_AOI', 'Pin_Entrada_PID', 'Camino_XML_Entrada_PID',
    'Pin_Salida_PID', 'Camino_XML_Salida_Elemento_Final',
    'Entrada_Tag', 'Entrada_AliasFor', 'Entrada_Tag_Fisico',
    'Salida_Tag', 'Salida_AliasFor', 'Salida_Tag_Fisico',
    'Area_Inferida', 'Evidencia_Area', 'Variable_ISA_Inferida',
    'Evidencia_Variable', 'No_procede_Definicion_AOI',
    'Instancia_Unica_Scope', 'Otras_Instancias_Misma_Entrada',
    'Otras_Instancias_Misma_Salida', 'Confianza_Final', 'Observaciones',
]
PID_CAMPOS = [
    'Categoria', 'PID_Unico', 'PLC', 'Scope', 'Instancia', 'Program',
    'Routine', 'Tipo_Bloque_AOI', 'Ocurrencia_ID', 'Camino_XML',
    'Definicion_AOI', 'Ocurrencias_Misma_Instancia', 'Rutinas_Distintas',
    'Observaciones',
]


def _tag_path(tag, scope):
    return f"{scope}/Tag[@Name='{tag.get('Name', '')}']"


def _node_path(program, routine, sheet, node):
    tipo = node.tag
    return (f"Controller/Program[@Name='{program}']/Routine[@Name='{routine}']"
            f"/FBDContent/Sheet[@Number='{sheet.get('Number', '')}']"
            f"/{tipo}[@ID='{node.get('ID', '')}'"
            f" and @Operand='{node.get('Operand', '')}']")


def _wire_text(wire):
    attrs = ' '.join(f"{k}='{wire.get(k, '')}'" for k in ('FromID', 'FromParam', 'ToID', 'ToParam'))
    return f'Wire[{attrs}]'


def _find_fbd_occurrences(root, plc, program_name, instance):
    results = []
    controller = root.find('Controller')
    program = next((p for p in controller.findall('Programs/Program')
                    if p.get('Name') == program_name), None)
    if program is None:
        return results
    for routine in program.findall('Routines/Routine'):
        for sheet in routine.findall('FBDContent/Sheet'):
            nodes = {n.get('ID'): n for n in sheet
                     if n.tag in ('IRef', 'ORef', 'Block', 'AddOnInstruction')}
            for node in nodes.values():
                if node.get('Operand') == instance:
                    results.append({
                        'program': program_name, 'routine': routine.get('Name', ''),
                        'sheet': sheet, 'nodes': nodes, 'node': node,
                        'type': node.get('Name', node.get('Type', '')),
                        'language': 'FBD',
                    })
    # RLL calls are retained for the PID audit, but they do not have pin XML.
    for routine in program.findall('Routines/Routine'):
        for rung in routine.findall('RLLContent/Rung'):
            text = ''.join(rung.itertext())
            if re.search(rf'(?<![A-Za-z0-9_]){re.escape(instance)}(?:\.|\()', text):
                results.append({
                    'program': program_name, 'routine': routine.get('Name', ''),
                    'rung': rung, 'node': None, 'type': 'RLL_CALL',
                    'language': 'RLL',
                })
    return results


def _trace_in(sheet, nodes, target_id, pin, seen=None, program='', routine=''):
    seen = set() if seen is None else seen
    marker = (target_id, pin or '')
    if marker in seen:
        return ['[CICLO]']
    seen.add(marker)
    wires = [w for w in sheet.findall('Wire')
             if w.get('ToID') == target_id and (not pin or w.get('ToParam') == pin)]
    paths = []
    for wire in wires:
        previous = nodes.get(wire.get('FromID'))
        wire_text = _wire_text(wire)
        if previous is None:
            paths.append(wire_text)
            continue
        if previous.tag == 'IRef':
            paths.append(f'{wire_text} <- {_node_path(program, routine, sheet, previous)}')
        else:
            upstream = _trace_in(sheet, nodes, previous.get('ID'), None, seen.copy(), program, routine)
            paths.extend(f'{wire_text} <- {_node_path(program, routine, sheet, previous)} <- {p}' for p in upstream)
    return paths or ['[SIN_WIRE_ENTRANTE]']


def _trace_out(sheet, nodes, source_id, pin, seen=None, program='', routine=''):
    seen = set() if seen is None else seen
    marker = (source_id, pin or '')
    if marker in seen:
        return ['[CICLO]']
    seen.add(marker)
    wires = [w for w in sheet.findall('Wire')
             if w.get('FromID') == source_id and (not pin or w.get('FromParam') == pin)]
    paths = []
    for wire in wires:
        following = nodes.get(wire.get('ToID'))
        wire_text = _wire_text(wire)
        if following is None:
            paths.append(wire_text)
            continue
        if following.tag == 'ORef':
            paths.append(f'{wire_text} -> {_node_path(program, routine, sheet, following)}')
        else:
            downstream = _trace_out(sheet, nodes, following.get('ID'), None, seen.copy(), program, routine)
            paths.extend(f'{wire_text} -> {_node_path(program, routine, sheet, following)} -> {p}' for p in downstream)
    return paths or ['[SIN_WIRE_SALIENTE]']


def _declaraciones(root, program_name):
    controller = root.find('Controller')
    result = {}
    for tag in controller.findall('Tags/Tag'):
        result[('Controller', tag.get('Name', '').casefold())] = tag
    for program in controller.findall('Programs/Program'):
        if program.get('Name') == program_name:
            for tag in program.findall('Tags/Tag'):
                result[(f'Program:{program_name}', tag.get('Name', '').casefold())] = tag
    return result


def _endpoint(declarations, operand):
    split = v3.split_operand(operand)
    if split is None:
        return '', '', ''
    base, member = split
    tag = declarations.get(('Controller', base.casefold()))
    if tag is None:
        tag = next((t for (scope, name), t in declarations.items() if name == base.casefold()), None)
    alias = tag.get('AliasFor', '') if tag is not None else ''
    return operand, alias, alias or operand


def _area(plc, endpoint):
    mapping = auditor.mapeo_area_para_plc(plc)
    for token in re.split(r'[_\-.]', endpoint.upper()):
        if token in mapping:
            return mapping[token], f"MAPEO_AREA para token {token} en {plc}"
    default = auditor.area_defecto_para(plc)
    if default:
        return default, f'AREA_DEFECTO_POR_PLC[{plc}]'
    return '', 'Sin evidencia de área suficiente'


def _variable(endpoint):
    variable, funcion = v3.classify_input(endpoint)
    return variable, f"Token ISA exacto en {endpoint}: {variable}{funcion}" if variable else 'Sin token ISA inequívoco'


def _controller_occurrence(root, program, instance):
    occurrences = _find_fbd_occurrences(root, root.find('Controller').get('Name', ''), program, instance)
    fbd = [x for x in occurrences if x['language'] == 'FBD' and x['node'] is not None]
    if not fbd:
        return occurrences[0] if occurrences else None, occurrences
    # Prefer the invocation with both PV and MV wires; other invocations are repetitions.
    chosen = max(fbd, key=lambda x: (
        any(w.get('ToID') == x['node'].get('ID') and w.get('ToParam') == 'PV' for w in x['sheet'].findall('Wire')),
        any(w.get('FromID') == x['node'].get('ID') and w.get('FromParam') in ('MV', 'CV', 'CVEU') for w in x['sheet'].findall('Wire')),
    ))
    return chosen, occurrences


def _pid_rows(topologies):
    rows = []
    executed_keys = set()
    repeated = []
    used_definitions = defaultdict(set)
    for top in topologies:
        controller = ET.parse(top.path).getroot().find('Controller')
        for identity in v3._controladores(top):
            key = (top.plc, identity.scope, identity.base)
            executed_keys.add(key)
            occurrences = _find_fbd_occurrences(controller.getparent() if False else ET.parse(top.path).getroot(), top.plc, identity.scope.split(':', 1)[1] if identity.scope.startswith('Program:') else '', identity.base)
            for occurrence in occurrences:
                used_definitions[(top.plc, identity.data_type)].add(identity.base)
            detail = []
            for n, occurrence in enumerate(occurrences, 1):
                if occurrence.get('language') == 'FBD':
                    sheet = occurrence['sheet']
                    path = _node_path(occurrence['program'], occurrence['routine'], sheet, occurrence['node'])
                    routine = occurrence['routine']
                else:
                    rung = occurrence['rung']
                    path = f"Controller/Program[@Name='{identity.scope.split(':',1)[1]}']/Routine[@Name='{occurrence['routine']}']/RLLContent/Rung[@Number='{rung.get('Number','')}']/Text"
                    routine = occurrence['routine']
                detail.append((routine, path))
            rows.append({
                'Categoria': 'EJECUTADA_CONTROLLER_PROGRAM',
                'PID_Unico': '|'.join((top.plc, identity.scope, identity.base)),
                'PLC': top.plc, 'Scope': identity.scope, 'Instancia': identity.base,
                'Program': identity.scope.split(':', 1)[1] if identity.scope.startswith('Program:') else '',
                'Routine': '|'.join(sorted({x[0] for x in detail})),
                'Tipo_Bloque_AOI': identity.data_type or 'PID/PIDE',
                'Ocurrencia_ID': '|'.join(x[1] for x in detail),
                'Camino_XML': '|'.join(x[1] for x in detail),
                'Definicion_AOI': 'NO_APLICA',
                'Ocurrencias_Misma_Instancia': str(len(detail)),
                'Rutinas_Distintas': str(len({x[0] for x in detail})),
                'Observaciones': 'Instancia ejecutada deduplicada por PLC+scope+instancia',
            })
            if len({x[0] for x in detail}) > 1 or len(detail) > 1:
                repeated.append(rows[-1].copy())
    # Category 2: definitions containing native PID/PIDE with no executed instance of that AOI type.
    for top in topologies:
        root = ET.parse(top.path).getroot()
        controller = root.find('Controller')
        declared_types = {i.data_type for i in top.declarations.values()}
        for definition in controller.findall('AddOnInstructionDefinitions/AddOnInstructionDefinition'):
            body = ET.tostring(definition, encoding='unicode')
            if not re.search(r'Type="(?:PID|PIDE)"', body, re.I):
                continue
            name = definition.get('Name', '')
            if name in declared_types:
                continue
            path = f"Controller/AddOnInstructionDefinitions/AddOnInstructionDefinition[@Name='{name}']"
            rows.append({
                'Categoria': 'SOLO_DEFINICION_AOI',
                'PID_Unico': f'{top.plc}|DEFINITION|{name}', 'PLC': top.plc,
                'Scope': 'AddOnInstructionDefinitions', 'Instancia': name,
                'Program': '', 'Routine': '', 'Tipo_Bloque_AOI': name,
                'Ocurrencia_ID': '', 'Camino_XML': path, 'Definicion_AOI': path,
                'Ocurrencias_Misma_Instancia': '0', 'Rutinas_Distintas': '0',
                'Observaciones': 'Plantilla AOI; no es ejecución de planta',
            })
    for row in repeated:
        row['Categoria'] = 'REPETICION_MISMA_INSTANCIA'
        row['Observaciones'] = 'La misma instancia aparece en más de una ocurrencia/rutina'
        rows.append(row)
    return rows, len(executed_keys)


def generar_evidencia(l5x_dir, evidencia_csv, pid_csv):
    topologias = [v3.Topologia(p) for p in sorted(Path(l5x_dir).glob('*.L5X'))]
    asociaciones = []
    for top in topologias:
        asociaciones.extend(v3.build_associations(top))
    habilitados = [a for a in asociaciones if a.inputs and a.controller and a.outputs
                   and len(a.inputs) == 1 and len(a.outputs) == 1 and not a.problems]
    if len(habilitados) != 3:
        raise ValueError(f'Se esperaban 3 grupos habilitados y se encontraron {len(habilitados)}')
    evidence_rows = []
    endpoint_users = defaultdict(set)
    for a in asociaciones:
        for endpoint in (*a.inputs, *a.outputs):
            endpoint_users[(a.plc, endpoint.key)].add(a.controller.key)
    for a in habilitados:
        top = next(t for t in topologias if t.plc.casefold() == a.plc.casefold())
        root = ET.parse(top.path).getroot()
        program = a.controller.scope.split(':', 1)[1]
        chosen, occurrences = _controller_occurrence(root, program, a.controller.base)
        if chosen is None or chosen.get('language') != 'FBD':
            raise ValueError(f'No se encontró ocurrencia FBD del controlador {a.controller.base}')
        node = chosen['node']; sheet = chosen['sheet']; nodes = chosen['nodes']
        definition = node.get('Name', node.get('Type', ''))
        pin_in = 'PV' if definition in top.aoi_definitions and 'PV' in top.aoi_definitions[definition] else 'PV'
        pin_out = 'MV' if definition in top.aoi_definitions and 'MV' in top.aoi_definitions[definition] else 'CV'
        in_paths = _trace_in(sheet, nodes, node.get('ID'), pin_in, program=chosen['program'], routine=chosen['routine'])
        out_paths = _trace_out(sheet, nodes, node.get('ID'), pin_out, program=chosen['program'], routine=chosen['routine'])
        in_tag, in_alias, in_phys = _endpoint(_declaraciones(root, program), a.inputs[0].base)
        out_tag, out_alias, out_phys = _endpoint(_declaraciones(root, program), a.outputs[0].base)
        area, area_evidence = _area(top.plc, a.inputs[0].base)
        variable, variable_evidence = _variable(a.inputs[0].base)
        base_path = (f"Controller[@Name='{top.controller}']/Programs/Program[@Name='{program}']"
                     f"/Routines/Routine[@Name='{chosen['routine']}']"
                     f"/FBDContent/Sheet[@Number='{sheet.get('Number','')}']")
        pid_path = f"{base_path}/AddOnInstruction[@ID='{node.get('ID')}'][@Operand='{a.controller.base}']"
        other_in = endpoint_users[(a.plc, a.inputs[0].key)] - {a.controller.key}
        other_out = endpoint_users[(a.plc, a.outputs[0].key)] - {a.controller.key}
        rows_obs = []
        if len(occurrences) > 1:
            rows_obs.append(f'Instancia repetida en {len(occurrences)} ocurrencias; se deduplica por PLC+scope+instancia')
        evidence_rows.append({
            'PLC': top.plc, 'Program': program, 'Routine': chosen['routine'], 'Scope': a.controller.scope,
            'Loop_ID': a.loop_id, 'Instancia_Controlador': a.controller.base,
            'Tipo_Bloque_AOI': f"AddOnInstruction Name={definition}; DataType={a.controller.data_type}",
            'Pin_Entrada_PID': pin_in, 'Camino_XML_Entrada_PID': f'{pid_path} <- ' + ' <- '.join(in_paths),
            'Pin_Salida_PID': pin_out, 'Camino_XML_Salida_Elemento_Final': f'{pid_path} -> ' + ' -> '.join(out_paths),
            'Entrada_Tag': in_tag, 'Entrada_AliasFor': in_alias, 'Entrada_Tag_Fisico': in_phys,
            'Salida_Tag': out_tag, 'Salida_AliasFor': out_alias, 'Salida_Tag_Fisico': out_phys,
            'Area_Inferida': area, 'Evidencia_Area': area_evidence,
            'Variable_ISA_Inferida': variable, 'Evidencia_Variable': variable_evidence,
            'No_procede_Definicion_AOI': 'SI', 'Instancia_Unica_Scope': 'SI',
            'Otras_Instancias_Misma_Entrada': 'NO' if not other_in else '|'.join(map(str, sorted(other_in))),
            'Otras_Instancias_Misma_Salida': 'NO' if not other_out else '|'.join(map(str, sorted(other_out))),
            'Confianza_Final': a.confianza_final,
            'Observaciones': '; '.join(rows_obs) or 'Sin repetición de instancia en otra ocurrencia',
        })
    pid_rows, pid_unique = _pid_rows(topologias)
    evidencia_csv = Path(evidencia_csv); pid_csv = Path(pid_csv)
    evidencia_csv.parent.mkdir(parents=True, exist_ok=True); pid_csv.parent.mkdir(parents=True, exist_ok=True)
    with evidencia_csv.open('w', encoding='utf-8-sig', newline='') as f:
        writer=csv.DictWriter(f,fieldnames=EVIDENCIA_CAMPOS,delimiter=';'); writer.writeheader(); writer.writerows(evidence_rows)
    with pid_csv.open('w', encoding='utf-8-sig', newline='') as f:
        writer=csv.DictWriter(f,fieldnames=PID_CAMPOS,delimiter=';'); writer.writeheader(); writer.writerows(pid_rows)
    return {'grupos_habilitados':len(evidence_rows),'pid_unicos_scope':pid_unique,'pid_filas':len(pid_rows),
            'evidencia_csv':str(evidencia_csv),'pid_csv':str(pid_csv)}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Evidencia Fase 2 — solo lectura')
    parser.add_argument('--l5x-dir',default='L5X_Produccion',type=Path)
    parser.add_argument('--evidencia',default='exports/evidencia_3_lazos_habilitados.csv',type=Path)
    parser.add_argument('--pids',default='exports/auditoria_209_pid.csv',type=Path)
    args=parser.parse_args(argv)
    import json
    print(json.dumps(generar_evidencia(args.l5x_dir,args.evidencia,args.pids),ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
