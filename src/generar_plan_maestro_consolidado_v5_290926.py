"""Plan maestro v5: cierra las 4 autorizaciones de Ingeniería del 29/09.

Etapa separada de v4. Lee el CSV v4, conserva cada fila y aplica las
numeraciones y homologaciones autorizadas. SQLite en mode=ro + query_only.
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
OUT = EX / 'plan_maestro_consolidado_v5_290926.csv'
EXPECTED_DB = 'dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522'
EXPECTED_V4 = 'dae9a6ee1b8d959e73c4ecff559ef5e08923b11b6982f6786e623ba352ad62d0'
PROTECTED = {'200_PIT_004', '200_PIC_004', '200_PV_004', '200_LT_035', '200_LIC_035',
             '200_LV_035', '200_FT_080', '200_FIC_080', '200_FV_080', '250_PV_001', '250_PV_002'}
EXTRA = ['Evidencia_XML_V5', 'Estado_Verificacion_V5', 'Grupo_V5', 'Estado_Homologacion_V5']
HOMOLOGADOS = ('NO_INSERTAR_REVISION', 'UPDATE_METADATOS_NO_RENOMBRAR')


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
        raise RuntimeError('SQLite cambió; no se emite v5')
    if digest(EX / 'plan_maestro_consolidado_v4_290926.csv') != EXPECTED_V4:
        raise RuntimeError('v4 cambió; no se emite v5')
    con = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        if con.execute('PRAGMA query_only').fetchone()[0] != 1:
            raise RuntimeError('query_only no activo')
        prod = {r[0]: r[1] for r in con.execute('SELECT tag_completo,id FROM tags')}
        if len(prod) != 196 or not PROTECTED <= prod.keys():
            raise RuntimeError('Base inesperada')
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Integridad rota')
        original = read('plan_maestro_consolidado_v4_290926.csv')
        if len(original) != 707:
            raise RuntimeError('Universo v4 modificado')
        cols = list(original[0])
        if len(cols) != len(set(cols)):
            raise RuntimeError('Columnas v4 duplicadas')
        cols += [c for c in EXTRA if c not in cols]
        rows = []
        for x in original:
            item = dict(x)
            item.update({k: '' for k in EXTRA})
            rows.append(item)

        def add(source, block, old='', new='', area='', var='', number='', func='', identity='',
                address='', status='NO_INSERTAR_REVISION', note='', plc='', op='INSERT',
                evidence='', id_old='', grupo=''):
            x = dict.fromkeys(cols, '')
            x.update({'Fuente_Fila': source, 'Bloque_Maestro': block, 'Operacion_Efectiva': op,
                      'Tag_Origen_Efectivo': old, 'Tag_Destino_Efectivo': new,
                      'ID_Origen_Efectivo': str(id_old), 'Area_Efectiva': area, 'Variable_Efectiva': var,
                      'Numero_Efectivo': str(number), 'Identidad_PLC_Efectiva': identity,
                      'Direccion_Modulo_Efectiva': address, 'Estado_Maestro': status,
                      'Nota_Maestra': note, 'PLC_Fuente_V2': plc, 'Escritura_SQLite': 'NO',
                      'Evidencia_XML_V5': evidence, 'Estado_Verificacion_V5': status, 'Grupo_V5': grupo})
            rows.append(x)
            return x

        occupied = defaultdict(set)
        for name in set(prod) | {r['Tag_Destino_Efectivo'] for r in rows} | {r['Tag_Origen_Efectivo'] for r in rows}:
            m = re.fullmatch(r'(\d{3})_[A-Z]+_(\d{3})[A-Z]?', name or '')
            if m:
                occupied[m[1]].add(int(m[2]))

        def tomar(area, numero):
            if numero in occupied[area]:
                raise RuntimeError(f'Número ya ocupado: {area}_{numero:03d}')
            occupied[area].add(numero)
            return numero

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
                alias = {}
                for scope, node in [('Controller', root)] + [('Program:' + p.get('Name'), p)
                                                             for p in root.findall('Programs/Program')]:
                    for t in node.findall('Tags/Tag'):
                        if t.get('AliasFor'):
                            alias[(scope, t.get('Name'))] = t.get('AliasFor')
                cache[plc] = (root, alias)
            return cache[plc]

        def routine(plc, program, name):
            r = xml(plc)[0].find(f"Programs/Program[@Name='{program}']/Routines/Routine[@Name='{name}']")
            if r is None:
                raise RuntimeError(f'Rutina ausente {plc}/{program}/{name}')
            return r

        def edges(rut):
            out = []
            for sh in rut.findall('.//Sheet'):
                ns = {n.get('ID'): n for n in sh if n.get('ID')}
                for w in sh.findall('Wire'):
                    a, b = ns.get(w.get('FromID')), ns.get(w.get('ToID'))
                    if a is not None and b is not None:
                        out.append((a, b, w.get('FromParam'), w.get('ToParam')))
            return out

        def require_free(plc, address):
            for r in rows:
                if r['Operacion_Efectiva'] and r['Direccion_Modulo_Efectiva'] == address and r['PLC_Fuente_V2'] == plc:
                    raise RuntimeError('Canal ya planificado: ' + address)

        notas = []

        # ---- 1. Cinco corrientes de carga de centrífugas C2..C6.
        cent = routine('CENTRIFUGA_DE_PRIMERA', 'MainProgram', 'ARRANQUE_MOTOR')
        canales = [('Local:2:I.Ch00.Data', 'CORRIENTE_CARGA_C2', 'SCL_65', 'Corriente_carga_C2', 'SCL_66', 'CORRIENTE_C2_AMP'),
                   ('Local:2:I.Ch01.Data', 'CORRIENTE_CARGA_C3', 'SCL_67', 'Corriente_carga_C3', 'SCL_68', 'CORRIENTE_C3_AMP'),
                   ('Local:2:I.Ch02.Data', 'CORRIENTE_CARGA_C4', 'SCL_69', 'Corriente_carga_C4', 'SCL_70', 'CORRIENTE_C4_AMP'),
                   ('Local:2:I.Ch03.Data', 'CORRIENTE_CARGA_C5', 'SCL_71', 'Corriente_carga_C5', 'SCL_72', None),
                   ('Local:2:I.Ch04.Data', 'CORRIENTE_CARGA_C6', 'SCL_73', 'Corriente_carga_C6', 'SCL_74', None)]
        e_cent = edges(cent)
        desvios = []
        for i, (ch, ident, scl, destino, scl2, destino2) in enumerate(canales):
            if not any(a.get('Operand') == ch and b.get('Operand') == scl for a, b, fp, tp in e_cent) or \
               not any(a.get('Operand') == scl and b.get('Operand') == destino for a, b, fp, tp in e_cent):
                raise RuntimeError(f'Cadena de corriente no demostrada: {ch}')
            if not any((a.get('Operand') == ch and b.get('Operand') == scl2) or
                       (a.get('Operand') == scl and b.get('Operand') == scl2) for a, b, fp, tp in e_cent):
                raise RuntimeError(f'Segundo escalado no demostrado: {ch}')
            require_free('CENTRIFUGA_DE_PRIMERA', ch)
            pedido = 5 + i
            if pedido in occupied['700']:
                numero = free('700')
                desvios.append((f'700_IT_{pedido:03d}', f'700_IT_{numero:03d}'))
                nota_extra = (f'; el número autorizado 700_IT_{pedido:03d} ya está ocupado en producción por el lazo '
                              f'B_PC_10_5/B_PC_20_10, por lo que se asignó el siguiente libre 700_IT_{numero:03d}; '
                              'decisión a confirmar por Ingeniería')
            else:
                numero = tomar('700', pedido)
                nota_extra = ''
            add('INGENIERIA_CORRIENTES_CENTRIFUGA_V5', 'CORRIENTES_CARGA_CENTRIFUGA', new=f'700_IT_{numero:03d}',
                area='700', var='I', func='T', number=numero, identity=ident, address=ch,
                plc='CENTRIFUGA_DE_PRIMERA',
                note='Área 700 y numeración autorizadas por Ingeniería; canal analógico de corriente de carga. '
                     'El segundo escalado del mismo canal es una representación en amperios, no otro instrumento' + nota_extra,
                evidence=f'CENTRIFUGA_DE_PRIMERA.L5X MainProgram/ARRANQUE_MOTOR: {ch} -> {scl}.In -> {destino}' +
                         (f' y {scl2}.In -> {destino2}' if destino2 else f' y {scl2}.In (sin salida cableada)'),
                grupo='item1_corrientes')
        notas.append('item1: corrientes C2-C4 numeradas 700_IT_005/006/007. Colisiones con la autorización: ' +
                     ('; '.join(f'{a} estaba ocupado (lazo B_PC_10_5 en 008 / B_PC_20_10 en 009), se usó {b}'
                                for a, b in desvios) if desvios else 'ninguna'))

        # ---- 2. Desaireador:3 por lógica viva cableada.
        cal = xml('Calderas_8_9_10_Desaireador')[0]
        planes = [
            (0, 'DES_S3_ST_BBA_9', 'DES/des_S3_ESCALADO_AI', 'DES_S3_ESCALADO_AI', 'SCL_16', 'DES_ST_BBA_9', 'S',
             'Velocidad: el escalado vivo escribe DES_ST_BBA_9 (4-20 mA -> 4..2985 rpm)'),
            (2, 'DES_S3_IT_BBA_1', 'DES/DES_S3_ESCALADO_AI', 'DES_S3_ESCALADO_AI', 'B_DES_IT_BBA_1', '', 'I',
             'Corriente: el bloque vivo procesa el alias (4-20 mA -> 0..100 %) pero no tiene salida cableada'),
            (3, 'DES_S3_IT_BBA_2', 'DES/DES_CORRIENTE_BBA', 'DES_CORRIENTE_BBA', 'B_DES_IT_BBA_7', '', 'I',
             'Corriente: el bloque vivo se llama B_DES_IT_BBA_7 y toma el canal crudo (4-20 mA -> 0..100 %), sin '
             'salida cableada; el alias declarado numera 2 en lugar de 7: ambos nombres quedan en trazabilidad'),
            (4, 'DES_S3_IT_BBA_3', 'DES/DES_S3_ESCALADO_AI', 'DES_S3_ESCALADO_AI', 'MUL_05', 'IT_DES_ARRANQUE_BBA_TK_1000_BACKUP',
             'I', 'Corriente: MUL_05 (x2.56) -> SCL_14 -> IT_DES_ARRANQUE_BBA_TK_1000_BACKUP (0..81 A)'),
            (6, 'DES_S3_IT_BBA_6', 'DES/DES_S1_ESCALADO_AI', 'DES_S1_ESCALADO_AI', 'B_DES_LT_TK_1001', 'DES_LT_TK2_1000',
             'L', 'Nivel: el único bloque vivo que lee el canal escribe DES_LT_TK2_1000; no es I, S ni T, se numera con '
             'la variable que demuestra la lógica'),
            (7, 'DES_S3_IT_BBA_7', 'DES/DES_S4_ESCALADO_AI', 'DES_S4_ESCALADO_AI', 'SCL_08', 'DES_TT_DESAEREADOR', 'T',
             'Temperatura: SCL_08 escribe DES_TT_DESAEREADOR (4-20 mA -> 0..200 °C)')]
        for ch, alias_des, _, prog, bloque, destino, var, motivo in planes:
            addr = f'Desaireador:3:I.Ch[{ch}].Data'
            rut = routine('Calderas_8_9_10_Desaireador', 'DES', prog.split('/')[-1])
            e = edges(rut)
            entra = [x for x in e if x[1].get('Operand') == bloque and
                     (x[0].get('Operand') == addr or x[0].get('Operand') == alias_des)]
            if not entra:
                raise RuntimeError(f'{bloque} no lee {addr}')
            if destino:
                if not any(a.get('Operand') in (bloque, 'SCL_14', 'MUL_05') and b.get('Operand') == destino
                           for a, b, fp, tp in e) and destino not in {b.get('Operand') for a, b, fp, tp in e}:
                    raise RuntimeError(f'{bloque} no escribe {destino}')
            require_free('Calderas_8_9_10_Desaireador', addr)
            numero = free('300')
            add('INGENIERIA_DESAIREADOR3_V5', 'DESAIREADOR_3_LOGICA_VIVA', new=f'300_{var}T_{numero:03d}', area='300',
                var=var, func='T', number=numero, identity=destino or alias_des, address=addr,
                plc='Calderas_8_9_10_Desaireador',
                note=f'{motivo}. Alias declarado en el controlador: {alias_des}; bloque vivo: {prog}/{bloque}; '
                     f'destino escrito: {destino or "(ninguno)"}. Ambos nombres quedan para inspección en planta',
                evidence=f'Calderas_8_9_10_Desaireador.L5X {prog}: {addr}' +
                         (f' y alias {alias_des}' if alias_des != addr else '') +
                         f' -> {bloque}.In' + (f' -> {destino}' if destino else ' (sin ORef)'),
                grupo='item2_desaireador3')
        # Canales 1 y 5: sin bloque vivo / doble escritura contradictoria.
        e3 = edges(routine('Calderas_8_9_10_Desaireador', 'DES', 'DES_S3_ESCALADO_AI'))
        e2 = edges(routine('Calderas_8_9_10_Desaireador', 'DES', 'DES_S2_ESCALADO_AI'))
        if any(a.get('Operand') == 'Desaireador:3:I.Ch[1].Data' for a, b, fp, tp in e3 + e2):
            raise RuntimeError('Ch[1] tiene consumidor; revisar')
        if not (any(a.get('Operand') == 'Desaireador:3:I.Ch[5].Data' and b.get('Operand') == 'SCL_15' for a, b, fp, tp in e3)
                and any(a.get('Operand') == 'Desaireador:3:I.Ch[5].Data' and b.get('Operand') == 'SCL_19' for a, b, fp, tp in e2)):
            raise RuntimeError('Doble escritura de Ch[5] no demostrada')
        add('INGENIERIA_DESAIREADOR3_V5', 'DESAIREADOR_3_SIN_NUMERO', identity='DES_S3_ST_BBA_10',
            address='Desaireador:3:I.Ch[1].Data', plc='Calderas_8_9_10_Desaireador', op='',
            status='SIN_BLOQUE_VIVO', note='El alias declarado no se usa en ninguna rutina y ningún bloque lee el canal: '
            'sin variable ni destino demostrable, no se numera',
            evidence='Calderas_8_9_10_Desaireador.L5X DES_S3_ESCALADO_AI / DES_CORRIENTE_BBA: sin IRef del canal ni del alias',
            grupo='item2_desaireador3')
        add('INGENIERIA_DESAIREADOR3_V5', 'DESAIREADOR_3_SIN_NUMERO', identity='DES_S3_IT_BBA_4',
            address='Desaireador:3:I.Ch[5].Data', plc='Calderas_8_9_10_Desaireador', op='',
            status='DOBLE_ESCRITURA_CONTRADICTORIA', note='El canal alimenta dos bloques vivos con destinos de distinta '
            'magnitud: SCL_15 -> ST_DES_ARRANQUE_BBA_TK_1000_BACKUP (velocidad, 0..1500) y SCL_19 -> TEMP_CCM_DES '
            '(temperatura, 0..150 °C). No se elige variable sin verificación de campo',
            evidence='Calderas_8_9_10_Desaireador.L5X DES_S3_ESCALADO_AI SCL_15 y DES_S2_ESCALADO_AI SCL_19 sobre el mismo canal',
            grupo='item2_desaireador3')
        notas.append('item2: 6 de 8 canales de Desaireador:3 numerados; Ch[1] sin bloque vivo y Ch[5] con doble escritura contradictoria')

        # ---- 3. Par entrada + controlador de caja 11.
        fab = xml('FABRICA')
        if fab[1].get(('Controller', 'EVAP_S4_LT_CAJA_11')) != 'ISLA_FAB_AI:4:I.Ch[2].Data':
            raise RuntimeError('Alias de caja 11 cambiado')
        esc4 = routine('FABRICA', 'FAB_ESCALADOS', 'FAB_S4_ESCALADO_AI')
        e4 = edges(esc4)
        if not (any(a.get('Operand') == 'EVAP_S4_LT_CAJA_11' and b.get('Operand') == 'LPF_03' for a, b, fp, tp in e4)
                and any(a.get('Operand') == 'LPF_03' and b.get('Operand') == 'B_LT_CAJA_11' for a, b, fp, tp in e4)
                and any(a.get('Operand') == 'B_LT_CAJA_11' and b.get('Operand') == 'EVAP_LT_C11' for a, b, fp, tp in e4)):
            raise RuntimeError('Cadena EVAP_LT_C11 no demostrada')
        e5 = edges(routine('FABRICA', 'FAB_EVAP', 'EVAP_LC_C11'))
        if not any(a.get('Operand') == '\\FAB_ESCALADOS.EVAP_LT_C11' and b.get('Operand') == 'B_LC_CAJA_11' for a, b, fp, tp in e5):
            raise RuntimeError('PV de B_LC_CAJA_11 no cableada al escalado')
        e6 = edges(routine('FABRICA', 'FAB_EVAP', 'EVAP_LC_5TO_EFECTO'))
        if not (any(a.get('Operand') == 'B_LC_CAJA_11.MV_VALV_NC' and b.get('Operand') == 'SEL_02' for a, b, fp, tp in e6)
                and any(a.get('Operand') == 'B_LC_CAJA_9_10.MV_VALV_NC' and b.get('Operand') == 'SEL_02' for a, b, fp, tp in e6)
                and any(a.get('Operand') == 'SEL_02' and b.get('Operand') == 'EVAP_S2_FCV_MELADO_EVAP_BBA_NORTE' for a, b, fp, tp in e6)):
            raise RuntimeError('Compartición de SEL_02 no demostrada')
        require_free('FABRICA', 'ISLA_FAB_AI:4:I.Ch[2].Data')
        ev3 = ('FABRICA.L5X FAB_ESCALADOS/FAB_S4_ESCALADO_AI: EVAP_S4_LT_CAJA_11 (AliasFor ISLA_FAB_AI:4:I.Ch[2].Data) '
               '-> LPF_03 -> B_LT_CAJA_11 -> EVAP_LT_C11; FAB_EVAP/EVAP_LC_C11: PV <- \\FAB_ESCALADOS.EVAP_LT_C11; '
               'FAB_EVAP/EVAP_LC_5TO_EFECTO: B_LC_CAJA_11.MV_VALV_NC -> SEL_02.In2 junto con B_LC_CAJA_9_10.MV_VALV_NC '
               '-> SEL_02.In1, y SEL_02.Out alimenta EVAP_S2_FCV_MELADO_EVAP_BBA_NORTE/SUR y JUGO_CLARO:O.Data[11]/[9]')
        tomar('500', 4)
        add('INGENIERIA_CAJA11_V5', 'PAR_ENTRADA_CONTROLADOR_CAJA_11', new='500_LT_004', area='500', var='L',
            func='T', number=4, identity='EVAP_S4_LT_CAJA_11', address='ISLA_FAB_AI:4:I.Ch[2].Data', plc='FABRICA',
            note='Mismo criterio que el par de B_LC_CAJA_6 (500_LT_002 / 500_LIC_002)',
            evidence=ev3, grupo='item3_caja_11')
        add('INGENIERIA_CAJA11_V5', 'PAR_ENTRADA_CONTROLADOR_CAJA_11', new='500_LIC_004', area='500', var='L',
            func='IC', number=4, identity='B_LC_CAJA_11', address='', plc='FABRICA',
            note='Par entrada + controlador; su salida NO es exclusiva: entra a SEL_02 compartido con B_LC_CAJA_9_10 '
                 'y el selector escribe los dos caudales de melado y dos bits de JUGO_CLARO',
            evidence=ev3, grupo='item3_caja_11')
        notas.append('item3: par de caja 11 numerado como 500_LT_004 / 500_LIC_004 con la compartición de SEL_02 documentada')

        # ---- 4. Homologación de las tres salidas en revisión.
        homolog = {'700_LXV_001': ('700_LY_001', 'CONTROL_NIVEL_TK_MIEL1',
                                  'Homologado con 700_LY_012 (CONTROL_NIVEL_TK_MIEL_2, salidas a variadores WEG_MIEL): '
                                  'la salida de TK_MIEL1 se trata como mando de motor/accionamiento',
                                  'FABRICA.L5X FAB_ESCALADOS/AGITADORES_JUGO_DESTIL_PID: CONTROL_NIVEL_TK_MIEL1 '
                                  'ID49 MV_VALV_NC -> ORef ID37 FLEX5000_MIELES:2:O.Ch00.Data; homologación por '
                                  'Ingeniería con 700_LY_012'),
                   '700_PV_002': (None, 'B_PID_VAL_20_10_AUX_1',
                                  'Discrepancia de alias conservada: EVAP_S13_LCD_MELADO_5TO_EFE (el alias apunta a '
                                  'melado de 5º efecto, no a presión de vapor de escape); verificar el dispositivo en campo',
                                  'FABRICA.L5X FAB_CCV/CCV_PC_ALTA_ESCAPE ORef 22 ISLA_FAB_AI:13:O.Ch[6].Data con alias '
                                  'exacto EVAP_S13_LCD_MELADO_5TO_EFE'),
                   '400_PV_004': (None, 'B_PID_VAL_20_10_AUX_2',
                                  'Discrepancia de alias conservada: Slot3_PV_VAL_CTROL_LT_J_ENCALADO (el alias apunta a '
                                  'una válvula de nivel de jugo encalado, variable L, no a presión); verificar el '
                                  'dispositivo en campo',
                                  'FABRICA.L5X FAB_CCV/CCV_PC_ALTA_ESCAPE ORef 23 SULFO_ENCALADO:8:O.Ch7Data con alias '
                                  'exacto Slot3_PV_VAL_CTROL_LT_J_ENCALADO')}
        for viejo, (nuevo, inst, nota, ev) in homolog.items():
            destino = [r for r in rows[:len(original)] if r['Tag_Destino_Efectivo'] == viejo and
                       r['Estado_Maestro'] in ('REVISION_ACTUADOR_NO_CONFIRMADO', 'REVISION_VARIABLE_CONFLICTO')]
            if len(destino) != 1:
                raise RuntimeError('Fila en revisión ausente: ' + viejo)
            r = destino[0]
            if nuevo:
                if nuevo in occupied[r['Area_Efectiva']]:
                    raise RuntimeError('Número ocupado al renombrar: ' + nuevo)
                occupied[r['Area_Efectiva']].add(int(nuevo[-3:]))
                r['Tag_Destino_Efectivo'] = nuevo
                r['Numero_Efectivo'] = str(int(nuevo[-3:]))
            r['Estado_Maestro'] = 'NO_INSERTAR_REVISION'
            r['Estado_Verificacion_V5'] = 'NO_INSERTAR_REVISION'
            r['Grupo_V5'] = 'item4_homologacion'
            r['Evidencia_XML_V5'] = ev
            r['Nota_Maestra'] = r['Nota_Maestra'] + '; ' + nota
            if nuevo and nuevo != r['Tag_Destino_Efectivo']:
                raise RuntimeError('Renombre inconsistente ' + viejo)
        for clave in ('EVAP_S13_LCD_MELADO_5TO_EFE', 'Slot3_PV_VAL_CTROL_LT_J_ENCALADO', '700_LY_012'):
            if not any(clave in (r['Nota_Maestra'] or '') for r in rows):
                raise RuntimeError('Advertencia ausente en Nota_Maestra: ' + clave)
        notas.append('item4: 700_LXV_001 -> 700_LY_001 y las dos salidas PV pasaron a NO_INSERTAR_REVISION conservando la advertencia de alias')

        # ---- Estados heredados que este lote resuelve.
        resueltos_des3 = {f'Desaireador:3:I.Ch[{i}].Data' for i in range(8)}
        for r in rows[:len(original)]:
            if r['Estado_Verificacion_V4'] == 'CANAL_CONFLICTO_ALIAS_VS_LOGICA' and r['Direccion_Modulo_Efectiva'] in resueltos_des3:
                r['Estado_Maestro'] = 'REVISADO_EN_V5'
                r['Estado_Auditoria_V3'] = 'REVISADO_EN_V5'
            if r['Estado_Verificacion_V4'] == 'IDENTIFICADO_SIN_AUTORIZACION' and r['Direccion_Modulo_Efectiva'] in {
                    'Local:2:I.Ch00.Data', 'Local:2:I.Ch01.Data', 'Local:2:I.Ch02.Data', 'Local:2:I.Ch03.Data',
                    'Local:2:I.Ch04.Data'}:
                r['Estado_Maestro'] = 'NUMERADO_EN_V5'
                r['Estado_Auditoria_V3'] = 'NUMERADO_EN_V5'
            if r['Estado_Verificacion_V4'] == 'SIN_LAZO_COMPLETO' and r['Identidad_PLC_Efectiva'] == 'B_LC_CAJA_11':
                r['Estado_Maestro'] = 'PAR_NUMERADO_EN_V5'
                r['Estado_Auditoria_V3'] = 'PAR_NUMERADO_EN_V5'
        for r in rows:
            if r['Operacion_Efectiva'] in ('INSERT', 'UPDATE', 'DELETE'):
                r['Estado_Homologacion_V5'] = 'HOMOLOGADO' if r['Estado_Maestro'] in HOMOLOGADOS else \
                    'PENDIENTE_REVISION_LEGADO'
            else:
                r['Estado_Homologacion_V5'] = 'NO_APLICA'

        # ---- Verificación final.
        ops = [r for r in rows if r['Operacion_Efectiva'] in ('INSERT', 'UPDATE', 'DELETE')]
        dests = defaultdict(list)
        origins = defaultdict(list)
        for r in ops:
            op, old, new = r['Operacion_Efectiva'], r['Tag_Origen_Efectivo'], r['Tag_Destino_Efectivo']
            if old in PROTECTED or new in PROTECTED:
                raise RuntimeError('Tag manual tocado')
            if op in ('UPDATE', 'DELETE'):
                if old not in prod or str(prod[old]) != r['ID_Origen_Efectivo']:
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
        for t in dests:
            if t in prod and t not in origins:
                raise RuntimeError('Destino ocupado por producción: ' + t)
        if any(r['Estado_Maestro'] in ('REVISION_ACTUADOR_NO_CONFIRMADO', 'REVISION_VARIABLE_CONFLICTO') for r in ops):
            raise RuntimeError('Quedan operaciones en estado de revisión de actuador/variable')
        esperados = ['700_IT_005', '700_IT_006', '700_IT_007', '500_LT_004', '500_LIC_004', '700_LY_001']
        for t in esperados:
            if t not in dests:
                raise RuntimeError('Falta el tag autorizado ' + t)
        for viejo, nuevo in desvios:
            if viejo in dests or nuevo not in dests:
                raise RuntimeError(f'Desvío no aplicado: {viejo} -> {nuevo}')
        if '700_LXV_001' in dests:
            raise RuntimeError('700_LXV_001 sigue presente tras la homologación')
        if digest(DB) != before:
            raise RuntimeError('SQLite cambió antes de emitir')
        with OUT.open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, cols, delimiter=';', lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
        parsed = read('plan_maestro_consolidado_v5_290926.csv')
        if parsed != rows or any(r['Escritura_SQLite'] != 'NO' for r in parsed):
            raise RuntimeError('CSV inválido')
        counts = Counter(r['Operacion_Efectiva'] for r in parsed)
        nuevos = [r for r in parsed[len(original):] if r['Operacion_Efectiva'] == 'INSERT']
        hom = Counter(r['Estado_Homologacion_V5'] for r in parsed if r['Operacion_Efectiva'] in ('INSERT', 'UPDATE', 'DELETE'))
        print('BLOQUES V5:', dict(Counter(r['Grupo_V5'] for r in nuevos)))
        print('OPERACIONES nuevas:', counts['INSERT'] - 281, 'INSERT;', counts['UPDATE'] - 43, 'UPDATE;',
              counts['DELETE'] - 12, 'DELETE')
        for n in notas:
            print('  -', n)
        print('HOMOLOGACIÓN de', sum(hom.values()), 'operaciones activas:', dict(hom))
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
