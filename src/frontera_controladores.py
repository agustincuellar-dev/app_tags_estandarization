"""Frontera XML estática. Sin SQLite, renumeración ISA ni prueba runtime.

El universo legado es de declaraciones; las invocaciones se prueban aparte.
Se detiene en semántica no implementada: nunca atraviesa un AOI por todos
sus pines ni atribuye una condición Ladder a una transferencia de proceso.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

try:
    from . import reconciliador_topologico_v3 as v3
except ImportError:
    import reconciliador_topologico_v3 as v3

NATIVE = {'PID', 'PIDE', 'PID01', 'PIDE01'}
TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_:]*(?:\[[^\]\r\n]+\]|\.[A-Za-z0-9_]+)*')


def clean(text):
    # Preserve newlines so ST line locations still address the XML.
    return re.sub(r"\(\*.*?\*\)|/\*.*?\*/|//[^\n]*|'(?:\$\x27|[^\x27])*'|\"[^\"]*\"",
                  lambda m: '\n' * m.group().count('\n') or ' ', text, flags=re.S)


def calls(text):
    """Neutral-text calls preserving zero, ?, and positional arguments."""
    for m in re.finditer(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(', clean(text)):
        source = clean(text); depth = 1; end = m.end()
        while end < len(source) and depth:
            depth += (source[end] == '(') - (source[end] == ')'); end += 1
        if depth:
            continue
        args = []; start = m.end(); nested = 0
        for pos in range(start, end - 1):
            char = source[pos]
            if char in '([': nested += 1
            elif char in ')]': nested -= 1
            elif char == ',' and not nested:
                args.append(source[start:pos].strip()); start = pos + 1
        args.append(source[start:end - 1].strip())
        yield m.group(1), args, source[m.start():end]


class XMLAudit:
    def __init__(self, path):
        self.top = v3.Topologia(path)
        self.root = ET.parse(path).getroot()
        self.controller = self.root.find('Controller')
        self.controllers = {(i.scope.casefold(), i.base.casefold()): i
                            for i in v3._controladores(self.top)}
        self.occurrences = defaultdict(list)
        self.references = defaultdict(list)
        self.definitions = []
        self.text_units = []
        self.locations = {}
        self._paths(self.root, '')
        for definition in self.controller.findall('AddOnInstructionDefinitions/AddOnInstructionDefinition'):
            native = [n for n in definition.findall('.//Block') if n.get('Type', '').upper() in NATIVE]
            native += [n for n in definition.findall('.//AddOnInstruction') if n.get('Name', '').upper() in NATIVE]
            for node in definition.findall('.//Rung/Text') + definition.findall('.//STContent/Line'):
                if any(name.upper() in NATIVE for name, _, _ in calls(node.text or '')):
                    native.append(node)
            if native:
                self.definitions.append({'name': definition.get('Name'), 'path': self.locations[id(definition)],
                                         'native_paths': [self.locations[id(n)] for n in native]})
        for program in self.controller.findall('Programs/Program'):
            pname = program.get('Name', '')
            for routine in program.findall('Routines/Routine'):
                common = {'program': pname, 'routine': routine.get('Name', ''), 'language': routine.get('Type', '')}
                for sheet in routine.findall('FBDContent/Sheet'):
                    nodes = {n.get('ID'): n for n in sheet if n.get('ID') is not None}
                    for node in nodes.values():
                        operand = node.get('Operand', '')
                        record = dict(common, node=node, path=self.locations[id(node)], operand=operand,
                                      sheet=sheet, nodes=nodes, instruction=node.get('Name', node.get('Type', node.tag)))
                        self._reference(operand, pname, record)
                        if node.tag in ('Block', 'AddOnInstruction'):
                            self._invocation(operand, record['instruction'], record)
                text_nodes = routine.findall('RLLContent/Rung/Text') + routine.findall('STContent/Line')
                cleaned_lines = clean('\n'.join(n.text or '' for n in text_nodes)).splitlines()
                # RLL text often has embedded newlines; clean whole routine for multiline comments.
                joined = clean('\n\0\n'.join(n.text or '' for n in text_nodes)).split('\n\0\n')
                for node, text in zip(text_nodes, joined):
                    record = dict(common, node=node, path=self.locations[id(node)], text=text,
                                  operand='', instruction=routine.get('Type', ''))
                    self.text_units.append(record)
                    for token in sorted(set(TOKEN.findall(text))):
                        self._reference(token, pname, record)
                    for name, args, literal in calls(text):
                        rec = dict(record, instruction=name, args=args, literal=literal)
                        if args:
                            self._invocation(args[0], name, rec)

    def _paths(self, node, parent):
        counts = Counter()
        for child in node:
            counts[child.tag] += 1
            attr = next((a for a in ('Name', 'Number', 'ID') if a in child.attrib), None)
            part = child.tag + (f"[@{attr}='{child.get(attr)}']" if attr else f'[{counts[child.tag]}]')
            path = parent + '/' + part if parent else part
            self.locations[id(child)] = path
            self._paths(child, path)

    def resolve(self, operand, program):
        identity = self.top.resolve_operand(operand, program)
        return identity

    def _reference(self, operand, program, record):
        identity = self.resolve(operand, program)
        if identity:
            self.references[identity.key].append(dict(record, referenced=operand))

    def _invocation(self, operand, name, record):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', operand):
            return
        identity = self.resolve(operand, record['program'])
        if not identity:
            return
        key = (identity.scope.casefold(), identity.base.casefold())
        declared = self.controllers.get(key)
        if declared and (name.casefold() == declared.data_type.casefold() or
                         name.upper() in NATIVE and declared.data_type.upper() in NATIVE):
            self.occurrences[key].append(dict(record, operand=operand))


def inspect_xml(path):
    return XMLAudit(path)


COLUMNS = ['PLC', 'Program', 'Scope', 'Routine', 'Instancia', 'Tipo',
           'Invocacion_XML_Demostrada', 'Clasificacion_Previa',
           'Tiene_Entrada', 'Tiene_Salida', 'Entrada_Encontrada', 'Salida_Encontrada',
           'Punto_Exacto_Donde_Se_Corta_Entrada', 'Punto_Exacto_Donde_Se_Corta_Salida',
           'Lenguaje', 'Rutina', 'Instruccion_o_Bloque', 'Operando_Actual',
           'Siguiente_Operando', 'Motivo_Bloqueo', 'Submotivo_Bloqueo',
           'Detalle_Bloqueo', 'Analizador_Faltante', 'Prioridad', 'Confianza']
REASONS = frozenset('PIN_SIN_CONEXION TAG_INTERMEDIO_SIN_ESCRITOR TAG_INTERMEDIO_SIN_LECTOR AOI_ENVOLTORIO PARAMETRO_DE_RUTINA JSR_SBR_RET INSTRUCCION_LADDER_NO_SOPORTADA EXPRESION_ST_NO_SOPORTADA MIEMBRO_UDT_NO_RESUELTO ARRAY_O_INDICE_INDIRECTO ALIAS_NO_RESUELTO I_O_REMOTA_NO_RESUELTA MULTIPLES_ESCRITORES EXTREMO_COMPARTIDO OTRO_CON_EVIDENCIA'.split())
IMPROVEMENTS = {
    'PIN_SIN_CONEXION': 'Resolver referencias externas al miembro del pin; revisar conexión/configuración XML, no crear wires',
    'TAG_INTERMEDIO_SIN_ESCRITOR': 'Índice de escritores interrutina y transferencias de datos no soportadas',
    'TAG_INTERMEDIO_SIN_LECTOR': 'Índice de lectores interrutina y transferencias de datos no soportadas',
    'AOI_ENVOLTORIO': 'Expandir cuerpo AOI por parámetro Usage y mapear instancia/pin sin mezclar pines',
    'PARAMETRO_DE_RUTINA': 'Binding explícito de parámetros de rutina por llamada',
    'JSR_SBR_RET': 'Mapear JSR/SBR/RET con posición y contexto de cada llamada',
    'INSTRUCCION_LADDER_NO_SOPORTADA': 'Añadir firma direccional de la instrucción Ladder citada',
    'EXPRESION_ST_NO_SOPORTADA': 'AST ST con semántica direccional de la sentencia citada',
    'MIEMBRO_UDT_NO_RESUELTO': 'Resolver miembro UDT y escrituras al agregado sin perder offsets',
    'ARRAY_O_INDICE_INDIRECTO': 'Resolver índices y rangos con evidencia estática; no adivinar índice runtime',
    'ALIAS_NO_RESUELTO': 'Resolver cadena AliasFor con scope exacto y detección de ciclos',
    'I_O_REMOTA_NO_RESUELTA': 'Mapear módulos y comunicaciones a dirección física documentada',
    'MULTIPLES_ESCRITORES': 'Análisis de exclusión de escritores/selección, no elegir el primero',
    'EXTREMO_COMPARTIDO': 'Revisión de exclusividad física y selección/cascada entre controladores',
    'OTRO_CON_EVIDENCIA': 'Revisar evidencia concreta individual; no existe una mejora universal para este grupo',
}


def issue(reason, record, current, following='', detail=''):
    return {'reason': reason, 'path': record['path'], 'current': current, 'next': following,
            'detail': detail, 'language': record.get('language', 'XML'),
            'routine': record.get('routine', ''), 'instruction': record.get('instruction', '')}


def _submotivo(problem):
    if problem['reason'] != 'OTRO_CON_EVIDENCIA':
        return problem['reason']
    detail = problem.get('detail', '')
    for prefix, code in (
        ('Declaración ', 'DECLARACION_SIN_INVOCACION_XML'),
        ('Camino XML alcanza ', 'CAMINO_COMPLETO_NO_APROBADO'),
        ('FBD ', 'BLOQUE_FBD_SIN_MAPEO_DIRECCIONAL'),
        ('Operando literal ', 'CONSTANTE_O_LITERAL'),
        ('Ciclo ', 'CICLO_DIRECCIONAL'),
        ('Dirección física ', 'DIRECCION_FISICA_OPUESTA'),
        ('Wire referencia ID ausente', 'WIRE_ID_AUSENTE'),
    ):
        if detail.startswith(prefix):
            return code
    return 'EVIDENCIA_INDIVIDUAL_NO_CLASIFICADA'


class Tracer:
    """Conservative pin-aware tracing. A result is evidence, never a plant loop approval."""
    def __init__(self, audit):
        self.audit = audit

    def pin(self, rec, pin, direction, seen=frozenset()):
        node = rec['node']; nid = node.get('ID'); sheet = rec['sheet']
        incoming = direction == 'in'
        side, param, other = ('ToID', 'ToParam', 'FromID') if incoming else ('FromID', 'FromParam', 'ToID')
        wires = [w for w in sheet.findall('Wire') if w.get(side) == nid and w.get(param, '') == pin]
        if not wires:
            member = rec.get('operand', node.get('Operand', '')) + '.' + pin
            identity = self.audit.resolve(member, rec['program'])
            references = self.audit.references.get(identity.key, []) if identity else []
            if references:
                return self.operand(member, rec, direction, seen)
            return [], [issue('PIN_SIN_CONEXION', rec, member, detail=f'No hay Wire {side}={nid} {param}={pin} en esta Sheet ni referencia externa exacta al miembro en Programs. No prueba desconexión runtime.')]
        endpoints, problems = [], []
        if incoming and len(wires) > 1:
            problems.append(issue('MULTIPLES_ESCRITORES', rec, rec['operand'] + '.' + pin,
                                  detail=' | '.join(self.audit.locations[id(w)] + ' ' + ET.tostring(w, encoding='unicode').strip() for w in wires)))
        for wire in wires:
            target = rec['nodes'].get(wire.get(other))
            if target is None:
                problems.append(issue('OTRO_CON_EVIDENCIA', rec, rec['operand'], detail=f'Wire referencia ID ausente: {ET.tostring(wire, encoding="unicode").strip()}'))
                continue
            target_rec = dict(rec, node=target, operand=target.get('Operand', ''),
                              path=self.audit.locations[id(target)],
                              instruction=target.get('Name', target.get('Type', target.tag)))
            marker = (target_rec['path'], direction)
            if marker in seen:
                problems.append(issue('OTRO_CON_EVIDENCIA', target_rec, target_rec['operand'], detail='Ciclo XML en el camino direccional; no se continúa por segunda vez.'))
                continue
            newseen = seen | {marker}
            if target.tag == ('IRef' if incoming else 'ORef'):
                found, blocked = self.operand(target_rec['operand'], target_rec, direction, newseen)
            elif target.tag == 'AddOnInstruction':
                attached = wire.get('FromParam' if incoming else 'ToParam', '')
                found, blocked = [], [issue('AOI_ENVOLTORIO', target_rec, target_rec['operand'] + ('.' + attached if attached else ''),
                                            detail=f'Wire literal {ET.tostring(wire, encoding="unicode").strip()}; el cuerpo de {target.get("Name")} debe mapear este pin, no todos sus parámetros.')]
            elif target.tag == 'Block' and target.get('Type', '').upper() in ('SCL', 'MOV', 'MOVE'):
                transfer = ('In', 'Out') if target.get('Type', '').upper() == 'SCL' else ('Source', 'Dest')
                found, blocked = self.pin(target_rec, transfer[0 if incoming else 1], direction, newseen)
            else:
                found, blocked = [], [issue('OTRO_CON_EVIDENCIA', target_rec, target_rec['operand'] or target.get('ID', ''),
                    detail=f'FBD {target.tag} {target_rec["instruction"]}: no hay mapeo direccional implementado para Wire {ET.tostring(wire, encoding="unicode").strip()}')]
            endpoints.extend(found); problems.extend(blocked)
        return endpoints, problems

    def operand(self, operand, rec, direction, seen=frozenset()):
        identity = self.audit.resolve(operand, rec['program'])
        if identity is None:
            return [], [issue('OTRO_CON_EVIDENCIA', rec, operand or '(vacío XML)', detail=f'Operando literal {operand!r}, no es referencia a tag; no se infiere sensor/actuador de una constante.')]
        marker = (identity.key, direction)
        if marker in seen:
            return [], [issue('ALIAS_NO_RESUELTO' if identity.alias_for else 'OTRO_CON_EVIDENCIA', rec, operand, detail=f'Ciclo al volver a {identity.scope}/{operand}; no se elige una rama arbitraria.')]
        seen = seen | {marker}
        physical = identity.alias_for or operand
        role = v3._alias_kind(physical)
        if role == ('ENTRADA' if direction == 'in' else 'SALIDA'):
            return [f'{identity.scope}/{operand} -> {physical}'], []
        if role:
            return [], [issue('OTRO_CON_EVIDENCIA', rec, operand, physical, f'Dirección física {role} opuesta al trazado {direction}.')]
        if identity.alias_for:
            return self.operand(identity.alias_for + identity.member, rec, direction, seen)
        if re.search(r'\[[^\]]*[^0-9\]][^\]]*\]', operand):
            return [], [issue('ARRAY_O_INDICE_INDIRECTO', rec, operand, detail='Índice no literal decimal en el operando XML citado.')]
        refs = [r for r in self.audit.references.get(identity.key, []) if r['path'] != rec['path']]
        candidates = []
        uncertain = []
        for ref in refs:
            if ref.get('sheet') is not None:
                node = ref['node']
                if node.tag == ('ORef' if direction == 'in' else 'IRef'):
                    candidates.append(('fbd', ref, ''))
                continue
            for name, args, literal in calls(ref.get('text', '')):
                exact = [i for i, a in enumerate(args) if self.audit.resolve(a, ref['program']) and self.audit.resolve(a, ref['program']).key == identity.key]
                if not exact:
                    continue
                if name.upper() in ('MOV', 'MOVE') and len(args) == 2:
                    if (direction == 'in' and 1 in exact) or (direction == 'out' and 0 in exact):
                        candidates.append(('operand', dict(ref, instruction=name), args[0 if direction == 'in' else 1]))
                elif name.upper() in ('XIC', 'XIO', 'OTE', 'OTL', 'OTU'):
                    uncertain.append(issue('INSTRUCCION_LADDER_NO_SOPORTADA', dict(ref, instruction=name), operand, detail=f'{literal}; referencia booleana, no transferencia analógica probada.'))
                else:
                    reason = 'JSR_SBR_RET' if name.upper() in ('JSR', 'SBR', 'RET') else ('AOI_ENVOLTORIO' if name in self.audit.top.aoi_definitions else 'INSTRUCCION_LADDER_NO_SOPORTADA')
                    uncertain.append(issue(reason, dict(ref, instruction=name), operand,
                                           detail=f'{literal}; posición(es) exactas {exact}, dirección de este argumento no implementada.'))
            if ref['language'] == 'ST':
                uncertain.append(issue('EXPRESION_ST_NO_SOPORTADA', ref, operand, detail=ref['text'].strip()))
        if direction == 'in' and len(candidates) > 1:
            return [], [issue('MULTIPLES_ESCRITORES', rec, operand,
                              detail='Escritores candidatos: ' + ' | '.join(r['path'] for _, r, _ in candidates))] + uncertain
        endpoints, problems = [], list(uncertain)
        for kind, reference, following in sorted(candidates, key=lambda x: (x[1]['path'], x[2])):
            if kind == 'fbd':
                found, blocked = self.pin(reference, '', direction, seen)
            else:
                found, blocked = self.operand(following, reference, direction, seen)
            endpoints.extend(found); problems.extend(blocked)
        if not endpoints and not problems:
            reason = ('MIEMBRO_UDT_NO_RESUELTO' if identity.member else
                      'TAG_INTERMEDIO_SIN_ESCRITOR' if direction == 'in' else 'TAG_INTERMEDIO_SIN_LECTOR')
            if not identity.declaration_found:
                reason = 'I_O_REMOTA_NO_RESUELTA' if ':' in operand else 'ALIAS_NO_RESUELTO'
            problems.append(issue(reason, rec, operand, detail=f'Identidad {identity.scope}/{identity.qualified}; {len(refs)} referencias externas exactas en Programs, ninguna transferencia direccional resuelta. Escritura al agregado/servicios externos no descartados.'))
        return sorted(set(endpoints)), problems

    def controller(self, identity, occurrences):
        sides = {'in': ([], []), 'out': ([], [])}
        for rec in occurrences:
            for direction in sides:
                if rec['language'] == 'FBD':
                    pins = self.audit.top.aoi_control.get(identity.data_type, ('PV', ('CV', 'CVEU')))
                    selected = (pins[0],) if direction == 'in' else pins[1]
                    # Use existing wires for native CV/CVEU; absent pins are not fabricated.
                    if identity.data_type.upper() in NATIVE and direction == 'out':
                        available = {w.get('FromParam') for w in rec['sheet'].findall('Wire') if w.get('FromID') == rec['node'].get('ID')}
                        selected = tuple(p for p in selected if p in available) or ('CV',)
                    results = [self.pin(rec, pin, direction) for pin in selected]
                elif rec['instruction'].upper() == 'PID' and len(rec['args']) >= 4:
                    operand = rec['args'][1 if direction == 'in' else 3]
                    results = [self.operand(operand, rec, direction)]
                else:
                    results = [([], [issue('AOI_ENVOLTORIO' if identity.data_type in self.audit.top.aoi_definitions else 'INSTRUCCION_LADDER_NO_SOPORTADA', rec, identity.base,
                                            detail=rec.get('literal', '') + '; requiere binding posicional de parámetros de la llamada.')])]
                for endpoints, problems in results:
                    sides[direction][0].extend(endpoints); sides[direction][1].extend(problems)
        return sides


def _write_csv(path, fields, rows):
    temporary = path.with_suffix('.csv.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=';')
        writer.writeheader(); writer.writerows(rows)
    temporary.replace(path)


def _format_side(endpoints, problems):
    values = ['EXTREMO_XML: ' + endpoint for endpoint in sorted(set(endpoints))]
    values += [f'{p["reason"]}: {p["path"]} | {p["current"]}' + (f' -> {p["next"]}' if p['next'] else '') + ' | ' + p['detail'] for p in problems]
    return ' || '.join(dict.fromkeys(values))


def generate(l5x_dir, approved_csv, output_dir):
    paths = sorted(Path(l5x_dir).glob('*.L5X'))
    if not paths:
        raise ValueError('No hay XML L5X')
    with Path(approved_csv).open(encoding='utf-8-sig', newline='') as handle:
        approved_rows = list(csv.DictReader(handle, delimiter=';'))
    approved = {(r['PLC'].casefold(), r['Scope'].casefold(), r['Instancia_Controlador'].casefold()) for r in approved_rows}
    if len(approved_rows) != 3 or len(approved) != 3:
        raise ValueError('La evidencia aprobada debe identificar exactamente tres controladores distintos')
    rows = []; metrics = Counter(); all_keys = set(); proved_keys = set()
    definitions = []; inventory_rows = []; internals = []; historical = Counter()
    for path in paths:
        audit = inspect_xml(path); top = audit.top; tracer = Tracer(audit)
        old = {a.controller.key: a for a in v3.build_associations(top)}
        used_types = {audit.controllers[k].data_type for k in audit.occurrences}
        # Reachability of AOI definitions from direct XML calls, including nested wrappers.
        reachable = set(used_types)
        all_definitions = {d.get('Name'): d for d in audit.controller.findall('AddOnInstructionDefinitions/AddOnInstructionDefinition')}
        # Include calls to non-controller wrappers in programs as roots too.
        for n in audit.controller.findall('Programs/Program/Routines/Routine/FBDContent/Sheet/AddOnInstruction'):
            reachable.add(n.get('Name', ''))
        for unit in audit.text_units:
            reachable.update(name for name, _, _ in calls(unit['text']) if name in all_definitions)
        direct = set(reachable)
        pending = sorted(reachable)
        while pending:
            name = pending.pop(0); definition = all_definitions.get(name)
            if definition is None: continue
            children = {n.get('Name', '') for n in definition.findall('.//AddOnInstruction')}
            for n in definition.findall('.//Rung/Text') + definition.findall('.//STContent/Line'):
                children.update(c for c, _, _ in calls(n.text or '') if c in all_definitions)
            for child in sorted(children - reachable):
                reachable.add(child); pending.append(child)
        declared_types = {i.data_type for i in top.declarations.values()}
        for definition in audit.definitions:
            name = definition['name']; metrics['definiciones_con_control_nativo'] += 1
            metrics['bloques_o_llamadas_nativas_dentro_definiciones'] += len(definition['native_paths'])
            metrics['definiciones_sin_tipo_declarado_criterio_legado'] += name not in declared_types
            metrics['definiciones_sin_invocacion_directa'] += name not in direct
            metrics['definiciones_no_alcanzadas_incluyendo_anidadas'] += name not in reachable
            definitions.append({'PLC': top.plc, 'Definicion': name, 'Camino_XML': definition['path'],
                                'Nativos_XML': ' | '.join(definition['native_paths']),
                                'Tipo_Declarado': 'SI' if name in declared_types else 'NO',
                                'Invocacion_Directa_Programs': 'SI' if name in direct else 'NO',
                                'Alcanzable_Incluyendo_AOI_Anidadas': 'SI' if name in reachable else 'NO',
                                'Cuenta_Como_Instancia': 'NO'})
        for key, identity in sorted(audit.controllers.items()):
            full = (top.plc.casefold(), *key)
            if full in all_keys:
                raise ValueError(f'PLC/Scope/Instancia duplicada entre archivos: {full}')
            all_keys.add(full); metrics['inventariados'] += 1
            occurrences = audit.occurrences.get(key, [])
            if occurrences:
                proved_keys.add(full); metrics['invocacion_xml_demostrada'] += 1
            else:
                metrics['declaraciones_sin_invocacion'] += 1
            for language in sorted({o['language'] for o in occurrences}):
                metrics['instancias_' + language] += 1
            metrics['ocurrencias_xml'] += len(occurrences)
            declaration = next(t for t in audit.controller.findall('Tags/Tag') + audit.controller.findall('Programs/Program/Tags/Tag')
                               if t.get('Name') == identity.base and audit.locations[id(t)].startswith(
                                   'Controller' + ("[@Name='" + top.controller + "']" if top.controller else '[1]'))
                               and (('/Programs/' not in audit.locations[id(t)]) if identity.scope == 'Controller' else
                                    f"/Program[@Name='{identity.scope.split(':',1)[1]}']/Tags" in audit.locations[id(t)]))
            declaration_path = audit.locations[id(declaration)]
            inventory_rows.append({'PLC': top.plc, 'Scope': identity.scope, 'Instancia': identity.base,
                                   'Tipo': identity.data_type, 'Declaracion_XML': declaration_path,
                                   'Invocacion_XML_Demostrada': 'SI' if occurrences else 'NO',
                                   'Ocurrencias': len(occurrences), 'Caminos_Invocacion_XML': ' | '.join(o['path'] for o in occurrences),
                                   'Excluida_Por_Evidencia_Aprobada': 'SI' if full in approved else 'NO'})
            previous = old[identity.key]
            previous_class = ('COMPLETO' if previous.inputs and previous.outputs else
                              'PID_SALIDA' if previous.outputs else
                              'ENTRADA_PID' if previous.inputs else 'SIN_EXTREMOS')
            historical[previous_class] += 1
            if full in approved:
                continue
            if occurrences:
                sides = tracer.controller(identity, occurrences)
            else:
                rec = {'path': declaration_path, 'language': 'XML', 'instruction': 'Tag DataType=' + identity.data_type}
                problem = issue('OTRO_CON_EVIDENCIA', rec, identity.base, detail=f'Declaración {identity.scope}/{identity.base} DataType={identity.data_type}; cero invocaciones exactas Block/AddOnInstruction FBD o llamadas RLL/ST en Controller/Programs. No existe corte de ejecución demostrable; revisar uso/invocación, no fabricar conexión.')
                sides = {'in': ([], [problem]), 'out': ([], [problem])}
            inp, pi = sides['in']; out, po = sides['out']
            blockers = pi + po
            if not blockers:
                rec = occurrences[0]
                blockers = [issue('OTRO_CON_EVIDENCIA', rec, identity.base, detail=f'Camino XML alcanza {len(set(inp))} entradas y {len(set(out))} salidas, fuera de los tres aprobados. Requiere validar exclusividad, cuerpo AOI y pertenencia; no se inventa un corte inexistente.')]
            missing_side = (po if inp and not out else pi if out and not inp else [])
            one_proved_hop = (bool(inp) != bool(out) and len(missing_side) == 1
                              and bool(missing_side[0].get('next'))
                              and missing_side[0]['reason'] not in ('OTRO_CON_EVIDENCIA',
                                                                  'PIN_SIN_CONEXION',
                                                                  'EXTREMO_COMPARTIDO'))
            priority = (1 if previous_class == 'PID_SALIDA' else
                        2 if previous_class == 'ENTRADA_PID' else
                        3 if one_proved_hop else 4)
            dominant_pool = (pi if priority == 1 and pi else
                             po if priority == 2 and po else blockers)
            dominant = dominant_pool[0]
            row = dict.fromkeys(COLUMNS, '')
            row.update(PLC=top.plc, Program=' | '.join(sorted({o['program'] for o in occurrences})) or (identity.scope.split(':',1)[1] if ':' in identity.scope else ''),
                       Scope=identity.scope, Routine=' | '.join(sorted({o['routine'] for o in occurrences})),
                       Instancia=identity.base, Tipo=identity.data_type,
                       Invocacion_XML_Demostrada='SI' if occurrences else 'NO',
                       Clasificacion_Previa=previous_class,
                       Tiene_Entrada='SI' if inp else 'NO', Tiene_Salida='SI' if out else 'NO',
                       Entrada_Encontrada=' | '.join(sorted(set(inp))), Salida_Encontrada=' | '.join(sorted(set(out))),
                       Punto_Exacto_Donde_Se_Corta_Entrada=_format_side(inp, pi) or 'Sin corte: extremo XML alcanzado',
                       Punto_Exacto_Donde_Se_Corta_Salida=_format_side(out, po) or 'Sin corte: extremo XML alcanzado',
                       Lenguaje=dominant['language'], Rutina=dominant['routine'], Instruccion_o_Bloque=dominant['instruction'],
                       Operando_Actual=dominant['current'], Siguiente_Operando=dominant['next'],
                       Motivo_Bloqueo=dominant['reason'], Submotivo_Bloqueo=_submotivo(dominant),
                       Detalle_Bloqueo=dominant['detail'],
                       Analizador_Faltante=IMPROVEMENTS[dominant['reason']],
                       Prioridad=priority, Confianza='BAJA')
            rows.append(row); internals.append((row, sides, blockers, bool(occurrences)))
    if not approved <= proved_keys:
        raise ValueError(f'Evidencia aprobada sin invocación exacta XML: {sorted(approved - proved_keys)}')
    if len(all_keys) != 213:
        raise ValueError(f'Universo declarado cambió: {len(all_keys)}; no forzar 213')
    metrics['excluidos_aprobados'] = len(approved); metrics['filas_frontera'] = len(rows)
    # Reverse endpoint ownership is scoped by PLC and includes all non-approved diagnostics.
    owners = defaultdict(set)
    for row in rows:
        for column in ('Entrada_Encontrada', 'Salida_Encontrada'):
            for endpoint in filter(None, row[column].split(' | ')):
                owners[(row['PLC'], endpoint.split(' -> ')[-1])].add((row['Scope'], row['Instancia']))
    for row, sides, blockers, invoked in internals:
        shared = sorted({endpoint.split(' -> ')[-1] for side in sides.values() for endpoint in side[0]
                         if len(owners[(row['PLC'], endpoint.split(' -> ')[-1])]) > 1})
        if shared:
            detail = 'Extremos compartidos XML: ' + ' | '.join(f'{e}: {sorted(owners[(row["PLC"], e)])}' for e in shared)
            row['Punto_Exacto_Donde_Se_Corta_Salida'] += ' || EXTREMO_COMPARTIDO: ' + detail
            if row['Tiene_Entrada'] == row['Tiene_Salida'] == 'SI':
                row['Motivo_Bloqueo'] = 'EXTREMO_COMPARTIDO'
                row['Submotivo_Bloqueo'] = 'EXTREMO_COMPARTIDO'
                row['Detalle_Bloqueo'] = detail
                row['Analizador_Faltante'] = IMPROVEMENTS['EXTREMO_COMPARTIDO']
            blockers.append({'reason': 'EXTREMO_COMPARTIDO'})
    summaries = []
    potential_keys_by_reason = defaultdict(set)
    for reason in sorted({r['Motivo_Bloqueo'] for r in rows}):
        group = [entry for entry in internals if entry[0]['Motivo_Bloqueo'] == reason]
        # Conditional ceiling ONLY where one side is known and this is the sole blocker type.
        potential = [row for row, sides, blockers, invoked in group if invoked
                     and bool(sides['in'][0]) != bool(sides['out'][0])
                     and {p['reason'] for p in blockers} == {reason}
                     and reason not in ('OTRO_CON_EVIDENCIA', 'EXTREMO_COMPARTIDO', 'PIN_SIN_CONEXION')]
        potential_keys_by_reason[reason].update(
            (r['PLC'], r['Scope'], r['Instancia']) for r in potential)
        summaries.append({'Motivo_Bloqueo': reason, 'Controladores_Afectados': len(group),
                          'Mejora': IMPROVEMENTS[reason], 'Estimacion_Minima': 0,
                          'Techo_Condicional_Lazos_Adicionales': len(potential), 'Cierres_Garantizados': 0,
                          'Base_Estimacion': 'Techo, no pronóstico: una sola mitad alcanzada y un único tipo de bloqueo en todas las ramas/ocurrencias. Sólo si la mejora demuestra la otra mitad física, unicidad y pertenencia. Afectados no equivale a cierres.',
                          'Identidades_Techo_Condicional': ' | '.join(f'{r["PLC"]}/{r["Scope"]}/{r["Instancia"]}' for r in potential)})
    cause_summaries = []
    for (reason, subreason), group in sorted(((key, list(values)) for key, values in itertools.groupby(
            sorted(rows, key=lambda r: (r['Motivo_Bloqueo'], r['Submotivo_Bloqueo'])),
            key=lambda r: (r['Motivo_Bloqueo'], r['Submotivo_Bloqueo']))), key=lambda item: item[0]):
        potential = [r for r in group
                     if (r['PLC'], r['Scope'], r['Instancia']) in potential_keys_by_reason[reason]]
        cause_summaries.append({
            'Motivo_Bloqueo': reason, 'Submotivo_Bloqueo': subreason,
            'Controladores_Afectados': len(group), 'Mejora': IMPROVEMENTS[reason],
            'Techo_Condicional_Lazos_Adicionales': len(potential), 'Cierres_Garantizados': 0,
            'Base_Estimacion': 'Techo condicionado a demostrar la mitad faltante, unicidad y pertenencia; no es un pronóstico.',
        })
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    for name, fields, data in (
        ('frontera_210_controladores.csv', COLUMNS, rows),
        ('frontera_controladores_con_invocacion_xml.csv', COLUMNS,
         [r for r in rows if r['Invocacion_XML_Demostrada'] == 'SI']),
        ('declaraciones_controlador_sin_invocacion.csv', COLUMNS,
         [r for r in rows if r['Invocacion_XML_Demostrada'] == 'NO']),
        ('resumen_frontera_por_motivo.csv', list(summaries[0]), summaries),
        ('resumen_frontera_por_causa.csv', list(cause_summaries[0]), cause_summaries),
        ('inventario_controladores_xml.csv', list(inventory_rows[0]), inventory_rows),
        ('definiciones_controladores_xml.csv', list(definitions[0]), definitions)):
        _write_csv(output/name, fields, data)
    metrics = dict(sorted(metrics.items()))
    metrics['prioridades'] = dict(sorted(Counter(str(r['Prioridad']) for r in rows).items()))
    metrics['categorias_legado_no_pin_aware'] = dict(sorted(historical.items()))
    metrics['prioridades_legado'] = {
        '1_PID_SALIDA': historical['PID_SALIDA'],
        '2_ENTRADA_PID': historical['ENTRADA_PID'],
    }
    metrics['advertencia'] = '213 declaraciones NO son 213 invocaciones. Tres definiciones sin tipo declarado NO son todas las definiciones sin uso. XML ejecutable no prueba ejecución runtime. Tiene_Entrada/Salida indica extremo candidato alcanzado, no cierre aprobado. No se verifica planificación de tareas ni alcanzabilidad de rutina.'
    metrics['limitaciones'] = 'Traza conservadora: FBD pines, SCL/MOV, transferencias MOV Ladder y PID posicional; detiene AOI, otras instrucciones, ST y agregados. Pines AOI candidatos heredados de v3 requieren demostrar semántica interna. Ningún caso de un salto restante certificado: prioridad 3 vacía, no se inventa distancia.'
    _write_csv(output/'metricas_frontera.csv', ['Metrica', 'Valor'], [{'Metrica': k, 'Valor': json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, dict) else v} for k, v in metrics.items()])
    consistency = [
        {'Metrica': 'instancias_declaradas', 'Valor': 213, 'Confirmada': 'SI',
         'Evidencia': 'Declaraciones DataType PID/PIDE o AOI de control, deduplicadas por PLC+scope+instancia'},
        {'Metrica': 'invocaciones_xml_demostradas', 'Valor': metrics['invocacion_xml_demostrada'], 'Confirmada': 'SI',
         'Evidencia': 'Block/AddOnInstruction FBD o llamada RLL/ST exacta bajo Controller/Programs'},
        {'Metrica': 'declaraciones_sin_invocacion', 'Valor': metrics['declaraciones_sin_invocacion'], 'Confirmada': 'SI',
         'Evidencia': 'Declaración presente, cero invocaciones exactas en Programs'},
        {'Metrica': 'definiciones_AOI_con_control_nativo', 'Valor': metrics['definiciones_con_control_nativo'], 'Confirmada': 'SI',
         'Evidencia': 'Definiciones AOI con PID/PIDE en FBD/RLL/ST; nunca contadas como lazo de planta'},
        {'Metrica': 'definiciones_AOI_no_alcanzadas', 'Valor': metrics['definiciones_no_alcanzadas_incluyendo_anidadas'], 'Confirmada': 'SI',
         'Evidencia': 'Sin camino de invocación desde Programs, incluyendo envoltorios AOI anidados'},
        {'Metrica': 'solicitud_ejecutados_unicos_213', 'Valor': metrics['invocacion_xml_demostrada'], 'Confirmada': 'NO',
         'Evidencia': f"{metrics['inventariados']} es inventario de declaraciones; sólo {metrics['invocacion_xml_demostrada']} tienen invocación XML demostrada"},
        {'Metrica': 'solicitud_definiciones_AOI_no_ejecutadas_3', 'Valor': metrics['definiciones_no_alcanzadas_incluyendo_anidadas'], 'Confirmada': 'NO',
         'Evidencia': f"El rastreo de invocaciones directas y anidadas encuentra {metrics['definiciones_no_alcanzadas_incluyendo_anidadas']}, no 3"},
    ]
    _write_csv(output/'consistencia_213_pid.csv', ['Metrica', 'Valor', 'Confirmada', 'Evidencia'], consistency)
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).resolve().parents[1]
    parser.add_argument('--l5x-dir', type=Path, default=base/'L5X_Produccion')
    parser.add_argument('--approved-csv', type=Path, default=base/'exports/evidencia_3_lazos_habilitados.csv')
    parser.add_argument('--output-dir', type=Path, default=base/'exports')
    args = parser.parse_args(argv)
    print(json.dumps(generate(args.l5x_dir, args.approved_csv, args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
