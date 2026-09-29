"""Reconcile the historical 693-tag catalogue with production L5X files.

This command is intentionally read-only for every SQLite input.  It produces a
review CSV; it never inserts, updates or deletes catalogue rows.  The historical
catalogue is used as an inventory/provenance source, not as numbering truth.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

try:
    from . import auditar_l5x as auditor
except ImportError:
    import auditar_l5x as auditor


CAMPOS = [
    'PLC_Origen', 'Tag_Anterior', 'Tag_Original_PLC', 'Encontrado_L5X',
    'Rol_Propuesto', 'Area', 'Variable', 'Funcion', 'Lazo_Topologico',
    'Confianza_Topologica', 'Tag_Propuesto_ISA', 'Accion', 'Motivo',
]

_RE_MIGRADO = re.compile(r'^\s*Migrado\s+de\s+(.+?)\s*$', re.I | re.S)
_PROCESS_FUNCTIONS = {
    'T', 'IT', 'I', 'V', 'CV', 'XV', 'SV', 'E', 'R', 'Q', 'S', 'SH',
    'SL', 'SHH', 'AH', 'AL', 'A', 'Y', 'Z', 'ZT', 'ZSC', 'ZSO', 'G',
}
_PID_PARAMETER = re.compile(
    r'(?:^|_)(?:KP|KI|KD|TR|TD|PV_MAX|PV_MIN|MV_MAX|MV_MIN|MV_MANUAL|'
    r'SP_MAX|SP_MIN|A1_M0|RELACION_AIRE|SEG_PRESION_SUP_[HL])(?:_|$)', re.I)


def _connect_ro(path: Path) -> sqlite3.Connection:
    path = path.resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn


def _read_catalogue(path: Path) -> list[dict]:
    with closing(_connect_ro(path)) as conn:
        rows = conn.execute('''
            SELECT t.*, a.codigo AS area, v.letra AS variable,
                   f.letra AS funcion
              FROM tags t
              JOIN areas a ON a.id=t.area_id
              JOIN variables v ON v.id=t.variable_id
              JOIN funciones f ON f.id=t.funcion_id
             ORDER BY t.id
        ''').fetchall()
    return [dict(row) for row in rows]


def _canonical_plc(value: str | None) -> str | None:
    value = (value or '').strip().lower()
    if not value:
        return None
    if value.startswith('destileria'):
        return 'destileria'
    if value.startswith('calderas_8_9_10_des'):
        return 'calderas_8_9_10_desaireador'
    if value == 'centrifuga_2_de_primera':
        return 'centrifuga_de_primera'
    return value


def _raw_name(row: dict) -> str:
    match = _RE_MIGRADO.match(row.get('descripcion') or '')
    return match.group(1).strip() if match else ''


def _normalise_operand(value: str) -> str:
    return (value or '').strip().lstrip('\\')


def _loop_confidence(group: dict) -> str:
    if not group.get('problemas'):
        return 'ALTA'
    if len(group.get('entradas_proceso', ())) == 1:
        return 'MEDIA'
    return 'BAJA'


def _is_pid_parameter(row: dict, raw: str, actual_controllers: set[str]) -> bool:
    clean = _normalise_operand(raw)
    if clean in actual_controllers:
        return False
    if row.get('funcion') in {'C', 'IC'}:
        # A controller according to the old name-only classifier is accepted
        # only if the L5X proves that it is an executed PID/AOI instance.
        return True
    return bool(_PID_PARAMETER.search(clean))


def _next_number(occupied: dict[tuple[str, str], set[int]], area: str,
                 variable: str, ranges: dict[str, tuple[int, int]]) -> int | None:
    start, end = ranges[area]
    used = occupied.setdefault((area, variable), set())
    for number in range(start, end + 1):
        if number not in used:
            used.add(number)
            return number
    return None


def reconstruir(backup_db: Path, current_db: Path, l5x_dir: Path,
                output_csv: Path) -> dict:
    if Path(output_csv).suffix.lower() != '.csv':
        raise ValueError('La salida debe ser un archivo CSV')
    old_rows = _read_catalogue(backup_db)
    current_rows = _read_catalogue(current_db)
    current_names = {r['tag_completo'] for r in current_rows}

    with closing(_connect_ro(current_db)) as conn:
        ranges = {r['codigo']: (r['rango_inicio'], r['rango_fin'])
                  for r in conn.execute('SELECT codigo,rango_inicio,rango_fin FROM areas WHERE activo=1')}
    occupied: dict[tuple[str, str], set[int]] = defaultdict(set)
    for row in current_rows:
        occupied[(row['area'], row['variable'])].add(int(row['numero_loop']))

    files = {p.stem.lower(): p for p in l5x_dir.glob('*.L5X')}
    file_text = {key: path.read_text(encoding='utf-8-sig', errors='ignore')
                 for key, path in files.items()}
    topologies = {key: auditor.parsear_topologia_l5x(path)
                  for key, path in files.items()}
    loops = []
    for key, top in topologies.items():
        for group in auditor.extraer_lazos_control(top):
            item = dict(group)
            item['archivo_key'] = key
            item['lazo_id'] = '/'.join(group['id'])
            item['confianza'] = _loop_confidence(group)
            loops.append(item)

    loops_by_member: dict[tuple[str, str], list[dict]] = defaultdict(list)
    actual_controllers: dict[str, set[str]] = defaultdict(set)
    for group in loops:
        actual_controllers[group['archivo_key']].add(_normalise_operand(group['controlador']))
        for member in group['miembros']:
            loops_by_member[(group['archivo_key'], _normalise_operand(member))].append(group)

    result = []
    for row in old_rows:
        raw = _raw_name(row)
        key = _canonical_plc(row.get('plc_origen'))
        found = bool(raw and key in file_text and raw in file_text[key])
        related = loops_by_member.get((key, _normalise_operand(raw)), []) if raw and key else []
        controller_set = actual_controllers.get(key, set())
        protected = row['tag_completo'] in current_names

        if protected:
            role, action = 'PROTEGIDO_MANUAL', 'CONSERVAR_SIN_CAMBIOS'
            proposal = row['tag_completo']
            reason = 'Registro presente en la base actual protegida'
        elif not raw:
            role, action, proposal = 'IDENTIDAD_NO_RECUPERADA', 'REVISION_MANUAL', ''
            reason = 'La descripción no conserva un nombre PLC con formato Migrado de ...'
        elif not found:
            role, action, proposal = 'NO_ENCONTRADO', 'REVISION_MANUAL', ''
            reason = 'El nombre histórico no aparece exactamente en el L5X seleccionado'
        elif _normalise_operand(raw) in controller_set:
            role, action, proposal = 'PID_CONTROL_REAL', 'RENUMERAR_CON_LAZO', ''
            reason = 'Instancia ejecutada de PID/AOI demostrada por el L5X'
        elif _is_pid_parameter(row, raw, controller_set):
            role, action, proposal = 'PARAMETRO_INTERNO_PID', 'EXCLUIR_COMO_INSTRUMENTO', ''
            reason = 'El clasificador anterior confundió un parámetro con un controlador ISA'
        elif row.get('funcion') in _PROCESS_FUNCTIONS:
            role = 'VARIABLE_PROCESO_O_ELEMENTO_FINAL'
            if related:
                action, proposal = 'RENUMERAR_CON_LAZO', ''
                reason = 'Identidad confirmada y relacionada con lógica de control'
            else:
                # Do not allocate a standalone number yet.  A missing relation
                # can mean either a genuinely independent instrument or a
                # data-flow edge the conservative tracer has not crossed.  An
                # automatic number here would reproduce the original +1 bug.
                action, proposal = 'VALIDAR_INSTRUMENTO_SIN_LAZO', ''
                reason = 'Identidad confirmada en L5X; todavía no se demostró si pertenece a un PID'
        else:
            role, action, proposal = 'OTRO', 'REVISION_MANUAL', ''
            reason = 'Función histórica fuera del conjunto de instrumentos de proceso'

        loop_ids = sorted({g['lazo_id'] for g in related})
        confidences = sorted({g['confianza'] for g in related})
        result.append({
            'PLC_Origen': row.get('plc_origen') or '',
            'Tag_Anterior': row['tag_completo'],
            'Tag_Original_PLC': raw,
            'Encontrado_L5X': 'SI' if found else 'NO',
            'Rol_Propuesto': role,
            'Area': row['area'], 'Variable': row['variable'], 'Funcion': row['funcion'],
            'Lazo_Topologico': ' | '.join(loop_ids),
            'Confianza_Topologica': ' | '.join(confidences),
            'Tag_Propuesto_ISA': proposal,
            'Accion': action, 'Motivo': reason,
        })

    # Add real controller instances that the old name-only catalogue omitted.
    old_raw = {(_canonical_plc(r.get('plc_origen')), _normalise_operand(_raw_name(r)))
               for r in old_rows if _raw_name(r)}
    controller_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for group in loops:
        controller_groups[(group['archivo_key'], _normalise_operand(group['controlador']))].append(group)
    for (file_key, controller), groups in sorted(controller_groups.items()):
        if (file_key, controller) in old_raw:
            continue
        areas = {g.get('area') for g in groups if g.get('area')}
        variables = {g.get('variable') for g in groups if g.get('variable')}
        loop_ids = sorted({g['lazo_id'] for g in groups})
        confidences = {g['confianza'] for g in groups}
        confidence = 'ALTA' if confidences == {'ALTA'} else ('MEDIA' if 'MEDIA' in confidences else 'BAJA')
        result.append({
            'PLC_Origen': Path(topologies[file_key]['archivo']).stem,
            'Tag_Anterior': '', 'Tag_Original_PLC': controller,
            'Encontrado_L5X': 'SI', 'Rol_Propuesto': 'PID_CONTROL_REAL',
            'Area': next(iter(areas)) if len(areas) == 1 else '',
            'Variable': next(iter(variables)) if len(variables) == 1 else '',
            'Funcion': 'C', 'Lazo_Topologico': ' | '.join(loop_ids),
            'Confianza_Topologica': confidence, 'Tag_Propuesto_ISA': '',
            'Accion': 'AGREGAR_CON_LAZO',
            'Motivo': 'Instancia ejecutada de PID/AOI no representada correctamente en el catálogo anterior',
        })

    # The historical catalogue is not a complete source of truth: several
    # scaled PVs and command outputs never reached it.  Surface every proven
    # endpoint from the topology so inputs and outputs do not disappear merely
    # because Claude's name-only pass omitted them.
    endpoint_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for group in loops:
        for operand in group.get('entradas_proceso', ()):
            endpoint_groups[(group['archivo_key'], _normalise_operand(operand), 'ENTRADA_PROCESO_DESCUBIERTA')].append(group)
        for operand in group.get('salidas_control', ()):
            endpoint_groups[(group['archivo_key'], _normalise_operand(operand), 'SALIDA_CONTROL_DESCUBIERTA')].append(group)
    for (file_key, operand, role), groups in sorted(endpoint_groups.items()):
        if (file_key, operand) in old_raw:
            continue
        areas = {g.get('area') for g in groups if g.get('area')}
        variables = {g.get('variable') for g in groups if g.get('variable')}
        loop_ids = sorted({g['lazo_id'] for g in groups})
        confidences = {g['confianza'] for g in groups}
        confidence = 'ALTA' if confidences == {'ALTA'} else ('MEDIA' if 'MEDIA' in confidences else 'BAJA')
        variable = next(iter(variables)) if len(variables) == 1 else ''
        if role.startswith('ENTRADA'):
            detected_variable, detected_function = auditor._evidencia_pv(operand)
            variable = detected_variable or variable
            function = detected_function or ('T' if variable else '')
            reason = 'Extremo PV demostrado por conexión a un controlador ejecutado'
        else:
            function = 'V' if re.search(r'(?:^|_)(?:VALVULA|VALVE|[FLPT]V)(?:_|$)', operand, re.I) else ''
            reason = 'Extremo de salida demostrado por conexión desde un controlador ejecutado'
        result.append({
            'PLC_Origen': Path(topologies[file_key]['archivo']).stem,
            'Tag_Anterior': '', 'Tag_Original_PLC': operand,
            'Encontrado_L5X': 'SI', 'Rol_Propuesto': role,
            'Area': next(iter(areas)) if len(areas) == 1 else '',
            'Variable': variable, 'Funcion': function,
            'Lazo_Topologico': ' | '.join(loop_ids),
            'Confianza_Topologica': confidence, 'Tag_Propuesto_ISA': '',
            'Accion': 'AGREGAR_CON_LAZO', 'Motivo': reason,
        })

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=CAMPOS, delimiter=';')
        writer.writeheader()
        writer.writerows(result)

    actions = Counter(r['Accion'] for r in result)
    roles = Counter(r['Rol_Propuesto'] for r in result)
    summary = {
        'registros_historicos': len(old_rows),
        'registros_protegidos_actuales': len(current_rows),
        'identidades_migradas': sum(bool(_raw_name(r)) for r in old_rows),
        'identidades_encontradas_l5x': sum(r['Encontrado_L5X'] == 'SI' for r in result[:len(old_rows)]),
        'lazos_control_detectados': len(loops),
        'controladores_unicos_detectados': len(controller_groups),
        'entradas_proceso_descubiertas': sum(r['Rol_Propuesto'] == 'ENTRADA_PROCESO_DESCUBIERTA' for r in result),
        'salidas_control_descubiertas': sum(r['Rol_Propuesto'] == 'SALIDA_CONTROL_DESCUBIERTA' for r in result),
        'filas_salida': len(result),
        'acciones': dict(sorted(actions.items())),
        'roles': dict(sorted(roles.items())),
        'salida': str(output_csv),
    }
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Reconstrucción ISA segura desde catálogo histórico y L5X')
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--db-actual', required=True, type=Path)
    parser.add_argument('--l5x-dir', required=True, type=Path)
    parser.add_argument('--salida', required=True, type=Path)
    args = parser.parse_args(argv)
    summary = reconstruir(args.backup, args.db_actual, args.l5x_dir, args.salida)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
