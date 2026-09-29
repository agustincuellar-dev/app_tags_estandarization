"""Migra familias completas del CSV; nunca inserta tags ni modifica catálogos.

Uso: python src/migrar_alta_confianza.py [--csv ARCHIVO] [--db ARCHIVO]
     Agregar --simular para validar y ejecutar con ROLLBACK, sin persistir.
Realizar un respaldo consistente antes de ejecutar sobre producción.
El prefijo de Estado es autorización del CSV, no verificación de campo.
"""
import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'Propuesta — familia nueva'
FIELDS = {'Tag_Original', 'Tag_Propuesto_ISA', 'Bloque_Lógico', 'Estado'}


def migrar(csv_path, db_path, simular=False):
    """Una sola transacción para todas las familias; falla cerrada ante ambigüedad."""
    with Path(csv_path).open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source, delimiter=';')
        if not FIELDS.issubset(reader.fieldnames or []):
            raise ValueError('Faltan columnas obligatorias del CSV')
        families = defaultdict(list)
        for row in reader:
            if None in row or any(row.get(k) is None for k in FIELDS):
                raise ValueError('Fila CSV mal formada')
            families[row['Bloque_Lógico']].append(row)
    selected = []
    for block, rows in families.items():
        accepted = [r for r in rows if r['Estado'].startswith(PREFIX)]
        if not accepted:
            continue
        if not block or len(accepted) != len(rows):
            raise ValueError(f'Familia incompleta o con estados mixtos: {block}')
        selected.extend(accepted)

    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=rw', uri=True,
                           isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('BEGIN IMMEDIATE')
        plan = []
        errors = []
        seen_ids, seen_targets = set(), set()
        loop_blocks = {}
        family_keys = defaultdict(set)
        family_functions = defaultdict(set)
        for row in selected:
            original, target, block = (row[k] for k in ('Tag_Original','Tag_Propuesto_ISA','Bloque_Lógico'))
            match = re.fullmatch(r'([0-9]{3})_([A-Z])([A-Z]+)_([0-9]{3,4})', target)
            if not original or original != original.strip() or not match:
                raise ValueError(f'Identificador inválido: {original!r} -> {target!r}')
            area, variable, function, number = match.groups()
            key = f'{area}_{variable}_{number}'
            if key in loop_blocks and loop_blocks[key] != block:
                raise ValueError(f'Dos familias comparten destino: {key}')
            loop_blocks[key] = block
            family_keys[block].add(key)
            family_functions[block].add(function)
            catalogs = []
            for table, column, value in [('areas','codigo',area),('variables','letra',variable),('funciones','letra',function)]:
                found = conn.execute(f'SELECT id FROM {table} WHERE {column}=?',(value,)).fetchall()
                if len(found) != 1:
                    raise ValueError(f'Catálogo inexistente o ambiguo: {table} {value}')
                catalogs.append(found[0]['id'])
            # Identidad exacta exclusivamente. No buscar por descripciones ni substrings.
            matches = conn.execute('SELECT * FROM tags WHERE tag_completo=? OR alias_for=?',
                                   (original,original)).fetchall()
            if len(matches) != 1:
                errors.append(f'{original}: {len(matches)} registros coincidentes')
                continue
            record = matches[0]
            plc = record['plc_origen']
            if plc and plc != block.split('/')[0]:
                raise ValueError(f'PLC de origen incompatible: {original}')
            if record['alias_for'] not in (None, '', original):
                raise ValueError(f'Procedencia previa diferente; no sobrescribir: {original}')
            if record['id'] in seen_ids or target in seen_targets:
                raise ValueError(f'Origen o destino duplicado: {original} -> {target}')
            seen_ids.add(record['id']); seen_targets.add(target)
            plan.append((record, target, original, catalogs, int(number), key))
        if errors:
            raise ValueError('No se puede migrar la familia completa:\n' + '\n'.join(errors))
        for block, keys in family_keys.items():
            functions = family_functions[block]
            if len(keys) != 1 or not (functions & {'T','IT'} and functions & {'C','IC'} and functions & {'V','CV'}):
                raise ValueError(f'Familia sin entrada, controlador y salida coherentes: {block}')
        for record, target, original, ids, number, key in plan:
            conflicts = conn.execute('SELECT id FROM tags WHERE tag_completo=? OR (area_id=? AND variable_id=? AND numero_loop=?)',
                                     (target, ids[0], ids[1], number)).fetchall()
            if any(r['id'] not in seen_ids for r in conflicts):
                raise ValueError(f'Destino/lazo ocupado por registros ajenos: {key}')
        counts = Counter()
        for record, target, original, ids, number, key in plan:
            if (record['tag_completo'],record['alias_for'],record['area_id'],record['variable_id'],record['funcion_id'],record['numero_loop']) == (target,original,*ids,number):
                continue
            changed = conn.execute('UPDATE tags SET tag_completo=?, alias_for=?, area_id=?, variable_id=?, funcion_id=?, numero_loop=?, fecha_modificacion=datetime(\'now\',\'localtime\') WHERE id=?',
                                   (target,original,*ids,number,record['id']))
            if changed.rowcount != 1:
                raise sqlite3.IntegrityError(f'Actualización no unívoca: {original}')
            counts[key] += 1
        if conn.execute('PRAGMA foreign_key_check').fetchall():
            raise sqlite3.IntegrityError('Referencias inválidas en la base')
        conn.execute('ROLLBACK' if simular else 'COMMIT')
        return dict(sorted(counts.items()))
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv',type=Path,default=ROOT/'exports/propuestas_auditoria.csv')
    parser.add_argument('--db',type=Path,default=ROOT/'app_etiquetas/tags_ingenio.db')
    parser.add_argument('--simular',action='store_true')
    args = parser.parse_args()
    try:
        counts = migrar(args.csv,args.db,args.simular)
    except (ValueError,sqlite3.Error,OSError) as error:
        print(f'ABORTADO; ningún cambio confirmado.\n{error}',file=sys.stderr)
        return 1
    print('SIMULACIÓN (ROLLBACK)' if args.simular else 'Migración confirmada (COMMIT)')
    for loop, count in counts.items():
        print(f'Lazo {loop}: {count} tags')
    print(f'Total: {sum(counts.values())} tags actualizados')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
