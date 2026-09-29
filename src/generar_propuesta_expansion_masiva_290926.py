"""Propuesta sin aplicación: lee producción mode=ro/query_only y dos CSV de evidencia."""
import csv
import hashlib
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / 'exports'
DB = ROOT / 'app_etiquetas' / 'tags_ingenio.db'
OUT = EXPORT / 'propuesta_expansion_masiva_290926.csv'
EXPECTED_SHA = 'dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522'
COLUMNS = ['Bloque', 'Estado_Propuesta', 'Operacion_Propuesta', 'Tag_Actual', 'Tag_Propuesto', 'PLC', 'Program', 'Instancia_PID', 'Rol', 'Area', 'Variable_ISA', 'Numero_Lazo', 'Identidad_PLC', 'Identidades_Consolidadas', 'Direccion_Modulo', 'Evidencia', 'Motivo_Revision', 'Escritura_SQLite']
PROTECTED = {'200_PIT_004','200_PIC_004','200_PV_004','200_LT_035','200_LIC_035','200_LV_035','200_FT_080','200_FIC_080','200_FV_080','250_PV_001','250_PV_002'}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(name):
    with (EXPORT / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=';'))


def tag(area, function, number, suffix=''):
    return f'{area}_{function}_{number:03d}{suffix}'


