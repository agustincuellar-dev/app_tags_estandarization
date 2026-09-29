"""Plan maestro v4: cierra lazos y canales definidos por Ingeniería el 29/09.

Etapa separada de v3: lee el CSV v3, conserva cada fila y añade operaciones
nuevas. SQLite en mode=ro + query_only. Cero escrituras.
"""
import csv
import hashlib
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / 'exports'
DB = ROOT / 'app_etiquetas/tags_ingenio.db'
OUT = EX / 'plan_maestro_consolidado_v4_290926.csv'
EXPECTED_DB = 'dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522'
EXPECTED_V3 = '76f2d0e70941f250fc200d77274c9e68224141b35147797b4cf90993774bfa15'
PROTECTED = {'200_PIT_004', '200_PIC_004', '200_PV_004', '200_LT_035', '200_LIC_035',
             '200_LV_035', '200_FT_080', '200_FIC_080', '200_FV_080', '250_PV_001', '250_PV_002'}
EXTRA = ['Evidencia_XML_V4', 'Estado_Verificacion_V4', 'Grupo_V4']
LOOPS = {
    '1': [('300', 'LT', '083', 'DES_S1_LT_TK_DESAIREADOR', '3', 'Calderas_8_9_10_Desaireador'),
          ('300', 'LIC', '083', 'B_DES_LC_DOMO', '2', 'Calderas_8_9_10_Desaireador'),
          ('300', 'LV', '083', 'DES_S6_PV_VALVULA_EVACUACION_DES', '4', 'Calderas_8_9_10_Desaireador'),
          ('200', 'FT', '081', 'Slot_FT_AGUA', '0', 'DESTILERIA'),
          ('200', 'FIC', '081', 'B_Ctrol_FT_AGUA_A_MOSTO', '1', 'DESTILERIA'),
          ('200', 'FV', '081', 'Slot_PV_VALVULA_CAUDAL_AGUA', '2', 'DESTILERIA'),
          ('200', 'LT', '082', 'Slot_LT_TK_AGUA_POTABLE', '7', 'DESTILERIA'),
          ('200', 'LIC', '082', 'B_Ctrol_TK_AGUA_POTABLE', '6', 'DESTILERIA'),
          ('200', 'LV', '082', 'Slot_PV_VALVULA_NIVEL_TK_AGUA', '5', 'DESTILERIA')],
}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(name):
    with (EX / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=';'))


