"""Auditoría histórica CSV: sin asignación de números nuevos ni escrituras SQLite.

Scope ausente se mantiene no probado, incluso cuando el XML actual sea único:
la ausencia de homónimos actuales no demuestra el scope del registro histórico.
"""
from __future__ import annotations

import re
import argparse
import csv
import hashlib
import json
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from collections import defaultdict


def registro_ocupacion(records):
    grouped = defaultdict(lambda: {'tags': set(), 'sources': set()})
    for r in records:
        key = (r['area'], int(r['numero']), r['owner'])
        grouped[key]['tags'].add(r['tag'])
        grouped[key]['sources'].add(r['source'])
    owners = defaultdict(set)
    tag_owners = defaultdict(set)
    for area, number, owner in grouped:
        owners[area, number].add(owner)
        for tag in grouped[area, number, owner]['tags']:
            tag_owners[area, number, tag].add(owner)
    result = []
    for (area, number, owner), values in sorted(grouped.items()):
        result.append(dict(Area=area, Numero=f'{number:03d}', Propietario=owner,
                           Tags='|'.join(sorted(values['tags'])),
                           Referencias='|'.join(sorted(values['sources'])),
                           Cantidad_Referencias=len(values['sources']),
                           Propietarios_Area_Numero=len(owners[area, number]),
                           Colision='POSIBLE_MULTIPLES_PROPIETARIOS' if len(owners[area, number]) > 1 else 'NO',
                           Tag_Duplicado='SI' if any(len(tag_owners[area, number, t]) > 1 for t in values['tags']) else 'NO'))
    return result


def hay_colision(registry, area, numero, allowed_owners):
    return any(r['Area'] == area and int(r['Numero']) == int(numero)
               and r['Propietario'] not in allowed_owners for r in registry)

MIGRADO = re.compile(r'^Migrado de ([A-Za-z_][A-Za-z0-9_]*(?:[.:\[\]A-Za-z0-9_]+)?)$')


def identidades_registro(row):
    match = MIGRADO.fullmatch(row.get('descripcion') or '')
    return {s for s in (row.get('alias_for'), row.get('tag_original'),
                        match.group(1) if match else '') if s}


def buscar_identidad(history, operand, physical=''):
    hits = []
    for h in history:
        tokens = identidades_registro(h)
        token = operand if operand in tokens else (physical if physical and physical in tokens else '')
        if token:
            hits.append(dict(h, _matched_token=token))
    return hits


def exacta_miembro(member, hit):
    plc, scope, operand = member['target']
    return identidad_exacta((plc, scope, hit.get('_matched_token', operand)), hit)


def identidad_exacta(target, row):
    plc, scope, operand = target
    return bool(scope and row.get('scope') == scope and row.get('plc_origen') == plc
                and operand in identidades_registro(row))


ROOT = Path(__file__).resolve().parents[1]
HISTORICO = ROOT / 'app_etiquetas/backups/tags_ingenio_antes_purga_20260911_110901_186931.db'
TAG = re.compile(r'(?<![A-Za-z0-9_])(\d{3})_([A-Z]{1,5})_(\d{3,4})(?![A-Za-z0-9_])')
CAMPOS = ('PLC Program Routine Scope Controlador Entrada_Fisica PID Salida_Fisica Area Variable_ISA '
          'Tag_Historico_Entrada Tag_Historico_PID Tag_Historico_Salida '
          'Numero_Historico_Entrada Numero_Historico_PID Numero_Historico_Salida Numero_Candidato '
          'Tag_Propuesto_Entrada Tag_Propuesto_PID Tag_Propuesto_Salida Origen_Numero Colision Confianza Decision Justificacion').split()


@contextmanager
def conexion_ro(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.row_factory = sqlite3.Row
        yield connection
    finally:
        connection.close()


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def leer_base(path):
    """Lee todas las tablas de usuario, sin helpers de inicialización."""
    with conexion_ro(path) as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if 'tags' not in tables or 'areas' not in tables:
            raise ValueError(f'Falta schema tags/areas: {path}')
        result = {t: [dict(r) for r in c.execute('SELECT * FROM ' + _quote(t))] for t in tables}
    for rows in result.values():
        rows.sort(key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False, default=str))
    return result