def main():
    before = sha(DB)
    if before != EXPECTED_SHA:
        raise RuntimeError(f'Hash DB distinto: {before}; sin emitir propuesta')
    con = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        if con.execute('PRAGMA query_only').fetchone()[0] != 1:
            raise RuntimeError('SQLite no está en query_only')
        prod = {r[0]: r for r in con.execute('SELECT tag_completo,plc_origen,descripcion,comentarios,alias_for,numero_loop FROM tags')}
        if len(prod) != 196 or not PROTECTED <= prod.keys() or con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Producción o protección manual inesperada')
        catalog = read('catalogo_candidatos_expansion_280926.csv')
        plan = read('plan_migracion_p1_p2_y_mieles_280926.csv')
        if len(catalog) != 222 or Counter(r['Operacion'] for r in plan)['INSERT'] != 23:
            raise RuntimeError('Fuentes cambiaron: volver a conciliar antes de numerar')
        occupied = defaultdict(set)
        for name in prod:
            m = re.match(r'^(\d{3})_[A-Z]+_(\d{3})(?:[A-Z])?$', name)
            if m:
                occupied[m[1]].add(int(m[2]))
        for p in plan:
            for field in ('Tag_Destino', 'Tag_Origen'):
                m = re.match(r'^(\d{3})_[A-Z]+_(\d{3})(?:[A-Z])?$', p[field])
                if m:
                    occupied[m[1]].add(int(m[2]))
        reserved_tags = set(prod) | {p['Tag_Destino'] for p in plan if p['Tag_Destino']}
        rows = []
        proposed = set()
        def add(block, status, operation='', new='', old='', plc='', program='', instance='', role='', area='', variable='', number='', identity='', identities='', address='', evidence='', reason=''):
            if old in PROTECTED or new in PROTECTED:
                raise RuntimeError('Intento de tocar tag manual')
            if operation in ('INSERT', 'UPDATE'):
                if not new or new in proposed or (operation == 'INSERT' and new in reserved_tags):
                    raise RuntimeError('Colisión de tag propuesto: ' + new)
                proposed.add(new)
            rows.append(dict(zip(COLUMNS, (block,status,operation,old,new,plc,program,instance,role,area,variable,str(number),identity,identities,address,evidence,reason,'NO'))))
        def number(area):
            for n in range(1,1000):
                if n not in occupied[area]:
                    occupied[area].add(n)
                    return n
            raise RuntimeError('Sin números libres para área ' + area)
        by_pid = defaultdict(list)
        by_channel = defaultdict(list)
        for r in catalog:
            by_channel[(r['PLC'],r['Direccion_Modulo'])].append(r)
            if r['Es_Lazo_PID'] == 'SI':
                for instance in r['Instancias_PID'].split(' | '):
                    if instance:
                        by_pid[(r['PLC'], r['Program'], instance)].append(r)
        # Las dos familias fueron autorizadas por ingeniería con sus cuatro miembros literales.
        sulfo = {
            'B_Ctrol_LT_TK_ENCALADO': ('Slot1_LT_TK_JUGO_ENCALADO','Slot3_SI_BB_JUGO_ENCALADO_NORTE','Slot3_SI_BB_JUGO_ENCALADO_SUR','SULFO_ENCALADO:1:I.Ch[1].Data'),
            'B_Ctrol_LT_TK_PESADO': ('Slot1_LT_TK_JUGO_PESADO','Slot3_SI_BB_JUGO_PESADO_NORTE','Slot3_SI_BB_JUGO_PESADO_SUR','SULFO_ENCALADO:1:I.Ch[0].Data'),
        }
        dedicated_channels = set()
        for instance, (inp,north,south,addr) in sulfo.items():
            group = by_pid.get(('FABRICA','SULFO_ENCALADO',instance), [])
            actual = {(r['Identidad_Fisica'],r['Direccion_Modulo']):r for r in group}
            if (inp,addr) not in actual or not all(any(r['Identidad_Fisica'] == name and ':O.' in r['Direccion_Modulo'] for r in group) for name in (north,south)):
                raise RuntimeError('Falta evidencia literal en familia Sulfo: ' + instance)
            n = number('400')
            for name, func, role, suffix in ((inp,'LT','Entrada',''),(instance,'LIC','Controlador',''),(north,'LXV','Salida','A'),(south,'LXV','Salida','B')):
                source = next((r for r in group if r['Identidad_Fisica'] == name), None)
                address = source['Direccion_Modulo'] if source else ''
                if source:
                    dedicated_channels.add(('FABRICA',address))
                add('LAZOS_NUEVOS_SULFO','NO_INSERTAR_REVISION', 'INSERT',tag('400',func,n,suffix),plc='FABRICA',program='SULFO_ENCALADO',instance=instance,role=role,area='400',variable='L',number=n,identity=name,address=address,evidence='Ingeniería: área 400, identidad de entrada y salidas; '+(source['Evidencia_Fisica'] if source else 'instancia en frontera XML'),reason='Propuesta de numeración; no verifica ejecución runtime')
        # Una salida existente prueba ocupación, no ausencia de sus pares. Conciliar todos los miembros.
        frontier_output_groups = 0
        seen_existing = set()
        for (plc,program,instance), group in sorted(by_pid.items()):
            outputs = [r for r in group if ':O' in r['Direccion_Modulo'] and r['Coincidencia_Produccion']]
            if not outputs: continue
            frontier_output_groups += 1
            tags = {t for r in outputs for t in r['Coincidencia_Produccion'].split(' | ') if t}
            if len(tags) != 1:
                add('FRONTERA_3_4','REVISION_RELACION_SALIDAS',plc=plc,program=program,instance=instance,reason='La instancia asocia más de un tag de salida existente')
                continue
            original = next(iter(tags))
            if original in PROTECTED: raise RuntimeError('Salida manual protegida')
            m = re.fullmatch(r'(\d{3})_([A-Z]+)_(\d{3})',original)
            if not m: raise RuntimeError('Salida productiva no reconocida: '+original)
            area, fn, number_text = m.groups()
            n = int(number_text)
            members = {t:prod[t] for t in prod if t.startswith(area+'_') and re.fullmatch(r'\d{3}_[A-Z]+_'+number_text+'[A-Z]?',t)}
            input_tag = tag(area, {'P':'PT','T':'TT','L':'LT','F':'FT','I':'IT','S':'ST'}[fn[0]],n)
            ctrl_tag = tag(area,fn[0]+'IC',n)
            if not {input_tag,ctrl_tag,original} <= members.keys():
                add('FRONTERA_3_4','REVISION_FALTAN_MIEMBROS',plc=plc,program=program,instance=instance,area=area,variable=fn[0],number=n,identity=' | '.join(sorted(tags)),reason='Entrada/controlador/salida no forman grupo completo en producción')
                continue
            input_rows = [r for r in group if ':I' in r['Direccion_Modulo']]
            for r in input_rows:
                dedicated_channels.add((plc,r['Direccion_Modulo']))
            for r in outputs:
                dedicated_channels.add((plc,r['Direccion_Modulo']))
            if original in seen_existing:
                add('FRONTERA_3_4','REVISION_CONTROLADORES_COMPARTEN_SALIDA',plc=plc,program=program,instance=instance,area=area,variable=fn[0],number=n,identity=original,reason='Mismo tag de salida ya asociado a otra instancia; no atribuir entrada automáticamente')
                continue
            seen_existing.add(original)
            source = ' | '.join(r['Identidad_Fisica']+' @ '+r['Direccion_Modulo'] for r in input_rows)
            existing_input = ' | '.join(str(members[input_tag][i] or '') for i in (2,3,4))
            existing_ctrl = ' | '.join(str(members[ctrl_tag][i] or '') for i in (2,3,4))
            if not input_rows or (source and not any(r['Identidad_Fisica'] in existing_input or r['Direccion_Modulo'] in existing_input for r in input_rows)):
                add('FRONTERA_3_4','REVISION_TRAZABILIDAD_ENTRADA',old=input_tag,plc=plc,program=program,instance=instance,role='Entrada',area=area,variable=fn[0],number=n,identity=source,reason='Par cargado, pero la identidad/canal físico trazado no figura en la descripción, comentarios o alias_for; verificar antes de UPDATE')
            if instance not in existing_ctrl:
                add('FRONTERA_3_4','REVISION_TRAZABILIDAD_CONTROLADOR',old=ctrl_tag,plc=plc,program=program,instance=instance,role='Controlador',area=area,variable=fn[0],number=n,identity=instance,reason='Identidad de instancia no acreditada en campos de procedencia productivos')
            unique_outputs = {r['Direccion_Modulo']:r for r in outputs}
            # UPDATE + INSERT sólo si la descripción productiva consigna literalmente ambos canales.
            if len(unique_outputs) == 2 and all(addr in (prod[original][2] or '') for addr in unique_outputs):
                for suffix,(address,r) in zip('AB',sorted(unique_outputs.items())):
                    add('FRONTERA_3_4','NO_INSERTAR_REVISION','UPDATE' if suffix=='A' else 'INSERT',tag(area,fn,n,suffix),original if suffix=='A' else '',plc,program,instance,'Salida',area,fn[0],n,r['Identidad_Fisica'],'',address,r['Evidencia_Fisica'],'Desglose planificado; UPDATE/INSERT sujeto a validación de ingeniería')
            elif len(unique_outputs) > 1:
                add('FRONTERA_3_4','REVISION_SALIDAS_MULTIPLES',old=original,plc=plc,program=program,instance=instance,area=area,variable=fn[0],number=n,reason='Canales de salida no acreditados conjuntamente en producción')
            elif not input_rows:
                add('FRONTERA_3_4','REVISION_ENTRADA_NO_TRAZADA',old=original,plc=plc,program=program,instance=instance,area=area,variable=fn[0],number=n,reason='Grupo productivo completo, pero entrada física no trazada por catálogo')
            else:
                add('FRONTERA_3_4','YA_TAGUEADO_REVISAR_TRAZABILIDAD',old=original,plc=plc,program=program,instance=instance,area=area,variable=fn[0],number=n,identity=source,reason='Tres miembros ya presentes; no proponer INSERT por una discrepancia de procedencia')
        # La condición SIN_LAZO exige un canal físico único, no utilizado por un PID.
        monitoring = defaultdict(list)
        for r in catalog:
            if r['Es_Lazo_PID'] == 'NO' and r['Estado_Catalogacion'] in ('CANDIDATO_FISICO_REVISAR_LAZO','REVISION_CANAL_COMPARTIDO','PENDIENTE_AREA_VARIABLE_TIPO'):
                monitoring[(r['PLC'],r['Direccion_Modulo'])].append(r)
        pid_channels = {(r['PLC'],r['Direccion_Modulo']) for r in catalog if r['Es_Lazo_PID']=='SI'} | dedicated_channels
        for (plc,address),items in sorted(monitoring.items()):
            if ':I' not in address and ':O' not in address: continue
            names = sorted({r['Identidad_Fisica'] for r in items})
            area_set = {r['Area_Inferida'] for r in items}
            var_set = {r['Variable_ISA'] for r in items}
            typ_set = {r['Tipo_Instrumento'] for r in items}
            exemplar = items[0]
            def pending(reason):
                add('MONITOREO_SIN_LAZO','REVISION_NO_NUMERAR',plc=plc,program=exemplar['Program'],area=exemplar['Area_Inferida'],variable=exemplar['Variable_ISA'],identity=names[0],identities=' | '.join(names),address=address,evidence=' | '.join(sorted({i['Evidencia_Fisica'] for i in items})),reason=reason)
            if (plc,address) in pid_channels or any(r['Coincidencia_Produccion'] for r in by_channel[(plc,address)]):
                pending('Canal usado por PID o representado en producción: no es monitoreo independiente')
                continue
            if len(area_set)!=1 or len(var_set)!=1 or len(typ_set)!=1 or not all((next(iter(area_set)),next(iter(var_set)),next(iter(typ_set)))):
                pending('Área, variable o tipo sin prueba consistente')
                continue
            if len(names)>1:
                normalized = {re.sub(r'_2$','',re.sub(r'^Slot_','',x,flags=re.I),flags=re.I).upper() for x in names}
                if len(normalized)!=1 and not (plc=='DESTILERIA' and all(x.startswith('FT_VINO_A_JW_ACUM_') for x in names)) and not set(names)=={'Slot_ST_MOTOR_CONDUCTOR','M_MIN_CONDUCTORA'}:
                    pending('Identidades contradictorias sobre un mismo canal; no consolidar por canal solamente')
                    continue
            area = next(iter(area_set));var=next(iter(var_set));typ=next(iter(typ_set))
            if any(x.startswith('S3_SI_') for x in names):
                pending('S3_SI sin demostración de medida de velocidad; salidas :O son comandos')
                continue
            if typ=='Switch':
                function= 'FSL' if names[0].startswith('FSL_') else var+'S'
            elif typ=='Válvula':
                function=var+'V'
            else:
                function=var+'T'
            if ':O' in address and typ!='Válvula':
                pending('Salida no es transmisor físico')
                continue
            if ':I' in address and typ=='Válvula':
                pending('Entrada no es válvula física')
                continue
            n=number(area)
            add('MONITOREO_SIN_LAZO','NO_INSERTAR_REVISION','INSERT',tag(area,function,n),plc=plc,program=exemplar['Program'],role=typ,area=area,variable=var,number=n,identity=names[0],identities=' | '.join(names),address=address,evidence=' | '.join(sorted({i['Evidencia_Fisica'] for i in items})),reason='Número libre contra DB+plan; instrumento independiente por canal; validar en campo')
        if sha(DB)!=before:raise RuntimeError('Producción cambió durante propuesta; abortar salida')
        with OUT.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,COLUMNS,delimiter=';',lineterminator='\n');writer.writeheader();writer.writerows(rows)
        assert read(OUT)==rows
        assert all(r['Escritura_SQLite']=='NO' for r in rows)
        assert not {r['Tag_Actual'] for r in rows if r['Operacion_Propuesta'] in ('UPDATE','DELETE')} & PROTECTED
        assert not {r['Tag_Propuesto'] for r in rows if r['Operacion_Propuesta']=='INSERT'} & reserved_tags
        print('Instancias con salida productiva trazada:',frontier_output_groups,'(no asumir 19 sin conciliación)')
        for block in ('LAZOS_NUEVOS_SULFO','FRONTERA_3_4','MONITOREO_SIN_LAZO'):
            group=[r for r in rows if r['Bloque']==block]
            print(block,'propuestas INSERT',sum(r['Operacion_Propuesta']=='INSERT' for r in group),'UPDATE',sum(r['Operacion_Propuesta']=='UPDATE' for r in group),'revisiones',sum(r['Estado_Propuesta'].startswith('REVISION') for r in group))
        print('TOTAL filas',len(rows),'CSV SHA-256',sha(OUT))
        print('DB registros',len(prod),'SHA-256 antes/después',before,sha(DB),'query_only=ON; cero escrituras SQLite')
        if sha(DB)!=before:raise RuntimeError('DB cambió tras escribir CSV')
    finally:
        con.close()

if __name__=='__main__':main()