def main():
    before = digest(DB)
    if before != EXPECTED_DB:
        raise RuntimeError('SQLite cambió; no se emite v4')
    if digest(EX / 'plan_maestro_consolidado_v3_290926.csv') != EXPECTED_V3:
        raise RuntimeError('v3 cambió; no se emite v4')
    con = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        if con.execute('PRAGMA query_only').fetchone()[0] != 1:
            raise RuntimeError('query_only no activo')
        prod = {r[0]: r for r in con.execute(
            'SELECT tag_completo,id,plc_origen,COALESCE(descripcion,\'\'),COALESCE(comentarios,\'\') FROM tags')}
        if len(prod) != 196 or not PROTECTED <= prod.keys():
            raise RuntimeError('Base inesperada')
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Integridad rota')
        original = read('plan_maestro_consolidado_v3_290926.csv')
        if len(original) != 616:
            raise RuntimeError('Universo v3 modificado')
        cols = list(original[0])
        if len(cols) != len(set(cols)):
            raise RuntimeError('Columnas v3 duplicadas')
        cols += [c for c in EXTRA if c not in cols]
        rows = []
        for x in original:
            item = dict(x)
            item.update({k: '' for k in EXTRA})
            rows.append(item)

        def add(source, block, old='', new='', area='', var='', number='', func='', file='',
                identity='', address='', status='NO_INSERTAR_REVISION', note='', plc='',
                op='INSERT', evidence='', id_old='', grupo=''):
            x = dict.fromkeys(cols, '')
            x.update({'Fuente_Fila': source, 'Bloque_Maestro': block, 'Operacion_Efectiva': op,
                      'Tag_Origen_Efectivo': old, 'Tag_Destino_Efectivo': new, 'ID_Origen_Efectivo': str(id_old),
                      'Area_Efectiva': area, 'Variable_Efectiva': var, 'Numero_Efectivo': str(number),
                      'Identidad_PLC_Efectiva': identity, 'Direccion_Modulo_Efectiva': address,
                      'Estado_Maestro': status, 'Nota_Maestra': note, 'PLC_Fuente_V2': plc,
                      'Escritura_SQLite': 'NO', 'Evidencia_XML_V4': evidence,
                      'Estado_Verificacion_V4': status, 'Grupo_V4': grupo})
            for k in ('Funcion_ISA', 'Rol'):
                if k in x:
                    x[k] = func
            rows.append(x)
            return x

        def audit(source, block, identity='', address='', plc='', status='REVISION_NO_NUMERAR',
                  note='', evidence='', grupo=''):
            return add(source, block, identity=identity, address=address, plc=plc, status=status,
                       note=note, evidence=evidence, op='', grupo=grupo)

        occupied = defaultdict(set)
        for name in set(prod) | {r['Tag_Destino_Efectivo'] for r in rows} | {r['Tag_Origen_Efectivo'] for r in rows}:
            m = re.fullmatch(r'(\d{3})_[A-Z]+_(\d{3})[A-Z]?', name or '')
            if m:
                occupied[m[1]].add(int(m[2]))

        def free(area):
            for i in range(1, 1000):
                if i not in occupied[area]:
                    occupied[area].add(i)
                    return i
            raise RuntimeError('Sin número libre en ' + area)

        cache = {}

        def xml(plc):
            if plc not in cache:
                path = ROOT / 'L5X_Produccion' / (plc + '.L5X')
                root = ET.parse(path).getroot().find('Controller')
                if root is None or root.get('Name') != plc:
                    raise RuntimeError('XML no corresponde a ' + plc)
                mods = {m.get('Name') for m in root.findall('Modules/Module')}
                alias = {}
                for scope, node in [('Controller', root)] + [('Program:' + p.get('Name'), p)
                                                             for p in root.findall('Programs/Program')]:
                    for t in node.findall('Tags/Tag'):
                        if t.get('AliasFor'):
                            alias[(scope, t.get('Name'))] = t.get('AliasFor')
                cache[plc] = (root, mods, alias)
            return cache[plc]

        def routine(plc, program, name):
            root = xml(plc)[0]
            r = root.find(f"Programs/Program[@Name='{program}']/Routines/Routine[@Name='{name}']")
            if r is None:
                raise RuntimeError(f'Rutina ausente {plc}/{program}/{name}')
            return r

        def edges(rut, pin_from=None, pin_to=None):
            out = []
            for sh in rut.findall('.//Sheet'):
                ns = {n.get('ID'): n for n in sh if n.get('ID')}
                for w in sh.findall('Wire'):
                    a, b = ns.get(w.get('FromID')), ns.get(w.get('ToID'))
                    if a is None or b is None:
                        continue
                    if pin_from is not None and w.get('FromParam') != pin_from:
                        continue
                    if pin_to is not None and w.get('ToParam') != pin_to:
                        continue
                    out.append((a, b, w.get('FromParam'), w.get('ToParam')))
            return out

        def scl_of_channel(plc, address, program_hint=None):
            """Devuelve (alias, bloque, tag interno) del escalado alimentado por el canal."""
            root, mods, alias = xml(plc)
            names = [n for (s, n), a in alias.items() if a == address]
            hits = []
            for pr in root.findall('Programs/Program'):
                for rr in pr.findall('Routines/Routine'):
                    for a, b, fp, tp in edges(rr, pin_to='In'):
                        op = a.get('Operand') or ''
                        if op == address or op in names:
                            outs = [t.get('Operand') for x, t, fp2, tp2 in edges(rr)
                                    if x.get('ID') == b.get('ID') and fp2 == 'Out']
                            hits.append((pr.get('Name'), rr.get('Name'), a.get('Operand'), b.get('Operand'), outs))
            return names, hits

        def forward_tags(rut, block_operand):
            """Etiquetas escritas al seguir las salidas de un bloque por bloques intermedios."""
            out = set()
            visitados = set()
            pendientes = [(block_operand, None)]
            while pendientes:
                nombre, _ = pendientes.pop()
                if nombre in visitados:
                    continue
                visitados.add(nombre)
                for a, b, fp, tp in edges(rut):
                    if a.get('Operand') != nombre or fp is None:
                        continue
                    if b.tag == 'ORef' and (b.get('Operand') or ''):
                        out.add(b.get('Operand'))
                    elif b.tag in ('Block', 'AddOnInstruction') and b.get('Operand'):
                        pendientes.append((b.get('Operand'), None))
            return sorted(out)

        def require_channel_free(plc, address):
            if not re.match(r'^[A-Za-z_0-9]+:', address or ''):
                raise RuntimeError('Dirección sin módulo: ' + address)
            for r in rows:
                if r['Operacion_Efectiva'] and r['Direccion_Modulo_Efectiva'] == address and r['PLC_Fuente_V2'] == plc:
                    raise RuntimeError('Canal ya planificado en v3/v4: ' + address)
            for row in prod.values():
                if address and address in (row[3] or '') + (row[4] or ''):
                    raise RuntimeError('Canal ya en producción: ' + address)

        notes = []

        # ---- 1. Tres familias ya verificadas: comprobar presencia, no reinsertar.
        for area, func, num, ident, rol, plc in LOOPS['1']:
            tag = f'{area}_{func}_{num}'
            if tag not in prod:
                raise RuntimeError('Familia de 3 lazos ausente en producción: ' + tag)
            add('INGENIERIA_3LAZOS_170926', 'LAZO_3LAZOS_YA_EN_PRODUCCION', new=tag, area=area,
                var=func[0] if func != 'LIC' and func != 'FIC' else func[0], number=num, func=func,
                identity=ident, plc=plc, op='', status='YA_EN_PRODUCCION',
                note=f'Ya existe en tags_ingenio.db (id {prod[tag][1]}); no se reinserta ni se renumera',
                evidence=f'propuesta_numeracion_3_lazos.csv; verificado en producción id {prod[tag][1]}',
                grupo='item1_3lazos')
        notes.append('item1: 9/9 tags de propuesta_numeracion_3_lazos.csv ya presentes en producción (0 INSERT nuevos)')

        # ---- 2. Desaireador: área 300 confirmada.
        raiz_cal = xml('Calderas_8_9_10_Desaireador')[0]
        libre = []
        for ch in range(8):
            addr = f'Desaireador:2:I.Ch[{ch}].Data'
            names, hits = scl_of_channel('Calderas_8_9_10_Desaireador', addr)
            s1 = [n for n in names if n.startswith('DES_S1_')]
            s2 = [n for n in names if n.startswith('DES_S2_')]
            if len(s1) != 1:
                raise RuntimeError('Sin una única identidad DES_S1 en ' + addr)
            if not s2:
                raise RuntimeError('Falta el duplicado DES_S2 en ' + addr)
            internos = sorted({o for h in hits if h[2] == s1[0] for o in h[4] if o and not o.startswith('NIVEL_SCL')})
            if (s1[0] == 'DES_S1_LT_TK_DESAIREADOR') or (ch == 6):
                if not internos:
                    raise RuntimeError('Producción sin escalado: ' + addr)
                audit('AUDITORIA_DESAIREADOR_V4', 'DESAIREADOR_CANAL_YA_REPRESENTADO', identity=s1[0], address=addr,
                      plc='Calderas_8_9_10_Desaireador', status='YA_EN_PRODUCCION',
                      note='Canal ya numerado en producción (' + ('300_LT_083' if ch == 4 else '300_PT_042') +
                           '); no se renumera', evidence=f'XML {addr} alias {s1[0]} -> {internos[0]}',
                      grupo='item2_desaireador')
                continue
            if len(internos) != 1:
                raise RuntimeError('Escalado ambiguo en ' + addr + ' ' + str(internos))
            escalado_s2 = [(h[1], h[3], [o for o in h[4] if o]) for h in hits if h[2] == s2[0]]
            libre.append((ch, addr, s1[0], internos[0], s2[0], hits[0], escalado_s2))
        if len(libre) != 6:
            raise RuntimeError('Se esperaban 6 canales libres en Desaireador:2')
        for ch, addr, s1, interno, s2, hit, escalado_s2 in libre:
            num = free('300')
            var, fn = ('P', 'T') if '_PT_' in s1 else ('L', 'T')
            extra = ('; el duplicado ' + s2 + ' también tiene escalado cableado ' + str(escalado_s2) +
                     ': dos lecturas del mismo canal, requiere verificación de campo') if escalado_s2 else \
                    '; el duplicado declarado ' + s2 + ' no tiene salida de escalado cableada (etiqueta muerta)'
            add('AUDITORIA_DESAIREADOR_V4', 'DESAIREADOR_AREA_300', new=f'300_{var}{fn}_{num:03d}', area='300',
                var=var, func=fn, number=num, identity=s1, address=addr, plc='Calderas_8_9_10_Desaireador',
                note='Área 300 confirmada por Ingeniería; identidad tomada del alias y del escalado de ' + s1 +
                     ' con duplicado ' + s2 + ' declarado sobre el mismo canal, consolidado en trazabilidad (no se numera)',
                evidence=f'Calderas_8_9_10_Desaireador.L5X {hit[0]}/{hit[1]}: {addr} -> {s1}.In -> {interno}' + extra,
                grupo='item2_desaireador')
        notes.append('item2: 6 canales libres de Desaireador:2 numerados en área 300; 2 canales ya en producción')

        # Desaireador:3 y salidas: conflicto alias vs lógica, sin número.
        for ch in range(8):
            addr = f'Desaireador:3:I.Ch[{ch}].Data'
            names, hits = scl_of_channel('Calderas_8_9_10_Desaireador', addr)
            variantes = sorted({(h[3], tuple(o for o in h[4] if o)) for h in hits})
            audit('AUDITORIA_DESAIREADOR_V4', 'DESAIREADOR_CONFLICTO_SIN_NUMERO', identity=names[0] if names else addr,
                  address=addr, plc='Calderas_8_9_10_Desaireador', status='CANAL_CONFLICTO_ALIAS_VS_LOGICA',
                  note='Área 300 confirmada, sin número: el alias declarado (' + (names[0] if names else 'ninguno') +
                       ') y el bloque de escalado no coinciden en variable ni función',
                  evidence=f'XML {addr}; alias {names}; escalados {variantes}', grupo='item2_desaireador')
        for ident, addr in (('DES_S5_SI_BBA_1', 'Desaireador:5:O.Ch0Data'),
                            ('DES_S6_PV_VALVULA_EVACUACION_DES', 'Desaireador:6:O.Ch4Data'),
                            ('LIT_102_CALDERA_11', 'Desaireador:6:O.Ch7Data')):
            audit('AUDITORIA_DESAIREADOR_V4', 'DESAIREADOR_SALIDA_SIN_NUMERO', identity=ident, address=addr,
                  plc='Calderas_8_9_10_Desaireador', status='SALIDA_NO_INSTRUMENTO_SIN_NUMERO',
                  note='Área 300 confirmada por Ingeniería; canal de salida (comando) — no se numera como sensor',
                  evidence='XML Calderas_8_9_10_Desaireador.L5X alias ' + ident + ' -> ' + addr,
                  grupo='item2_desaireador')
        # Desaireador_2: TK 20 / agua de pozo -> 300 según la excepción confirmada.
        for addr, esperado, var in (('Desaireador_2:2:I.Ch[0].Data', 'DES_2_S2_IT_BBA_11_REP_TK_20_NORTE', 'I'),
                                    ('Desaireador_2:2:I.Ch[1].Data', 'DES_2_S2_ST_BBA_11_REP_TK_20_NORTE', 'S'),
                                    ('Desaireador_2:2:I.Ch[2].Data', 'DES_2_S2_IT_BBA_12_REP_TK_20_SUR', 'I'),
                                    ('Desaireador_2:2:I.Ch[3].Data', 'DES_2_S2_ST_BBA_12_REP_TK_20_SUR', 'S'),
                                    ('Desaireador_2:3:I.Ch[0].Data', 'DES_2_S3_LT_TK_AGUA_DE_POZO', 'L')):
            names, hits = scl_of_channel('Calderas_8_9_10_Desaireador', addr)
            if names != [esperado] or len(hits) != 1 or not hits[0][4]:
                raise RuntimeError('Cadena Desaireador_2 no demostrada: ' + addr)
            require_channel_free('Calderas_8_9_10_Desaireador', addr)
            num = free('300')
            add('AUDITORIA_DESAIREADOR_V4', 'DESAIREADOR_2_REPOSICION_TK20', new=f'300_{var}T_{num:03d}', area='300',
                var=var, func='T', number=num, identity=esperado, address=addr,
                plc='Calderas_8_9_10_Desaireador',
                note='Área 300 por la excepción de Ingeniería (agua de pozo / reposición TK 20). '
                     'Los tanques de alcohol y agua destilería del mismo adaptador siguen en área 200 (propuestas v2)',
                evidence=f'Calderas_8_9_10_Desaireador.L5X {hits[0][0]}/{hits[0][1]}: {addr} -> {esperado}.In -> '
                         f'{hits[0][4][0]}', grupo='item2_desaireador')
        notes.append('item2: Desaireador:3 (8 canales) y salidas: área 300 confirmada, SIN número por conflicto')
        notes.append('item2: Desaireador_2 TK20/pozo: 5 canales numerados en área 300 (excepción de Ingeniería)')

        # ---- 3. Domos de calderas 8, 9 y 10.
        domos = [('C8', 'BP_ANALOGICA:1:I.Ch[2].Data', 'BP_ANALOGICA:1:I.Ch[3].Data', 'B_C8_LT_DOMO_NORTE',
                  'B_C8_LT_DOMO_SUR', 'C8_LT_DOMO_NORTE', 'C8_LT_DOMO_SUR', 'B_C8_LC_DOMO',
                  'BP_ANALOGICA:10:O.Ch3Data', 'C8_FT_VAPOR'),
                 ('C9', 'BP_ANALOGICA:2:I.Ch[2].Data', 'BP_ANALOGICA:2:I.Ch[3].Data', 'B_C9_LT_DOMO_NORTE',
                  'B_C9_LT_DOMO_SUR', 'C9_LT_DOMO_NORTE', 'C9_LT_DOMO_SUR', 'B_C9_LC_DOMO',
                  'BP_ANALOGICA:11:O.Ch5Data', 'C9_FT_VAPOR'),
                 ('C10', 'BP_ANALOGICA:4:I.Ch[1].Data', 'BP_ANALOGICA:3:I.Ch[3].Data', 'B_C10_LT_DOMO_NORTE',
                  'B_C10_LT_DOMO_SUR', 'C10_LT_DOMO_NORTE', 'C10_LT_DOMO_SUR', 'B_C10_LC_DOMO',
                  'BP_ANALOGICA:12:O.Ch2Data', 'C10_FT_VAPOR')]
        for prog, chn, chs, blkn, blks, intern, inters, ctrl, salida, ft in domos:
            escala = routine('Calderas_8_9_10_Desaireador', prog, f'{prog}_S1_ESCALADO_AI')
            pares = {(a.get('Operand'), b.get('Operand')) for a, b, fp, tp in edges(escala, pin_to='In')}
            for ch, blk in ((chn, blkn), (chs, blks)):
                if (ch, blk) not in pares:
                    raise RuntimeError(f'Domo {prog}: {ch} no alimenta {blk}.In')
            if (blkn, intern) not in {(a.get('Operand'), b.get('Operand')) for a, b, fp, tp in edges(escala) if fp == 'Out'}:
                raise RuntimeError(f'Domo {prog}: {blkn} no escribe {intern}')
            rb = routine('Calderas_8_9_10_Desaireador', prog, f'{prog}_LC_DOMO')
            e = edges(rb)
            if not (any(a.get('Operand') == intern and b.get('Type') == 'SEL' for a, b, fp, tp in e)
                    and any(a.get('Operand') == inters and b.get('Type') == 'SEL' for a, b, fp, tp in e)):
                raise RuntimeError(f'Domo {prog}: los dos LT no entran al selector')
            if not any(b.get('Operand') == ctrl for a, b, fp, tp in e if tp == 'PV'):
                raise RuntimeError(f'Domo {prog}: SEL no alimenta PV')
            if not any(a.get('Operand') == ctrl and b.get('Operand') == salida for a, b, fp, tp in e):
                raise RuntimeError(f'Domo {prog}: MV no llega a {salida}')
            for ch in (chn, chs, salida):
                require_channel_free('Calderas_8_9_10_Desaireador', ch)
            num = free('300')
            ev = (f'Calderas_8_9_10_Desaireador.L5X {prog}/{prog}_S1_ESCALADO_AI + {prog}_LC_DOMO: '
                  f'{chn}->{blkn}.In y {chs}->{blks}.In; ambos LT al selector -> PV de {ctrl}; '
                  f'{ctrl}.MV -> {salida}; caudales auxiliares {ft}')
            add('INGENIERIA_DOMOS_290926', 'DOMO_CALDERA_CERRADO', new=f'300_LT_{num:03d}A', area='300', var='L',
                func='T', number=num, identity=blkn, address=chn, plc='Calderas_8_9_10_Desaireador',
                note='Dos mediciones de nivel del domo sobre el mismo lazo; sufijo A = NORTE', evidence=ev,
                grupo='item3_domos')
            add('INGENIERIA_DOMOS_290926', 'DOMO_CALDERA_CERRADO', new=f'300_LT_{num:03d}B', area='300', var='L',
                func='T', number=num, identity=blks, address=chs, plc='Calderas_8_9_10_Desaireador',
                note='Sufijo B = SUR; misma numeración de lazo que A', evidence=ev, grupo='item3_domos')
            add('INGENIERIA_DOMOS_290926', 'DOMO_CALDERA_CERRADO', new=f'300_LIC_{num:03d}', area='300', var='L',
                func='IC', number=num, identity=ctrl, address='', plc='Calderas_8_9_10_Desaireador',
                note='PV por selector de los dos LT; MV a la salida de agua de alimentación', evidence=ev,
                grupo='item3_domos')
            add('INGENIERIA_DOMOS_290926', 'DOMO_CALDERA_CERRADO', new=f'300_LV_{num:03d}', area='300', var='L',
                func='V', number=num, identity=salida, address=salida, plc='Calderas_8_9_10_Desaireador',
                note='Función LV designada por Ingeniería; el XML demuestra el canal MV, no el tipo de '
                     'elemento final en campo', evidence=ev, grupo='item3_domos')
        notes.append('item3: 3 lazos de domo cerrados (12 tags) en área 300')

        # 3b. Completar lazos 046 y 047 del evaporador.
        pid_evap = routine('DESTILERIA', 'EVAPORADOR', 'PID_EVAPORADOR')
        for inst, salida in (('PID_CONTROL_NIVEL_1ER_EFECTO', 'EVAPORADOR:6:O.Ch0Data'),
                             ('PID_CONTROL_QUIEBRE_VACIO', 'EVAPORADOR:6:O.Ch2Data')):
            if not any(a.get('Operand') == inst and b.get('Operand') == salida for a, b, fp, tp in edges(pid_evap)):
                raise RuntimeError('Salida no demostrada para ' + inst)
            require_channel_free('DESTILERIA', salida)
        add('INGENIERIA_EVAP_290926', 'LAZO_046_047_COMPLETADO', new='200_LV_046', area='200', var='L', func='V',
            number='046', identity='PID_CONTROL_NIVEL_1ER_EFECTO.MV_VALV_NC', address='EVAPORADOR:6:O.Ch0Data',
            plc='DESTILERIA', note='Completa el lazo 046 (200_LT_046 / 200_LIC_046 ya propuestos); '
            'MV_VALV_NC es pin lógico: el tipo de elemento final requiere confirmación de campo',
            evidence='DESTILERIA.L5X EVAPORADOR/PID_EVAPORADOR: PID_CONTROL_NIVEL_1ER_EFECTO.MV_VALV_NC -> '
                     'EVAPORADOR:6:O.Ch0Data', grupo='item3_evaporador')
        add('INGENIERIA_EVAP_290926', 'LAZO_046_047_COMPLETADO', new='200_PV_047', area='200', var='P', func='V',
            number='047', identity='PID_CONTROL_QUIEBRE_VACIO.MV_VALV_NA', address='EVAPORADOR:6:O.Ch2Data',
            plc='DESTILERIA', note='Completa el lazo 047 (200_PT_047 / 200_PIC_047 ya propuestos); '
            'MV_VALV_NA es pin lógico: confirmar elemento final',
            evidence='DESTILERIA.L5X EVAPORADOR/PID_EVAPORADOR: PID_CONTROL_QUIEBRE_VACIO.MV_VALV_NA -> '
                     'EVAPORADOR:6:O.Ch2Data', grupo='item3_evaporador')

        # 3c. Tanque de condensado: LT + controlador + dos variadores.
        esc = routine('DESTILERIA', 'EVAPORADOR', 'ESCALADOS_PT_FT_LT_TT')
        if not any((a.get('Operand') or '') == 'EVAPORADOR:2:I.Ch1Data' and b.get('Operand') == 'B_LT_TK_CONDENSADO'
                   for a, b, fp, tp in edges(esc, pin_to='In')):
            raise RuntimeError('LT_TK_CONDENSADO sin cadena')
        if not any(a.get('Operand') == 'B_LT_TK_CONDENSADO' and b.get('Operand') == 'LT_TK_CONDENSADO'
                   and fp == 'Out' for a, b, fp, tp in edges(esc)):
            raise RuntimeError('Primera PV de LT_TK_CONDENSADO no probada')
        arm = routine('DESTILERIA', 'EVAPORADOR', 'ARRANQUE_MOTORES')
        ea = edges(arm)
        if not any(a.get('Operand') == 'PID_CONTROL_NIVEL_TK_CONDENSADO.MV_VALV_NC' and b.get('Operand') in ('SCL_09', 'SCL_10')
                   for a, b, fp, tp in ea):
            raise RuntimeError('MV del lazo de condensado sin escalados')
        if not (any(a.get('Operand') == 'SCL_09' and b.get('Operand') == 'SEL_06' for a, b, fp, tp in ea)
                and any(a.get('Operand') == 'SEL_06' and b.get('Operand') == 'BBA_CONDENSADO_ESTE:O.Reference' for a, b, fp, tp in ea)
                and any(a.get('Operand') == 'SCL_10' and b.get('Operand') == 'SEL_07' for a, b, fp, tp in ea)
                and any(a.get('Operand') == 'SEL_07' and b.get('Operand') == 'BBA_CONDENSADO_OESTE:O.Reference' for a, b, fp, tp in ea)):
            raise RuntimeError('Salidas a variadores del lazo de condensado no probadas')
        for ch in ('EVAPORADOR:2:I.Ch1Data', 'BBA_CONDENSADO_ESTE:O.Reference', 'BBA_CONDENSADO_OESTE:O.Reference'):
            require_channel_free('DESTILERIA', ch)
        if not any(b.get('Operand') == 'PID_CONTROL_NIVEL_TK_CONDENSADO' for a, b, fp, tp in edges(pid_evap) if tp == 'PV'):
            raise RuntimeError('PV del lazo de condensado no cableada')
        num_c = free('200')
        ev = ('DESTILERIA.L5X EVAPORADOR/ESCALADOS_PT_FT_LT_TT: EVAPORADOR:2:I.Ch1Data -> B_LT_TK_CONDENSADO.In -> '
              'LT_TK_CONDENSADO -> PID_CONTROL_NIVEL_TK_CONDENSADO.PV; ARRANQUE_MOTORES: MV_VALV_NC -> SCL_09/SCL_10 -> '
              'SEL_06/SEL_07 -> BBA_CONDENSADO_ESTE/OESTE:O.Reference (cada selector alterna con la referencia del arranque)')
        for fn, ident, ch, nota in (('LT', 'LT_TK_CONDENSADO', 'EVAPORADOR:2:I.Ch1Data', 'Primera PV tras el escalado'),
                                    ('LIC', 'PID_CONTROL_NIVEL_TK_CONDENSADO', '', 'Controlador del lazo'),
                                    ('LY', 'BBA_CONDENSADO_ESTE', 'BBA_CONDENSADO_ESTE:O.Reference',
                                     'Función Y: elemento final motor/variador (regla R-A); rama A'),
                                    ('LY', 'BBA_CONDENSADO_OESTE', 'BBA_CONDENSADO_OESTE:O.Reference',
                                     'Función Y: elemento final motor/variador (regla R-A); rama B')):
            suf = '' if fn in ('LT', 'LIC') else ('A' if ident.endswith('_ESTE') else 'B')
            add('INGENIERIA_EVAP_290926', 'LAZO_CONDENSADO_CERRADO', new=f'200_{fn}_{num_c:03d}{suf}', area='200',
                var='L', func=fn, number=num_c, identity=ident, address=ch, plc='DESTILERIA',
                note=nota + '; la salida de cada variador se selecciona con la referencia del arranque, no es exclusiva del PID',
                evidence=ev, grupo='item3_evaporador')
        notes.append(f'item3: lazo de tanque de condensado cerrado con 200_{num_c:03d} (LT, LIC, LY A/B)')

        # 3d. Cajas condensadoras 6 y 7/8: un número, sensor y salida compartidos.
        fab = xml('FABRICA')[0]
        rutc = routine('FABRICA', 'FAB_EVAP', 'EVAP_LC_COND_C_6_7_8')
        ec = edges(rutc)
        if not (any(a.get('Operand') == 'B_LC_COND_CAJA_6.MV_VALV_NC' and b.get('Operand') == 'SEL_08' for a, b, fp, tp in ec)
                and any(a.get('Operand') == 'B_LC_COND_CAJA_7_8.MV_VALV_NC' and b.get('Operand') == 'SEL_08' for a, b, fp, tp in ec)
                and any(a.get('Operand') == 'SEL_08' and b.get('Operand') == 'EVAP_S14_LCV_COND_CAJA_6_7_8' for a, b, fp, tp in ec)):
            raise RuntimeError('SEL_08 de cajas condensadoras no demostrado')
        alias_fab = {}
        for scope, node in [('Controller', fab)] + [('Program:' + p.get('Name'), p) for p in fab.findall('Programs/Program')]:
            for t in node.findall('Tags/Tag'):
                if t.get('AliasFor'):
                    alias_fab[(scope, t.get('Name'))] = t.get('AliasFor')
        if alias_fab.get(('Controller', 'EVAP_S14_LCV_COND_CAJA_6_7_8')) != 'ISLA_FAB_AI:14:O.Ch[5].Data' or \
           alias_fab.get(('Controller', 'EVAP_S5_LT_CAJA_6_7_8_COND')) != 'ISLA_FAB_AI:5:I.Ch[0].Data':
            raise RuntimeError('Alias de cajas condensadoras cambiados')
        for ch in ('ISLA_FAB_AI:5:I.Ch[0].Data', 'ISLA_FAB_AI:14:O.Ch[5].Data'):
            require_channel_free('FABRICA', ch)
        num_k = free('500')
        ev = ('FABRICA.L5X FAB_EVAP/EVAP_LC_COND_C_6_7_8: B_LC_COND_CAJA_6.MV_VALV_NC -> SEL_08.In1 y '
              'B_LC_COND_CAJA_7_8.MV_VALV_NC -> SEL_08.In2; SEL_08.Out -> EVAP_S14_LCV_COND_CAJA_6_7_8 '
              '(AliasFor ISLA_FAB_AI:14:O.Ch[5].Data). Entrada compartida EVAP_S5_LT_CAJA_6_7_8_COND -> '
              'ISLA_FAB_AI:5:I.Ch[0].Data')
        for fn, ident, ch, nota in (('LT', 'EVAP_S5_LT_CAJA_6_7_8_COND', 'ISLA_FAB_AI:5:I.Ch[0].Data',
                                     'Un único transmisor para las dos cajas; número base sin sufijo'),
                                    ('LIC', 'B_LC_COND_CAJA_6', '', 'Rama A del lazo'),
                                    ('LIC', 'B_LC_COND_CAJA_7_8', '', 'Rama B del lazo'),
                                    ('LXV', 'EVAP_S14_LCV_COND_CAJA_6_7_8', 'ISLA_FAB_AI:14:O.Ch[5].Data',
                                     'Salida común tras el selector; tipo de válvula por designación de Ingeniería')):
            suf = 'A' if ident == 'B_LC_COND_CAJA_6' else ('B' if ident == 'B_LC_COND_CAJA_7_8' else '')
            add('INGENIERIA_CAJAS_COND_290926', 'LAZO_CAJAS_COND_CERRADO', new=f'500_{fn}_{num_k:03d}{suf}',
                area='500', var='L', func=fn, number=num_k, identity=ident, address=ch, plc='FABRICA',
                note=nota, evidence=ev, grupo='item3_cajas_cond')
        notes.append(f'item3: lazo de cajas condensadoras 6 / 7-8 cerrado con 500_{num_k:03d}')

        # ---- 4. Canales libres de los dos grupos v3.
        item4 = [('Calderas_8_9_10_Desaireador', 'Calderas_8_9_10_Desaireador', 'C8', 'C8_S1_ESCALADO_AI',
                  'BP_ANALOGICA:1:I.Ch[1].Data', 'B_C8_FT_VAPOR', 'C8_FT_VAPOR', '300', 'F', 'C8_FT_VAPOR_REAL',
                  'Caudal de vapor C8; consolida C8_FT_VAPOR_REAL y CAUDAL_VAPOR_C8_DIA_ANT'),
                 ('Calderas_8_9_10_Desaireador', 'Calderas_8_9_10_Desaireador', 'C9', 'C9_S1_ESCALADO_AI',
                  'BP_ANALOGICA:2:I.Ch[1].Data', 'B_C9_FT_VAPOR', 'C9_FT_VAPOR', '300', 'F', 'C9_FT_VAPOR_REAL',
                  'Caudal de vapor C9; consolida C9_FT_VAPOR_REAL y CAUDAL_VAPOR_C9_DIA_ANT'),
                 ('Calderas_8_9_10_Desaireador', 'Calderas_8_9_10_Desaireador', 'C10', 'C10_S1_ESCALADO_AI',
                  'BP_ANALOGICA:3:I.Ch[1].Data', 'B_C10_FT_VAPOR', 'C10_FT_VAPOR', '300', 'F', 'C10_FT_VAPOR_REAL',
                  'Caudal de vapor C10; consolida C10_FT_VAPOR_REAL y CAUDAL_VAPOR_C10_DIA_ANT'),
                 ('Calderas_8_9_10_Desaireador', 'Calderas_8_9_10_Desaireador', 'C9', 'C9_S1_ESCALADO_AI',
                  'BP_ANALOGICA:2:I.Ch[6].Data', 'B_C9_TT_HOGAR_SUR', 'C9_TT_HOGAR_SUR', '300', 'T', 'C9_TT_HOGAR_SUR',
                  'Temperatura de hogar sur C9')]
        for _, plc, prog, rut, addr, blk, interno, area, var, ident, nota in item4:
            esc = routine(plc, prog, rut)
            entra = [(a, b, fp, tp) for a, b, fp, tp in edges(esc)
                     if (a.get('Operand') or '') == addr and b.get('Operand') == blk and tp in ('In', 'PV', 'In1')]
            if not entra:
                raise RuntimeError(f'{blk} no alimentado por {addr}')
            pin = entra[0][3]
            if not any(b.get('Operand') == interno for a, b, fp, tp in edges(esc) if a.get('Operand') == blk and fp == 'Out'):
                if interno not in forward_tags(esc, blk):
                    raise RuntimeError(f'{blk} no escribe {interno}')
            require_channel_free(plc, addr)
            num = free(area)
            add('INGENIERIA_CANALES_LIBRES_V4', 'CANAL_FISICO_UNICO_300', new=f'300_{var}T_{num:03d}', area=area,
                var=var, func='T', number=num, identity=interno, address=addr, plc=plc, note=nota,
                evidence=f'{plc}.L5X {prog}/{rut}: {addr} -> {blk}.{pin} -> {interno}', grupo='item4_canales')

        dest4 = [('DESTILERIA', 'FERMENTACION', 'ESCALADOS_PT_FT_LT_TT', 'jw_fermerntacion_2022:4:I.Ch0Data',
                  'B_ZT_VIBRACION_CENTRIFUGA_5', 'VIBRACION_CENTRIFUGA_5', 'V', 'Vibración de centrífuga 5. '
                  'El alias de canal declarado es Slot_LT_PRE_FERMENTADOR_1 y el mismo canal alimenta B_LT_PF_1 (LT_PRE_FERMENTADOR_1): '
                  'la identidad de vibración proviene del escalado, requiere confirmación de campo'),
                 ('DESTILERIA', 'EVAPORADOR', 'ESCALADOS_PT_FT_LT_TT', 'EVAPORADOR:2:I.Ch4Data',
                  'B_LT_TK_FLASH', 'LT_TK_FLASH_A', 'L', 'Nivel del tanque flash (medición A); '
                  'PID_CONTROL_NIVEL_TK_FLASH toma PV de un selector de A y B (SEL_02)'),
                 ('DESTILERIA', 'EVAPORADOR', 'ESCALADOS_PT_FT_LT_TT', 'EVAPORADOR:2:I.Ch5Data',
                  'B_LT_TK_FLASH_B', 'LT_TK_FLASH_B', 'L', 'Nivel del tanque flash (medición B); mismo controlador que A'),
                 ('DESTILERIA', 'FERMENTACION', 'ESCALADOS_PT_FT_LT_TT', 'jw_fermerntacion_2022:6:I.Ch[4].Data',
                  'B_FT_DENSIDAD_MELADO', 'DENSIDAD_MELADO_TRATADO', 'D', 'Densidad de melado tratado (primera salida del escalado); '
                  'el mismo canal tiene alias Slot_FT_MOSTO y ALCOHOL_HIDRATADO_TC205 declarados: identidad en conflicto'),
                 ('DESTILERIA', 'FERMENTACION', 'ESCALADOS_PT_FT_LT_TT', 'jw_fermerntacion_2022:3:I.Ch7Data',
                  'B_FT_DENSIDAD_MELADO1', 'DENSIDAD_MOSTO', 'D', 'Densidad de mosto (primera salida del escalado); '
                  'el alias de canal declarado es Slot_LT_CALICANTO_1: variable en conflicto'),
                 ('DESTILERIA', 'JW', 'ESCLADOS_PT_FT_LT_TT', 'fermerntacion2022_islas:3:I.Ch[2].Data',
                  'SCL_LT_CONDENSADO_BL101', 'LT_CONDENSADO_BL101', 'L', 'Nivel del condensado BL101; '
                  'el histórico lo ubicaba en área 300 y aquí se numera en 200 por pertenecer al PLC de Destilería'),
                 ('DESTILERIA', 'JW', 'ESCLADOS_PT_FT_LT_TT', 'fermerntacion2022_islas:5:I.Ch1Data',
                  'ALM_TT_108', '', 'T', 'Temperatura de entrada a condensadores: el canal alimenta directamente '
                  'el bloque de alarma ALM_TT_108, sin bloque de escalado; la identidad proviene del nombre del '
                  'bloque y requiere confirmación de campo')]
        for plc, prog, rut, addr, blk, interno, var, nota in dest4:
            esc = routine(plc, prog, rut)
            if not any((a.get('Operand') or '') == addr and b.get('Operand') == blk for a, b, fp, tp in
                       edges(esc, pin_to='In')):
                raise RuntimeError(f'{blk} no alimentado por {addr}')
            if interno and not any(b.get('Operand') == interno for a, b, fp, tp in edges(esc)
                                   if a.get('Operand') == blk and fp == 'Out'):
                if interno not in forward_tags(esc, blk):
                    raise RuntimeError(f'{blk} no escribe {interno}')
            require_channel_free(plc, addr)
            num = free('200')
            add('INGENIERIA_CANALES_LIBRES_V4', 'CANAL_FISICO_UNICO_200', new=f'200_{var}T_{num:03d}', area='200',
                var=var, func='T', number=num, identity=interno, address=addr, plc=plc, note=nota,
                evidence=f'{plc}.L5X {prog}/{rut}: {addr} -> {blk}.In' +
                         (f' -> {interno}' if interno else ' (bloque de alarma, sin escalado)'),
                grupo='item4_canales')

        # Canales con identidad sólo declarada (alias de campo) o no consumida en FBD.
        decl = [('DESTILERIA', 'jw_fermerntacion_2022:6:I.Ch[6].Data', 'Slot_FT_VINO_A_JW', '200', 'F', 'T',
                 'Caudalímetro de vino a JW: alias de campo declarado sin escalado ni consumo localizado en la lógica'),
                ('DESTILERIA', 'jw_fermerntacion_2022:10:O.Ch3Data', 'Slot_PV_VALVULA_CAUDAL_LECHADA', '200', 'F', 'V',
                 'Válvula de caudal de lechada: alias de salida declarado sin consumo localizado; '
                 'función FV por designación del alias')]
        for plc, addr, ident, area, var, func, nota in decl:
            root, mods, alias = xml(plc)
            if (('Controller', ident) not in alias) or alias[('Controller', ident)] != addr:
                raise RuntimeError('Alias no declarado exactamente: ' + ident)
            require_channel_free(plc, addr)
            num = free(area)
            add('INGENIERIA_CANALES_LIBRES_V4', 'CANAL_FISICO_UNICO_200', new=f'{area}_{var}{func}_{num:03d}',
                area=area, var=var, func=func, number=num, identity=ident,
                address=addr, plc=plc, note=nota,
                evidence=f'{plc}.L5X declaración Controller.{ident} AliasFor {addr}', grupo='item4_canales')

        # ---- Excluidos documentados (sin número).
        for ident, addr, motivo in (
                ('TT_ENTRADA_CAL_VINO', 'jw_fermerntacion_2022:2:I.Ch4Data',
                 'El canal tiene alias declarado Slot_ST_CENTRIFUGA_5 y el escalado B_ST_CENTRIFUGA_5 escribe ST_CENTRIFUGA_5 '
                 '(velocidad); el nombre del bloque de alarma sugiere temperatura. Variable no demostrable'),
                ('TT_ENTRADA_ENF_ALCOHOL', 'jw_fermerntacion_2022:2:I.Ch2Data',
                 'El canal tiene alias declarado Slot_ST_CENTRIFUGA_3 y el escalado B_ST_CENTRIFUGA_3 escribe ST_CENTRIFUGA_3 '
                 '(velocidad); el bloque de alarma sugiere temperatura. Variable no demostrable')):
            audit('AUDITORIA_CANALES_V4', 'CANAL_CONFLICTO_VARIABLE', identity=ident, address=addr, plc='DESTILERIA',
                  status='CANAL_CONFLICTO_VARIABLE', note=motivo,
                  evidence='DESTILERIA.L5X: alias Slot_ST_CENTRIFUGA_3/5 y escalados B_ST_CENTRIFUGA_3/5 sobre el mismo canal',
                  grupo='item4_canales')
        for ident, addr, motivo in (
                ('DES_TT_DESAEREADOR', 'Desaireador:3:I.Ch[7].Data',
                 'Mismo canal que DES_S3_IT_BBA_7 (corriente) mientras el escalado SCL_08 escribe una temperatura: variable en conflicto'),
                ('IT_DES_ARRANQUE_BBA_TK_1000_BACKUP', 'Desaireador:3:I.Ch[4].Data',
                 'Mismo canal que DES_S3_IT_BBA_3; el escalado asociado no tiene salida cableada: variable no demostrable')):
            audit('AUDITORIA_CANALES_V4', 'CANAL_CONFLICTO_VARIABLE', identity=ident, address=addr,
                  plc='Calderas_8_9_10_Desaireador', status='CANAL_CONFLICTO_VARIABLE', note=motivo,
                  evidence='XML Calderas_8_9_10_Desaireador.L5X escalados DES_S3_ESCALADO_AI/DES_S4_ESCALADO_AI',
                  grupo='item4_canales')
        for ident, addr in (('FT_AGUA', 'jw_fermerntacion_2022:6:I.Ch[0].Data'),
                            ('FT_MELAZA_TN_H', 'jw_fermerntacion_2022:6:I.Ch[3].Data'),
                            ('FT_MOSTO_PROM_24_HR', 'jw_fermerntacion_2022:5:I.Ch[2].Data')):
            audit('AUDITORIA_CANALES_V4', 'CANAL_YA_NUMERADO', identity=ident, address=addr, plc='DESTILERIA',
                  status='CANAL_YA_REPRESENTADO', note='Canal ya numerado en producción o en el plan: no se duplica',
                  evidence='200_FT_081 / 200_FT_086 / 200_FT_035 sobre el mismo canal físico', grupo='item4_canales')

        # ---- 5. Centrífuga de primera: área 700 confirmada.
        cent = xml('CENTRIFUGA_DE_PRIMERA')[0]
        if 'VDF755TR_CENT1' not in {m.get('Name') for m in cent.findall('Modules/Module')} or \
           'Remota_Weidmuller' not in {m.get('Name') for m in cent.findall('Modules/Module')}:
            raise RuntimeError('Módulos de centrífuga no declarados')
        e_esc = edges(routine('CENTRIFUGA_DE_PRIMERA', 'MainProgram', 'Escalado'))
        if not any(a.get('Operand') == 'VDF755TR_CENT1:I.P10_OutputFrequency' and b.get('Operand') == 'SCL_49'
                   for a, b, fp, tp in e_esc) or \
           not any(a.get('Operand') == 'SCL_49' and b.get('Operand') == 'rpm_VDF_motor' for a, b, fp, tp in e_esc):
            raise RuntimeError('rpm_VDF_motor no demostrado')
        e_def = edges(routine('CENTRIFUGA_DE_PRIMERA', 'MainProgram', 'Definicion_de_senales_analogicas'))
        if not (any(a.get('Operand') == 'Remota_Weidmuller:I.Data[2]' and b.get('Operand') == 'B_CONCATENADO_01' for a, b, fp, tp in e_def)
                and any(a.get('Operand') == 'Remota_Weidmuller:I.Data[3]' and b.get('Operand') == 'B_CONCATENADO_01' for a, b, fp, tp in e_def)
                and any(a.get('Operand') == 'B_CONCATENADO_01' and b.get('Operand') == 'SCL_27' for a, b, fp, tp in e_def)
                and any(a.get('Operand') == 'SCL_27' and b.get('Operand') == 'Velocidad_4_20mA' for a, b, fp, tp in e_def)):
            raise RuntimeError('Velocidad_4_20mA no demostrada')
        e_arm = edges(routine('CENTRIFUGA_DE_PRIMERA', 'MainProgram', 'ARRANQUE_MOTOR'))
        if not any(a.get('Operand') == 'Velocidad_4_20mA' and b.get('Operand') == 'SCL_25' for a, b, fp, tp in e_arm) or \
           not any(a.get('Operand') == 'SCL_25' and b.get('Operand') == 'rpm_Real_motor' for a, b, fp, tp in e_arm):
            raise RuntimeError('rpm_Real_motor no demostrado')
        lx7 = xml('CENTRIFUGA_DE_PRIMERA')[1] if False else None
        for ch in ('Remota_Weidmuller:I.Data[2]', 'Remota_Weidmuller:I.Data[3]', 'VDF755TR_CENT1:I.P10_OutputFrequency'):
            require_channel_free('CENTRIFUGA_DE_PRIMERA', ch)
        num7a = free('700')
        add('INGENIERIA_CENTRIFUGA_290926', 'CENTRIFUGA_AREA_700', new=f'700_ST_{num7a:03d}', area='700', var='S',
            func='T', number=num7a, identity='rpm_Real_motor / Velocidad_4_20mA',
            address='Remota_Weidmuller:I.Data[2] + Data[3]', plc='CENTRIFUGA_DE_PRIMERA',
            note='Una sola señal de velocidad por canal físico: los dos enteros remotos forman un único valor (B_CONCATENADO_01). '
                 'Consolida rpm_Real_motor y Velocidad_4_20mA',
            evidence='CENTRIFUGA_DE_PRIMERA.L5X MainProgram/Definicion_de_senales_analogicas: Remota_Weidmuller:I.Data[2] y [3] '
                     '-> B_CONCATENADO_01.OutPut_entero -> SCL_27.In -> Velocidad_4_20mA; ARRANQUE_MOTOR: Velocidad_4_20mA -> '
                     'SCL_25.In -> rpm_Real_motor -> rpm_int_motor', grupo='item5_centrifuga')
        num7b = free('700')
        add('INGENIERIA_CENTRIFUGA_290926', 'CENTRIFUGA_AREA_700', new=f'700_ST_{num7b:03d}', area='700', var='S',
            func='T', number=num7b, identity='rpm_VDF_motor', address='VDF755TR_CENT1:I.P10_OutputFrequency',
            plc='CENTRIFUGA_DE_PRIMERA',
            note='Miembro del variador VDF755TR_CENT1 (parámetro del equipo), no un transmisor de campo: se numera por '
                 'indicación de Ingeniería y queda en revisión',
            evidence='CENTRIFUGA_DE_PRIMERA.L5X MainProgram/Escalado: VDF755TR_CENT1:I.P10_OutputFrequency -> SCL_49.In -> '
                     'rpm_VDF_motor (y SUB_02 con rpm_int_motor)', grupo='item5_centrifuga')
        for ident, motivo in (('CORRIENTE_CARGA_C2', 'Sin declaración exacta (PLC, alcance, nombre) en el L5X de producción'),
                              ('RPM_motor1', 'Valor interno derivado; sin canal físico propio demostrado'),
                              ('Diferencia_relativa_entre_velocidades', 'Cálculo derivado de dos velocidades; no es instrumento')):
            audit('AUDITORIA_CENTRIFUGA_V4', 'CENTRIFUGA_SIN_NUMERO', identity=ident, plc='CENTRIFUGA_DE_PRIMERA',
                  status='SIN_CANAL_O_DERIVADO', note=motivo, evidence='CENTRIFUGA_DE_PRIMERA.L5X', grupo='item5_centrifuga')
        for i, ch in enumerate(('Local:2:I.Ch00.Data', 'Local:2:I.Ch01.Data', 'Local:2:I.Ch02.Data',
                                'Local:2:I.Ch03.Data', 'Local:2:I.Ch04.Data')):
            audit('AUDITORIA_CENTRIFUGA_V4', 'CENTRIFUGA_IDENTIFICADO_SIN_AUTORIZACION', identity=f'CORRIENTE_CARGA_C{i + 2}',
                  address=ch, plc='CENTRIFUGA_DE_PRIMERA', status='IDENTIFICADO_SIN_AUTORIZACION',
                  note='Canal analógico de corriente de carga de centrífuga C' + str(i + 2) +
                       ' identificado pero fuera del alcance autorizado de esta corrida (sólo VDF755TR_CENT1 y Remota_Weidmuller)',
                  evidence='CENTRIFUGA_DE_PRIMERA.L5X ARRANQUE_MOTOR: comentarios "CORRIENTE DE CARGA C2..C6-input" y IRef ' + ch,
                  grupo='item5_centrifuga')
        for i, ch in enumerate(('Remota_Weidmuller:I.Data[4]', 'Remota_Weidmuller:I.Data[5]',
                                'Remota_Weidmuller:I.Data[6]', 'Remota_Weidmuller:I.Data[7]',
                                'Remota_Weidmuller:I.Data[8]', 'Remota_Weidmuller:I.Data[9]')):
            audit('AUDITORIA_CENTRIFUGA_V4', 'CENTRIFUGA_IDENTIFICADO_SIN_AUTORIZACION',
                  identity=f'B_CONCATENADO_0{2 + i // 2}', address=ch, plc='CENTRIFUGA_DE_PRIMERA',
                  status='ESCALADO_SIN_CONSUMIDOR',
                  note='Par de enteros remotos que alimenta un escalado cuyo Out no está cableado: sin identidad ni consumidor',
                  evidence='CENTRIFUGA_DE_PRIMERA.L5X Definicion_de_senales_analogicas: SCL_28/29/30 sin salida cableada',
                  grupo='item5_centrifuga')

        # ---- Estados heredados de v3 que este lote cierra o reubica.
        resueltos = {'DES_S1_LT_TK_INOXIDABLE', 'DES_S1_LT_TK_20', 'DES_S1_PT_DESAIREADOR', 'DES_S1_LT_TK_1000',
                     'DES_S1_PT_VALVULA_20_10', 'DES_S1_PT_COLECTOR_AGUA_A_CALDERA',
                     'DES_S2_ST_BBA_1', 'DES_S2_ST_BBA_2', 'DES_S2_ST_BBA_3', 'DES_S2_ST_BBA_4',
                     'DES_S2_ST_BBA_5', 'DES_S2_ST_BBA_6', 'DES_S2_ST_BBA_8',
                     'DES_2_S2_IT_BBA_11_REP_TK_20_NORTE', 'DES_2_S2_ST_BBA_11_REP_TK_20_NORTE',
                     'DES_2_S2_IT_BBA_12_REP_TK_20_SUR', 'DES_2_S2_ST_BBA_12_REP_TK_20_SUR',
                     'DES_2_S3_LT_TK_AGUA_DE_POZO', 'DES_S1_LT_TK_DESAIREADOR', 'DES_S1_PT_VALVULA_10_0',
                     'DES_S6_PV_VALVULA_10_0', 'DES_S6_PV_VALVULA_20_10', 'DES_S6_PV_VALVULA_EVACUACION_DES',
                     'LIT_102_CALDERA_11',
                     'B_C8_LC_DOMO', 'B_C9_LC_DOMO', 'B_C10_LC_DOMO', 'PID_CONTROL_NIVEL_1ER_EFECTO',
                     'PID_CONTROL_QUIEBRE_VACIO', 'PID_CONTROL_NIVEL_TK_CONDENSADO', 'B_LC_COND_CAJA_6',
                     'B_LC_COND_CAJA_7_8',
                     'VIBRACION_CENTRIFUGA_5', 'LT_TK_CONDENSADO', 'LT_TK_FLASH_A', 'LT_TK_FLASH_B',
                     'DENSIDAD_MELADO_TRATADO', 'DENSIDAD_MOSTO', 'LT_CONDENSADO_BL101',
                     'TT_108_ENTRADA_CONDENSADORES', 'TT_ENTRADA_CAL_VINO', 'TT_ENTRADA_ENF_ALCOHOL',
                     'C8_FT_VAPOR_REAL', 'CAUDAL_VAPOR_C8_DIA_ANT', 'C9_FT_VAPOR_REAL', 'CAUDAL_VAPOR_C9_DIA_ANT',
                     'C10_FT_VAPOR_REAL', 'CAUDAL_VAPOR_C10_DIA_ANT', 'C9_TT_HOGAR_SUR', 'DES_TT_DESAEREADOR',
                     'IT_DES_ARRANQUE_BBA_TK_1000_BACKUP', 'DES_LT_TK_20', 'Slot_FT_VINO_A_JW',
                     'Slot_PV_VALVULA_CAUDAL_LECHADA', 'Slot_FT_AGUA', 'Slot_FT_MELAZA', 'Slot_FT_MOSTO',
                     'CORRIENTE_CARGA_C2', 'Diferencia_relativa_entre_velocidades', 'RPM_motor1', 'rpm_VDF_motor',
                     'DES_S3_IT_BBA_1', 'DES_S3_IT_BBA_2', 'DES_S3_IT_BBA_3', 'DES_S3_IT_BBA_4', 'DES_S3_IT_BBA_6',
                     'DES_S3_IT_BBA_7', 'DES_S3_ST_BBA_9', 'DES_S3_ST_BBA_10'}
        tocados = 0
        for r in rows[:616]:
            if r['Estado_Auditoria_V3'] in ('AREA_MULTISECTOR_NO_CONFIRMADA', 'INTERNO_ESCALADO_PENDIENTE_EXCLUSIVIDAD',
                                            'ALIAS_FISICO_SIN_LAZO_O_AREA') and r['Identidad_PLC_Efectiva'] in resueltos:
                r['Estado_Maestro'] = 'REVISADO_EN_V4'
                r['Nota_Maestra'] += '; revisado en v4: ver filas Grupo_V4=' + (
                    'item2_desaireador' if r['Identidad_PLC_Efectiva'].startswith('DES') else 'item4_canales')
                r['Estado_Auditoria_V3'] = 'REVISADO_EN_V4'
                tocados += 1
            elif r['Estado_Auditoria_V3'] == 'SIN_LAZO_COMPLETO' and r['Identidad_PLC_Efectiva'] in (
                    'B_C8_LC_DOMO', 'B_C9_LC_DOMO', 'B_C10_LC_DOMO', 'PID_CONTROL_NIVEL_TK_CONDENSADO',
                    'B_LC_COND_CAJA_6', 'B_LC_COND_CAJA_7_8'):
                r['Estado_Maestro'] = 'CERRADO_EN_V4'
                r['Nota_Maestra'] += '; cerrado en v4 (ver filas Grupo_V4=item3_*)'
                r['Estado_Auditoria_V3'] = 'CERRADO_EN_V4'
                tocados += 1
        notes.append(f'filas heredadas de v3 actualizadas: {tocados}')

        # ---- Verificación final.
        ops = [r for r in rows if r['Operacion_Efectiva'] in ('INSERT', 'UPDATE', 'DELETE')]
        dests = defaultdict(list)
        origins = defaultdict(list)
        for r in ops:
            op, old, new = r['Operacion_Efectiva'], r['Tag_Origen_Efectivo'], r['Tag_Destino_Efectivo']
            if old in PROTECTED or new in PROTECTED:
                raise RuntimeError('Tag manual protegido tocado')
            if op in ('UPDATE', 'DELETE'):
                if old not in prod or str(prod[old][1]) != r['ID_Origen_Efectivo']:
                    raise RuntimeError('Origen inválido ' + old)
                origins[old].append(r)
            if op in ('INSERT', 'UPDATE'):
                if not re.fullmatch(r'\d{3}_[A-Z]+_\d{3}[A-Z]?', new or ''):
                    raise RuntimeError('Tag inválido ' + new)
                dests[new].append(r)
        if any(len(v) != 1 for v in origins.values()):
            raise RuntimeError('Origen repetido: ' + str([k for k, v in origins.items() if len(v) != 1]))
        if any(len(v) != 1 for v in dests.values()):
            raise RuntimeError('Destino repetido: ' + str([k for k, v in dests.items() if len(v) != 1]))
        if any(t in prod and t not in origins for t in dests):
            raise RuntimeError('Destino ocupado por fila de producción')
        pares = defaultdict(set)
        for r in ops:
            if r['Bloque_Maestro'] not in ('DOMO_CALDERA_CERRADO', 'LAZO_CAJAS_COND_CERRADO',
                                           'LAZO_CONDENSADO_CERRADO'):
                continue
            m = re.fullmatch(r'(\d{3})_[A-Z]+_(\d{3})[A-Z]?', r['Tag_Destino_Efectivo'])
            if not m:
                raise RuntimeError('Miembro de lazo con forma inesperada: ' + r['Tag_Destino_Efectivo'])
            pares[(m[1], m[2])].add(r['Tag_Destino_Efectivo'])
        esperados = {'DOMO': {'LT': 2, 'LIC': 1, 'LV': 1}, 'CONDENSADO': {'LT': 1, 'LIC': 1, 'LY': 2},
                     'CAJAS': {'LT': 1, 'LIC': 2, 'LXV': 1}}
        if len(pares) != 5 or any(len(v) != 4 for v in pares.values()):
            raise RuntimeError('Grupos de lazo inesperados: ' + str({k: sorted(v) for k, v in pares.items()}))
        for (area, num), miembros in pares.items():
            cuenta = Counter(m.split('_')[1] for m in miembros)
            forma = next((k for k, v in esperados.items() if v == dict(cuenta)), None)
            if forma is None:
                raise RuntimeError(f'Lazo {area}_{num} con miembros inesperados: ' + str(sorted(miembros)))
            dup = [f for f, n in cuenta.items() if n == 2]
            if forma == 'DOMO' and dup != ['LT']:
                raise RuntimeError('Domo sin dos transmisores: ' + str(sorted(miembros)))
            if forma == 'DOMO' and {m[-1] for m in miembros if m.startswith(f'{area}_LT_')} != {'A', 'B'}:
                raise RuntimeError('Domo sin sufijos A/B: ' + str(sorted(miembros)))
            if forma == 'CONDENSADO' and dup != ['LY']:
                raise RuntimeError('Lazo de condensado sin dos salidas: ' + str(sorted(miembros)))
            if forma == 'CAJAS' and dup != ['LIC']:
                raise RuntimeError('Lazo de cajas sin dos controladores: ' + str(sorted(miembros)))
            if forma == 'CAJAS' and {m[-1] for m in miembros if m.startswith(f'{area}_LIC_')} != {'A', 'B'}:
                raise RuntimeError('Cajas sin sufijos A/B: ' + str(sorted(miembros)))
        if digest(DB) != before:
            raise RuntimeError('SQLite cambió antes de emitir')
        with OUT.open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, cols, delimiter=';', lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
        parsed = read('plan_maestro_consolidado_v4_290926.csv')
        if parsed != rows or any(r['Escritura_SQLite'] != 'NO' for r in parsed):
            raise RuntimeError('CSV inválido')
        counts = Counter(r['Operacion_Efectiva'] for r in parsed)
        nuevos = [r for r in parsed[616:] if r['Operacion_Efectiva'] == 'INSERT']
        print('BLOQUES V4:', dict(Counter(r['Grupo_V4'] for r in nuevos)))
        print('OPERACIONES nuevas:', counts['INSERT'] - 233, 'INSERT;', counts['UPDATE'] - 43, 'UPDATE;',
              counts['DELETE'] - 12, 'DELETE')
        for n in notes:
            print('  -', n)
        print('BALANCE INSERT', counts['INSERT'], 'UPDATE', counts['UPDATE'], 'DELETE', counts['DELETE'],
              'TOTAL PROYECTADO', 196 + counts['INSERT'] - counts['DELETE'])
        print('CSV filas', len(parsed), 'SHA-256', digest(OUT))
        print('DB', len(prod), 'SHA-256 antes/después', before, digest(DB), 'mode=ro query_only=ON; cero escrituras SQLite')
        if digest(DB) != before:
            raise RuntimeError('SQLite cambió después de emitir')
    finally:
        con.close()


if __name__ == '__main__':
    main()
