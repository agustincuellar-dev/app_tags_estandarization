"""Opción B: migración transaccional del plan v5 homologado a producción.

Dry-run por defecto (ejecuta todo y revierte). Con --apply: backup
byte-idéntico, una única transacción y verificación posterior en solo lectura.

Uso:
  python src/migrar_plan_v5_a_produccion_290926.py            # dry-run
  python src/migrar_plan_v5_a_produccion_290926.py --apply    # producción
"""
import argparse
import csv
import hashlib
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / 'exports'
DB = ROOT / 'app_etiquetas/tags_ingenio.db'
BACKUPS = ROOT / 'app_etiquetas/backups'
BACKUP = BACKUPS / 'tags_ingenio_pre_v5_196tags_290926.db'
CSV = EX / 'plan_maestro_consolidado_v5_homologado_290926.csv'
EXPECTED_DB = 'dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522'
EXPECTED_CSV = 'dcd12ccb77bb2b17b2efd132a375a6fb49e4e2fa42a3c014484cbb63d1eb369b'
TOTAL_ESPERADO = 478
PROTECTED = ['200_PIT_004', '200_PIC_004', '200_PV_004', '200_LT_035', '200_LIC_035', '200_LV_035',
             '200_FT_080', '200_FIC_080', '200_FV_080', '250_PV_001', '250_PV_002']
USUARIO = 'Agustin (via Hermes)'
SENAL = {'T': ('REAL', 'Analógico', 'Entrada'), 'IT': ('REAL', 'Analógico', 'Entrada'),
         'IC': ('REAL', 'Analógico', 'Memoria / Red'), 'V': ('REAL', 'Analógico', 'Salida'),
         'XV': ('REAL', 'Digital', 'Salida'), 'Y': ('REAL', 'Analógico', 'Salida'),
         'SH': ('BOOL', 'Digital', 'Entrada'), 'SHH': ('BOOL', 'Digital', 'Entrada'),
         'SL': ('BOOL', 'Digital', 'Entrada')}
PLC_PREFIJO = {'FLEX5000_MIELES': 'FABRICA', 'ISLA_FAB_AI': 'FABRICA', 'ISLA_FAB_DI': 'FABRICA',
               'SULFO_ENCALADO': 'FABRICA', 'BP_3_RECALENTADORES': 'FABRICA',
               'BP_ANALOGICA': 'Calderas_8_9_10_Desaireador', 'BP_DIGITALES': 'Calderas_8_9_10_Desaireador',
               'Desaireador': 'Calderas_8_9_10_Desaireador', 'Desaireador_2': 'Calderas_8_9_10_Desaireador',
               'EVAPORADOR': 'DESTILERIA', 'jw_fermerntacion_2022': 'DESTILERIA',
               'fermerntacion2022_islas': 'DESTILERIA', 'jw_fermentacion_2022_digital': 'DESTILERIA'}
CANAL = re.compile(r'[A-Za-z_][A-Za-z_0-9]*:\d+:[IO](?:\.[A-Za-z_0-9\[\]]+)+')
TAGRE = re.compile(r'(\d{3})_([A-Z]+)_(\d{3})([A-Z]?)')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def identidad_corta(x):
    for col in ('Identidad_PLC_Efectiva', 'Identidad_PLC', 'Identidad_Actual'):
        v = (x.get(col) or '').strip()
        if v:
            return v.split(' <- ')[0].split(' (')[0].strip()[:120]
    return ''


def canal_de(x):
    for col in ('Direccion_Modulo_Efectiva', 'Destino_Fisico', 'Direccion_Modulo', 'AliasFor_Direccion_Fisica'):
        m = CANAL.search(x.get(col) or '')
        if m:
            return m.group(0)
    m = CANAL.search(identidad_corta(x))
    return m.group(0) if m else ''


class Catalogos:
    def __init__(self, con):
        self.area_id, self.area_nombre, self.area_cod = {}, {}, {}
        for cod, aid, nom in con.execute('select codigo,id,nombre from areas'):
            self.area_id[cod] = aid
            self.area_nombre[cod] = nom
            self.area_cod[aid] = cod
        self.var_id, self.var_nombre = {}, {}
        for aid, letra, nom in con.execute('select id,letra,nombre from variables'):
            self.var_id[letra] = aid
            self.var_nombre[letra] = nom
        self.fun_id, self.fun_nombre = {}, {}
        for aid, letra, nom in con.execute('select id,letra,nombre from funciones'):
            self.fun_id[letra] = aid
            self.fun_nombre[letra] = nom