def propietario(row):
    # Stable record lineage across snapshots; PLC and original identity guard against ID reuse.
    return json.dumps([row.get('id'), row.get('fecha_creacion'), row.get('plc_origen'),
                       row.get('scope'), sorted(identidades_registro(row))], ensure_ascii=False, separators=(',', ':'))


def extraer_ocupacion(databases):
    refs = []
    known = defaultdict(set)
    for source, tables in databases.items():
        for row in tables['tags']:
            known[row.get('tag_completo', '')].add(propietario(row))
    coverage = []
    for source, tables in sorted(databases.items()):
        areas = {r['id']: str(r['codigo']) for r in tables['areas']}
        by_id = {r['id']: r for r in tables['tags']}
        for table, rows in sorted(tables.items()):
            coverage.append(dict(Fuente=source, Tabla=table, Filas=len(rows), Estado='LEIDA_COMPLETA'))
            for index, row in enumerate(rows):
                location = f'{source}:{table}:{row.get("id", index)}'
                matches = []
                for column, value in sorted(row.items()):
                    if isinstance(value, str):
                        matches.extend((m.group(1), m.group(3), m.group(0), column) for m in TAG.finditer(value))
                if 'numero_loop' in row and row.get('area_id') in areas:
                    matches.append((areas[row['area_id']], str(row['numero_loop']), row.get('tag_completo', ''), 'area_id+numero_loop'))
                for area, number, tag, column in matches:
                    if table == 'tags' and (column in ('tag_completo', 'area_id+numero_loop')):
                        owners = {propietario(row)}
                    elif row.get('tag_id') in by_id and tag == by_id[row['tag_id']].get('tag_completo'):
                        owners = {propietario(by_id[row['tag_id']])}
                    else:
                        # A mention of a known tag is a reference, not a new instrument.
                        owners = known.get(tag) or {'REFERENCIA_SIN_DUENO:' + tag}
                    for owner in sorted(owners):
                        refs.append(dict(area=area, numero=number, tag=tag, owner=owner, source=location + ':' + column))
    return registro_ocupacion(refs), coverage


def declaraciones(path):
    controller = ET.parse(path).getroot().find('Controller')
    if controller is None:
        raise ValueError(f'Sin Controller: {path}')
    result = defaultdict(set)
    for t in controller.findall('Tags/Tag'):
        result[t.get('Name')].add('Controller')
    for program in controller.findall('Programs/Program'):
        for t in program.findall('Tags/Tag'):
            result[t.get('Name')].add('Program:' + program.get('Name'))
    return result


def scope_actual(declared, operand, program):
    scopes = declared.get(operand, set())
    local = 'Program:' + program
    return local if local in scopes else ('Controller' if 'Controller' in scopes else '')


def evaluar(loop, members, registry):
    """No next-free fallback: only an exact, coherent historical anchor can be reused."""
    area = loop['Area_Inferida']; variable = loop['Variable_ISA_Inferida']
    row = dict.fromkeys(CAMPOS, '')
    row.update({k: loop.get(k, '') for k in ('PLC', 'Program', 'Routine', 'Scope')})
    row.update(Controlador=loop['Instancia_Controlador'], PID=loop['Instancia_Controlador'],
               Entrada_Fisica=loop['Entrada_Tag_Fisico'], Salida_Fisica=loop['Salida_Tag_Fisico'],
               Area=area, Variable_ISA=variable, Confianza='BAJA', Decision='PENDIENTE_NUMERO', Colision='NO_EVALUABLE')
    all_hits = [h for m in members for h in m['hits']]
    exact = [h for m in members for h in m['hits'] if exacta_miembro(m, h)]
    notes = []
    for member in members:
        role = member['role']
        row['Tag_Historico_' + role] = '|'.join(sorted({h.get('tag_completo', '') for h in member['hits']}))
        row['Numero_Historico_' + role] = '|'.join(sorted({str(h.get('numero_loop', '')).zfill(3) for h in member['hits']}))
        if not member['target'][1]:
            notes.append(f'{role}: declaración/scope actual no probado')
        if not member['hits']:
            notes.append(f'{role}: sin identidad histórica')
        elif not any(exacta_miembro(member, h) for h in member['hits']):
            notes.append(f'{role}: operando exacto pero PLC/scope histórico no exacto; no autoriza número')
    numbers = {int(h['numero_loop']) for h in all_hits}
    historic_areas = {h['_area'] for h in all_hits}
    malformed = any(not TAG.fullmatch(h['tag_completo']) or
                    TAG.fullmatch(h['tag_completo']).group(1) != h['_area'] or
                    int(TAG.fullmatch(h['tag_completo']).group(3)) != int(h['numero_loop']) for h in all_hits)
    contradictions = len(numbers) > 1 or bool(historic_areas - {area}) or malformed
    duplicated = any(len(member['hits']) > 1 for member in members)
    if duplicated:
        notes.append('Identidad histórica duplicada: múltiples registros independientes')
    if malformed:
        notes.append('Tag histórico inválido o discordante con área/número del catálogo')
    if contradictions:
        notes.append('CONTRADICCION: áreas históricas=' + '|'.join(sorted(historic_areas)) + '; área inferida=' + area + '; números históricos=' + '|'.join(map(str, sorted(numbers))))
    allowed = {propietario(h) for h in all_hits}  # partial candidate is not an independent intruder
    occupied = any(hay_colision(registry, h['_area'], h['numero_loop'], allowed) for h in all_hits)
    if occupied or duplicated:
        row.update(Decision='BLOQUEADO_COLISION', Colision='SI')
        notes.append('Ocupación por área: propietario ajeno o no demostrado; no se confunden referencias repetidas con dueños')
    elif exact and not contradictions and variable in ('L', 'F') and all(m['target'][1] for m in members):
        number = f'{next(iter(numbers)):03d}'
        row.update(Numero_Candidato=number, Confianza='ALTA', Colision='NO',
                   Decision='PROPUESTA_CONSERVAR_NUMERO' if all(len(m['hits']) == 1 and exacta_miembro(m, m['hits'][0]) for m in members) else 'PROPUESTA_REUNIFICAR',
                   Origen_Numero='Identidad exacta PLC+scope+operando en backup histórico pre-purga')
        for role, function in zip(('Entrada', 'PID', 'Salida'), (variable+'T', variable+'IC', variable+'V')):
            row['Tag_Propuesto_' + role] = f'{area}_{function}_{number}'
        notes.append('Propuesta CSV únicamente; no reserva ni aplica números')
    row['Justificacion'] = '; '.join(notes) or 'Sin ancla histórica exacta; jamás siguiente libre'
    return row