def describir(x, cat, area, var, func, ident):
    partes = [f'{cat.fun_nombre[func]} de {cat.var_nombre[var].lower()}']
    lazo = (x['Instancia'] or x['Instancia_PID'] or '').strip()
    if lazo:
        partes.append('lazo ' + lazo)
    if ident:
        partes.append('Migrado de: ' + ident)
    partes.append(x['Bloque_Maestro'])
    partes.append(f'área {area} ({cat.area_nombre[area]})')
    return ' — '.join(partes[:2]) + '; ' + '; '.join(partes[2:])


def preparar_altas(filas, cat):
    altas = []
    for x in filas:
        tag = x['Tag_Destino_Efectivo']
        m = TAGRE.fullmatch(tag)
        if not m:
            raise SystemExit('Tag con forma inválida: ' + tag)
        area, morfema, numero, sufijo = m.groups()
        pares = [(v, f) for v in cat.var_id for f in cat.fun_id if v + f == morfema]
        if len(pares) != 1:
            raise SystemExit(f'Morfema no descomponible de forma única: {tag} -> {pares}')
        var, func = pares[0]
        if x['Area_Efectiva'] and x['Area_Efectiva'] != area:
            raise SystemExit(f'Área del CSV distinta del tag: {tag}')
        if x['Variable_Efectiva'] and x['Variable_Efectiva'] != var:
            raise SystemExit(f'Variable del CSV distinta del tag: {tag}')
        if int(x['Numero_Efectivo']) != int(numero):
            raise SystemExit(f'Número del CSV distinto del tag: {tag}')
        ident = identidad_corta(x)
        canal = canal_de(x)
        crudo = ' | '.join((x.get(c) or '') for c in ('Direccion_Modulo_Efectiva', 'Destino_Fisico',
                                                      'Direccion_Modulo', 'AliasFor_Direccion_Fisica',
                                                      'Identidad_PLC_Efectiva', 'Identidad_PLC'))
        if canal and canal not in crudo:
            raise SystemExit(f'Canal derivado fuera de la evidencia: {tag} -> {canal}')
        if canal and crudo[crudo.index(canal) + len(canal):][:1] in ('.', '['):
            raise SystemExit(f'Canal truncado en {tag}: {canal}')
        plc = (x['PLC_Fuente_V2'] or x['PLC'] or '').strip()
        if not plc and canal:
            plc = PLC_PREFIJO.get(canal.split(':')[0], '')
        datatype, tipo, ent_sal = SENAL.get(func, ('REAL', 'Analógico', 'N/D'))
        altas.append({'tag': tag, 'area': area, 'var': var, 'func': func, 'numero': int(numero),
                      'descripcion': describir(x, cat, area, var, func, ident),
                      'plc': plc or None, 'ident': ident or tag, 'canal': canal,
                      'comentarios': ('Migrado de: ' + ident) if ident else '',
                      'datatype': datatype, 'tipo_senal': tipo, 'entrada_salida': ent_sal})
    # Inferencia de PLC para filas sin canal (controladores): hereda del resto del lazo.
    for _ in range(3):
        grupos = defaultdict(set)
        for a in altas:
            if a['plc']:
                grupos[(a['area'], a['numero'])].add(a['plc'])
        for a in altas:
            if not a['plc'] and len(grupos.get((a['area'], a['numero']), ())) == 1:
                a['plc'] = next(iter(grupos[(a['area'], a['numero'])]))
    return altas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='escribe en producción (por defecto: dry-run)')
    ap.add_argument('--permitir-backup-existente', action='store_true',
                    help='reutiliza el backup ya verificado en vez de abortar')
    args = ap.parse_args()

    if digest(DB) != EXPECTED_DB:
        raise SystemExit('tags_ingenio.db no coincide con la línea base autorizada')
    if digest(CSV) != EXPECTED_CSV:
        raise SystemExit('El CSV homologado cambió')
    with CSV.open(encoding='utf-8-sig', newline='') as f:
        filas = list(csv.DictReader(f, delimiter=';'))
    if len(filas) != 722:
        raise SystemExit('Universo del CSV inesperado')

    con = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    con.execute('PRAGMA query_only=ON')
    cat = Catalogos(con)
    columnas = [d[0] for d in con.execute('select * from tags limit 0').description]
    prod = {r[1]: dict(zip(columnas, r)) for r in con.execute('select * from tags')}
    total_auditoria_pre = con.execute('select count(*) from auditoria').fetchone()[0]
    con.close()
    if len(prod) != 196 or not set(PROTECTED) <= set(prod):
        raise SystemExit('Producción distinta de 196 registros o sin los tags manuales')

    act = [x for x in filas if x['Operacion_Efectiva'] in ('INSERT', 'UPDATE', 'DELETE')]
    reparto = Counter(x['Operacion_Efectiva'] for x in act)
    if reparto != {'INSERT': 294, 'UPDATE': 43, 'DELETE': 12}:
        raise SystemExit('Reparto inesperado: ' + str(dict(reparto)))
    if any(x['Estado_Homologacion_V5'] != 'HOMOLOGADO' for x in act):
        raise SystemExit('Hay operaciones sin homologar')
    altas = preparar_altas([x for x in act if x['Operacion_Efectiva'] == 'INSERT'], cat)
    upd = [x for x in act if x['Operacion_Efectiva'] == 'UPDATE']
    renombres = [x for x in upd if x['Tag_Destino_Efectivo'] != x['Tag_Origen_Efectivo']]
    metadatos = [x for x in upd if x['Tag_Destino_Efectivo'] == x['Tag_Origen_Efectivo']]
    bajas = [x for x in act if x['Operacion_Efectiva'] == 'DELETE']
    if (len(renombres), len(metadatos), len(bajas)) != (26, 17, 12):
        raise SystemExit('Composición de UPDATE/DELETE inesperada')

    por_id = {}
    for x in upd + bajas:
        oid = int(x['ID_Origen_Efectivo'])
        fila = next((f for f in prod.values() if f['id'] == oid), None)
        if fila is None or fila['tag_completo'] != x['Tag_Origen_Efectivo']:
            raise SystemExit('Origen no encontrado: ' + x['Tag_Origen_Efectivo'])
        por_id[oid] = fila
    destinos = [a['tag'] for a in altas] + [x['Tag_Destino_Efectivo'] for x in renombres]
    if len(destinos) != len(set(destinos)):
        raise SystemExit('Destinos repetidos')
    if set(destinos) & set(prod):
        raise SystemExit('Destino ya en producción: ' + str(sorted(set(destinos) & set(prod))))
    for r in renombres:
        m = TAGRE.fullmatch(r['Tag_Destino_Efectivo'])
        if not m or m[1] != r['Area_Efectiva'] or m[2][0] != r['Variable_Efectiva']:
            raise SystemExit('Renombre inconsistente: ' + r['Tag_Destino_Efectivo'])
    for x in act:
        if x['Tag_Origen_Efectivo'] in PROTECTED or x['Tag_Destino_Efectivo'] in PROTECTED:
            raise SystemExit('Tag manual dentro de las operaciones')

    sin_plc = [a['tag'] for a in altas if not a['plc']]
    sin_canal = [a['tag'] for a in altas if not a['canal']]
    print('PREFLIGHT OK')
    print(f'  INSERT {len(altas)} | UPDATE {len(upd)} (renombres {len(renombres)}, metadatos {len(metadatos)})'
          f' | DELETE {len(bajas)}')
    print(f'  altas sin PLC determinado: {len(sin_plc)} {sin_plc[:5]}')
    print(f'  altas sin canal físico (controladores): {len(sin_canal)}')
    print('  señal por función:', {k: v[1] + '/' + v[2] for k, v in SENAL.items()})
    print('  ejemplo de alta:', {k: v for k, v in list(altas[0].items())[:9]})
    if digest(DB) != EXPECTED_DB:
        raise SystemExit('La base cambió durante el preflight')

    if not args.apply:
        print('\nDRY-RUN: sin backup y sin abrir en escritura')
    else:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        if BACKUP.exists():
            if not args.permitir_backup_existente or digest(BACKUP) != EXPECTED_DB:
                raise SystemExit('El backup ya existe y no sirve como línea base: ' + str(BACKUP))
            print('\nBACKUP reutilizado', BACKUP)
            print('  SHA-256 backup == línea base:', digest(BACKUP) == EXPECTED_DB)
        else:
            shutil.copy2(DB, BACKUP)
            if digest(BACKUP) != EXPECTED_DB or digest(DB) != EXPECTED_DB:
                raise SystemExit('El backup no es byte-idéntico; se aborta antes de escribir')
            print('\nBACKUP', BACKUP)
            print('  SHA-256 backup == línea base:', digest(BACKUP))

    con = sqlite3.connect(DB.as_uri() + '?mode=rw', uri=True)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA journal_mode=DELETE')
        if con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise SystemExit('No se pudo activar foreign_keys')
        con.execute('BEGIN IMMEDIATE')
        creados = renombrados = metidos = borrados = 0
        nuevas_auditorias = 0
        for a in altas:
            cur = con.execute('''insert into tags (tag_completo, area_id, variable_id, funcion_id, numero_loop,
                                 descripcion, estado, creado_por, plc_origen, comentarios, datatype, alias_for,
                                 fluido_proceso, tipo_senal, entrada_salida)
                                 values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                              (a['tag'], cat.area_id[a['area']], cat.var_id[a['var']], cat.fun_id[a['func']],
                               a['numero'], a['descripcion'], 'Planificado', USUARIO, a['plc'], a['comentarios'],
                               a['datatype'], a['canal'], 'No determinado en la identidad del lazo',
                               a['tipo_senal'], a['entrada_salida']))
            con.execute('insert into auditoria (tag_id, accion, detalle, usuario) values (?,?,?,?)',
                        (cur.lastrowid, 'CREACION',
                         f'Migracion masiva v5 29/09/2026: Migrado de {a["ident"]}' +
                         (f' ({a["canal"]})' if a['canal'] else ''), USUARIO))
            creados += 1
            nuevas_auditorias += 1
        for x in renombres:
            oid = int(x['ID_Origen_Efectivo'])
            fila = por_id[oid]
            desc = fila['descripcion'] or ''
            area_prev = cat.area_cod[fila['area_id']]
            if area_prev != x['Area_Efectiva']:
                desc = re.sub(r'área \d{3} \([^)]*\)',
                              f'área {x["Area_Efectiva"]} ({cat.area_nombre[x["Area_Efectiva"]]})', desc)
            m = TAGRE.fullmatch(x['Tag_Destino_Efectivo'])
            con.execute('''update tags set tag_completo=?, area_id=?, variable_id=?, funcion_id=?, numero_loop=?,
                           descripcion=?, fecha_modificacion=datetime('now','localtime') where id=?''',
                        (x['Tag_Destino_Efectivo'], cat.area_id[m[1]], cat.var_id[m[2][0]],
                         cat.fun_id[m[2][1:]], int(m[3]), desc, oid))
            con.execute('insert into auditoria (tag_id, accion, detalle, usuario) values (?,?,?,?)',
                        (oid, 'MODIFICACION',
                         f'Migracion masiva v5 29/09/2026: {x["Tag_Origen_Efectivo"]} -> '
                         f'{x["Tag_Destino_Efectivo"]} ({x["Nota_Maestra"][:160]})', USUARIO))
            renombrados += 1
            nuevas_auditorias += 1
        for x in metadatos:
            oid = int(x['ID_Origen_Efectivo'])
            fila = por_id[oid]
            canal = canal_de(x)
            alias = (fila['alias_for'] or '').strip()
            nuevo_alias = alias
            if canal and not alias:
                nuevo_alias = canal
            elif canal and canal not in alias:
                nuevo_alias = alias + ' | ' + canal
            marca = (f'Canal físico verificado 29/09/2026: {identidad_corta(x)}'
                     + (f' ({canal})' if canal else ''))
            comentarios = (fila['comentarios'] or '').strip()
            comentarios = (comentarios + ' | ' + marca) if comentarios else marca
            con.execute("update tags set alias_for=?, comentarios=?, fecha_modificacion=datetime('now','localtime')"
                        ' where id=?', (nuevo_alias, comentarios, oid))
            con.execute('insert into auditoria (tag_id, accion, detalle, usuario) values (?,?,?,?)',
                        (oid, 'MODIFICACION', f'Migracion masiva v5 29/09/2026: {marca}', USUARIO))
            metidos += 1
            nuevas_auditorias += 1
        for x in bajas:
            oid = int(x['ID_Origen_Efectivo'])
            con.execute("update auditoria set tag_id=NULL, detalle=coalesce(detalle,'')"
                        " || ' [tag ' || ? || ' eliminado 29/09/2026]' where tag_id=?",
                        (x['Tag_Origen_Efectivo'], oid))
            con.execute('delete from tags where id=?', (oid,))
            con.execute('insert into auditoria (tag_id, accion, detalle, usuario) values (NULL,?,?,?)',
                        ('ELIMINACION', f'Migracion masiva v5 29/09/2026: baja de {x["Tag_Origen_Efectivo"]}'
                                        f' ({x["Nota_Maestra"][:160]})', USUARIO))
            borrados += 1
            nuevas_auditorias += 1

        total = con.execute('select count(*) from tags').fetchone()[0]
        if total != TOTAL_ESPERADO:
            raise SystemExit(f'Conteo {total} distinto de {TOTAL_ESPERADO}')
        for t in PROTECTED:
            actual = con.execute('select * from tags where tag_completo=?', (t,)).fetchone()
            if actual != tuple(prod[t][c] for c in columnas):
                raise SystemExit('Tag manual alterado: ' + t)
        if con.execute('pragma foreign_key_check').fetchall():
            raise SystemExit('foreign_key_check con hallazgos')
        if con.execute('pragma integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('integrity_check falló')
        if args.apply:
            con.execute('COMMIT')
        else:
            con.execute('ROLLBACK')
        print(f'\nPASO 2 {"APLICADO" if args.apply else "DRY-RUN (revertido)"}:'
              f' INSERT {creados} | renombres {renombrados} | metadatos {metidos} | bajas {borrados}'
              f' | auditorías nuevas {nuevas_auditorias}')
    except BaseException as e:
        try:
            con.execute('ROLLBACK')
        except sqlite3.Error:
            pass
        print('ERROR -> ROLLBACK:', type(e).__name__, e)
        raise
    finally:
        try:
            con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except sqlite3.Error:
            pass
        con.close()

    con = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    con.execute('PRAGMA query_only=ON')
    total = con.execute('select count(*) from tags').fetchone()[0]
    integ = con.execute('pragma integrity_check').fetchone()[0]
    fk = con.execute('pragma foreign_key_check').fetchall()
    por_area = con.execute('''select a.codigo, count(*) from tags t join areas a on a.id=t.area_id
                              group by 1 order by 1''').fetchall()
    manuales_ok = all(con.execute('select * from tags where tag_completo=?', (t,)).fetchone()
                      == tuple(prod[t][c] for c in columnas) for t in PROTECTED)
    n_auditoria = con.execute('select count(*) from auditoria').fetchone()[0]
    con.close()
    print('\nPASO 3 (solo lectura)')
    print('  tags:', total, '| integridad:', integ, '| foreign_key_check:', len(fk), 'hallazgos',
          '| 11 manuales intactos:', manuales_ok)
    print('  auditoría:', n_auditoria, 'filas (antes', total_auditoria_pre, ')')
    print('  tags por área:', dict(por_area))
    print('  SHA-256 backup:', digest(BACKUP) if BACKUP.exists() else '(dry-run: no se creó)')
    print('  SHA-256 tags_ingenio.db:', digest(DB))
    print('  residuos -wal/-journal:', [s for s in ('-wal', '-journal')
                                        if (DB.parent / (DB.name + s)).exists()] or 'ninguno')
    if args.apply and (total != TOTAL_ESPERADO or integ != 'ok' or fk or not manuales_ok):
        raise SystemExit('Verificación posterior fallida')
    if not args.apply and digest(DB) != EXPECTED_DB:
        raise SystemExit('El dry-run modificó la base')


if __name__ == '__main__':
    sys.exit(main())