def _csv(path, rows, fields=None):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]), delimiter=';', lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def generar(evidencia, historico, bases, l5x_dir, output_dir, *, expected_loops=3, expected_history=693):
    historico = Path(historico).resolve()
    paths = sorted({Path(p).resolve() for p in bases} | {historico})
    output_dir = Path(output_dir).resolve()
    if not output_dir.is_relative_to(ROOT):
        raise ValueError('La salida debe permanecer dentro del proyecto')
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with Path(evidencia).open(encoding='utf-8-sig', newline='') as stream:
        loops = list(csv.DictReader(stream, delimiter=';'))
    if len(loops) != expected_loops:
        raise ValueError('Cantidad inesperada de lazos habilitados')
    label = lambda p: p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.name
    databases = {label(p): leer_base(p) for p in paths}
    history = databases[label(historico)]['tags']
    if len(history) != expected_history:
        raise ValueError(f'Histórico no es el universo esperado {expected_history}: {len(history)}')
    areas = {r['id']: str(r['codigo']) for r in databases[label(historico)]['areas']}
    for h in history:
        h['_area'] = areas[h['area_id']]
    registry, coverage = extraer_ocupacion(databases)
    evidence_rows = []; proposals = []
    declarations = {}
    for loop in sorted(loops, key=lambda r: (r['PLC'], r['Scope'], r['Instancia_Controlador'])):
        plc = loop['PLC']
        if plc not in declarations:
            declarations[plc] = declaraciones(Path(l5x_dir) / (plc + '.L5X'))
        members = []
        for role, key in (('Entrada', 'Entrada_Tag'), ('PID', 'Instancia_Controlador'), ('Salida', 'Salida_Tag')):
            operand = loop[key]
            scope = scope_actual(declarations[plc], operand, loop['Program'])
            target = (plc, scope, operand)
            physical = loop.get(role + '_AliasFor') or loop.get(role + '_Tag_Fisico', '') if role != 'PID' else ''
            hits = buscar_identidad(history, operand, physical)
            members.append(dict(role=role, target=target, hits=hits))
            details = []
            for h in hits:
                details.append(dict(PLC=h.get('plc_origen') or '', Scope=h.get('scope') or '',
                                    Tag=h['tag_completo'], Numero=h['numero_loop'], Area=h['_area'],
                                    Descripcion=h.get('descripcion') or '', Migrado_de=(MIGRADO.fullmatch(h.get('descripcion') or '').group(1) if MIGRADO.fullmatch(h.get('descripcion') or '') else ''),
                                    Token_Matcheado=h['_matched_token'], Exactitud='EXACTA' if exacta_miembro(members[-1], h) else 'PARCIAL_PLC_SCOPE_NO_PROBADO', Registro_ID=h['id']))
            evidence_rows.append(dict(PLC=plc, Program=loop['Program'], Routine=loop['Routine'], Scope=scope,
                                      Scope_Controlador=loop['Scope'], Rol=role, Identidad=operand,
                                      Identidad_Fisica=physical,
                                      Scopes_Declarados='|'.join(sorted(declarations[plc].get(operand, set()))),
                                      Token_Matcheado='|'.join(d['Token_Matcheado'] for d in details), Tag_Historico='|'.join(d['Tag'] for d in details), Numero_Historico='|'.join(str(d['Numero']).zfill(3) for d in details),
                                      PLC_Historico='|'.join(d['PLC'] for d in details), Scope_Historico='|'.join(d['Scope'] for d in details),
                                      Descripcion='|'.join(d['Descripcion'] for d in details), Migrado_de='|'.join(d['Migrado_de'] for d in details),
                                      Exactitud='EXACTA' if any(d['Exactitud']=='EXACTA' for d in details) else ('PARCIAL_PLC_SCOPE_NO_PROBADO' if details else 'SIN_COINCIDENCIA'),
                                      Fuente=label(historico), Candidatos_JSON=json.dumps(details, ensure_ascii=False, sort_keys=True)))
        proposals.append(evaluar(loop, members, registry))
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if before != after:
        raise RuntimeError('Cambió una base durante la auditoría; no se publican propuestas')
    output_dir.mkdir(parents=True, exist_ok=True)
    _csv(output_dir/'propuesta_numeracion_3_lazos.csv', proposals, CAMPOS)
    _csv(output_dir/'evidencia_historica_9_identidades.csv', evidence_rows)
    _csv(output_dir/'registro_global_ocupacion.csv', registry)
    _csv(output_dir/'cobertura_tablas_historicas.csv', coverage)
    _csv(output_dir/'verificacion_bases_solo_lectura.csv', [dict(Fuente=label(p), SHA256_Antes=before[p], SHA256_Despues=after[p], Sin_Cambios='SI') for p in paths])
    return dict(lazos=len(proposals), identidades=len(evidence_rows), registros_ocupacion=len(registry),
                bases=len(paths), tablas=len(coverage), decisiones={d: sum(r['Decision']==d for r in proposals) for d in sorted({r['Decision'] for r in proposals})})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'exports')
    args = parser.parse_args(argv)
    # Universe: production 11 + pre-purge 693, including every user table/reference.
    current = ROOT/'app_etiquetas/tags_ingenio.db'
    with conexion_ro(current) as c:
        count = c.execute('SELECT count(*) FROM tags').fetchone()[0]
    if count != 11:
        raise ValueError(f'Producción esperada 11, encontrada {count}')
    bases = [current, HISTORICO]
    print(json.dumps(generar(ROOT/'exports/evidencia_3_lazos_habilitados.csv', HISTORICO,
                             bases, ROOT/'L5X_Produccion', args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
