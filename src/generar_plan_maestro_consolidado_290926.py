"""Consolida propuestas de revisión en CSV; nunca escribe SQLite."""
import csv
import hashlib
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / 'exports'
DB = ROOT / 'app_etiquetas/tags_ingenio.db'
OUT = EX / 'plan_maestro_consolidado_290926.csv'
EXPECTED = 'dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522'
PROTECTED = {'200_PIT_004','200_PIC_004','200_PV_004','200_LT_035','200_LIC_035','200_LV_035','200_FT_080','200_FIC_080','200_FV_080','250_PV_001','250_PV_002'}
MASTER = ['Fuente_Fila','Bloque_Maestro','Operacion_Efectiva','Tag_Origen_Efectivo','Tag_Destino_Efectivo','ID_Origen_Efectivo','Area_Efectiva','Variable_Efectiva','Numero_Efectivo','Identidad_PLC_Efectiva','Direccion_Modulo_Efectiva','Estado_Maestro','Nota_Maestra','Escritura_SQLite']


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def read(n):
    with (EX/n).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f,delimiter=';'))


def keytag(t):
    m=re.fullmatch(r'(\d{3})_[A-Z]+_(\d{3})(?:[A-Z])?',t or '')
    return (m[1],int(m[2])) if m else None


def main():
    before=sha(DB)
    if before!=EXPECTED:raise RuntimeError('Producción cambió: '+before)
    con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        if con.execute('PRAGMA query_only').fetchone()[0]!=1:raise RuntimeError('No es query_only')
        prod={r[0]:r for r in con.execute('SELECT tag_completo,id,plc_origen,COALESCE(descripcion,\'\'),COALESCE(comentarios,\'\'),COALESCE(alias_for,\'\') FROM tags')}
        if len(prod)!=196 or not PROTECTED<=prod.keys() or con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Base inesperada')
        p=read('plan_migracion_p1_p2_y_mieles_280926.csv')
        e=read('propuesta_expansion_masiva_290926.csv')
        cat=read('catalogo_candidatos_expansion_280926.csv')
        if len(p)!=67 or len(e)!=159 or len(cat)!=222:raise RuntimeError('Fuentes cambiaron')
        original_cols=list(dict.fromkeys([k for rs in (p,e) for r in rs for k in r]))
        cols=MASTER+[k for k in original_cols if k not in MASTER]
        rows=[]
        occupied=defaultdict(set)
        for t in set(prod)|{r['Tag_Destino'] for r in p}|{r['Tag_Propuesto'] for r in e}:
            k=keytag(t)
            if k:occupied[k[0]].add(k[1])
        def free(a):
            for n in range(1,1000):
                if n not in occupied[a]:occupied[a].add(n);return n
            raise RuntimeError('Sin libre '+a)
        def row(source,block,op='',old='',new='',id_old='',area='',var='',n='',identity='',addr='',status='PROPUESTA_NO_APLICAR',note='',original=None):
            x=dict.fromkeys(cols,'')
            if original:x.update(original)
            x.update(dict(zip(MASTER,(source,block,op,old,new,str(id_old),area,var,str(n),identity,addr,status,note,'NO'))))
            rows.append(x)
            return x
        for i,r in enumerate(p,2):
            op=r['Operacion'] if r['Operacion'] in ('INSERT','UPDATE','DELETE','MANTENER') else ''
            row(f'plan_migracion_p1_p2_y_mieles_280926.csv:{i}',r['Grupo'],op,r['Tag_Origen'],r['Tag_Destino'],r['ID_Origen'],r['Area_Destino'],r['Variable_ISA'],r['Numero_Destino'],r['Identidad_PLC'],r['Destino_Fisico'],'PENDIENTE_REEMPLAZADO' if not op else r['Estado_Revision'],r['Nota'],r)
        for i,r in enumerate(e,2):
            op=r['Operacion_Propuesta']
            old=r['Tag_Actual'];new=r['Tag_Propuesto']
            status=r['Estado_Propuesta'];note=r['Motivo_Revision']
            if r['Instancia_PID']=='B_PC_ESC_CAMPO_AUX' and not op:
                status='SUPERADO_POR_RAMA_E';note+='; ver operaciones Rama E'
            row(f'propuesta_expansion_masiva_290926.csv:{i}',r['Bloque'],op,old,new,prod[old][1] if old in prod else '',r['Area'],r['Variable_ISA'],r['Numero_Lazo'],r['Identidad_PLC'],r['Direccion_Modulo'],status,note,r)
        bypid=defaultdict(list)
        by_addr=defaultdict(list)
        for r in cat:
            by_addr[(r['PLC'],r['Direccion_Modulo'])].append(r)
            for instance in r['Instancias_PID'].split(' | '):
                if instance and r['Es_Lazo_PID']=='SI':bypid[(r['PLC'],r['Program'],instance)].append(r)
        # Las funciones finales son candidatas, no prueba del dispositivo conectado al canal.
        groups=[
            ('FABRICA','FAB_ESCALADOS','CONTROL_NIVEL_TK_MIEL1','700','L','FLEX5000_MIELES:1:I.Ch05.Data',['FLEX5000_MIELES:2:O.Ch00.Data'],'LXV'),
            ('Calderas_8_9_10_Desaireador','C8','B_C8_PC_HOGAR','300','P','BP_ANALOGICA:1:I.Ch[5].Data',['BP_ANALOGICA:10:O.Ch6Data','BP_ANALOGICA:10:O.Ch7Data'],'PV'),
            ('Calderas_8_9_10_Desaireador','C10','B_C10_PC_HOGAR','300','P','BP_ANALOGICA:3:I.Ch[5].Data',['BP_ANALOGICA:12:O.Ch3Data','BP_ANALOGICA:12:O.Ch4Data'],'PV'),
            ('Calderas_8_9_10_Desaireador','MainProgram','PID_CONTROL_NIVEL_BBA_AGUA_CENIZA','300','L','BP_ANALOGICA:6:I.Ch[6].Data',['BP_DIGITALES:1:O.Ch6Data','BP_DIGITALES:1:O.Ch7Data'],'LY'),
            ('DIBACCO','MainProgram','Ctrol_Presion_Escape_Tamiz','250','P','Local:6:I.Ch0Data',['Local:14:O.Ch6Data'],'PV'),
            ('FABRICA','SULFO_ENCALADO','CONTROL_PRESION_BIO','400','P','SULFO_ENCALADO:1:I.Ch[7].Data',['SULFO_ENCALADO:7:O.Ch[0].Data'],'PV'),
            ('FABRICA','FAB_CCV','B_PID_VAL_20_10_AUX_1','700','P','ISLA_FAB_AI:2:I.Ch[3].Data',['ISLA_FAB_AI:13:O.Ch[6].Data'],'PV'),
            ('FABRICA','FAB_CCV','B_PID_VAL_20_10_AUX_2','400','P','SULFO_ENCALADO:4:I.Ch0Data',['SULFO_ENCALADO:8:O.Ch7Data'],'PV'),
        ]
        new_loops={}
        for plc,program,instance,area,var,input_addr,outputs,final_fn in groups:
            evidence=bypid[(plc,program,instance)]
            actual={(r['Direccion_Modulo'],r['Es_Lazo_PID']) for r in evidence}
            if (input_addr,'SI') not in actual or any((o,'SI') not in actual for o in outputs):raise RuntimeError('Extremos no sustentados: '+instance)
            for addr in [input_addr]+outputs:
                if any(r['Coincidencia_Produccion'] for r in by_addr[(plc,addr)]):raise RuntimeError('Canal ya representado: '+addr)
            n=free(area);new_loops[instance]=(area,n)
            entries=[('Entrada',input_addr,var+'T',''),('Controlador','',var+'IC','')]
            entries += [('Salida',addr,final_fn,chr(65+j) if len(outputs)>1 else '') for j,addr in enumerate(outputs)]
            for role,addr,fn,suffix in entries:
                t=f'{area}_{fn}_{n:03d}{suffix}'
                identity=(next((r['Identidad_Fisica'] for r in evidence if r['Direccion_Modulo']==addr),addr) if addr else instance)
                row('INGENIERIA_USUARIO_290926','LAZOS_COMPLETOS_3_4','INSERT','',t,'',area,var,n,identity,addr,'CANDIDATO_FUNCION_FINAL_REVISAR' if role=='Salida' else 'NO_INSERTAR_REVISION',f'{plc}/{program}/{instance}; función final {fn} tentativa: dirección sola no demuestra tipo de actuador')
        # Cerrar la referencia, sin convertir una fila vacía heredada en operación contable.
        pending=[r for r in rows if r['Estado_Maestro']=='PENDIENTE_REEMPLAZADO']
        if len(pending)!=1 or 'CONTROL_NIVEL_TK_MIEL1' not in pending[0]['Instancia']:raise RuntimeError('Addendum inesperado')
        pending[0]['Nota_Maestra']='Sustituida por tres INSERT candidatos de LAZOS_COMPLETOS_3_4; no contar dos veces.'
        sensors=[
            ('DIBACCO','nivel_pileta','Local:13:I.Ch7Data','250','LT'),
            ('DIBACCO','salida_presion306','Local:6:I.Ch4Data','250','PT'),
            ('DIBACCO','salida_presion307','Local:6:I.Ch5Data','250','PT'),
            ('cenizas2020','nivel_agua_filtrada','Local:2:I.Ch[1].Data','300','LT'),
            ('cenizas2020','nivel_agua_clarificada','Local:2:I.Ch[3].Data','300','LT'),
            ('cenizas2020','nivel_nivel_cenizas','Local:2:I.Ch[4].Data','300','LT'),
            ('cenizas2020','L_040_PV_Escalado','Local:9:I.Ch[0].Data','300','LT'),
            ('cenizas2020','F_010_PV_Escalado','Local:2:I.Ch[5].Data','300','FT'),
            ('cenizas2020','F_020_PV_Escalado','Local:2:I.Ch[6].Data','300','FT'),
            ('cenizas2020','AT_010_PV_Escalado','Local:2:I.Ch[7].Data','300','AT'),
            ('cenizas2020','WSH_010','Local:3:I.Data.6','300','WSH'),
            ('cenizas2020','WSHH_010','Local:3:I.Data.7','300','WSHH'),
        ]
        for plc,identity,addr,area,fn in sensors:
            found=[r for r in cat if r['PLC']==plc and r['Identidad_Fisica']==identity and r['Direccion_Modulo']==addr and r['Es_Lazo_PID']=='NO']
            if len(found)!=1 or found[0]['Coincidencia_Produccion']:raise RuntimeError('Sensor no sustentado o ya producido: '+identity)
            if len(by_addr[(plc,addr)])!=1:raise RuntimeError('Canal compartido: '+identity)
            if any(r['Direccion_Modulo_Efectiva']==addr and r['Operacion_Efectiva']=='INSERT' and r.get('PLC')==plc for r in rows):raise RuntimeError('Canal ya propuesto: '+identity)
            n=free(area)
            row('INGENIERIA_USUARIO_290926','SENSORES_SIN_LAZO','INSERT','',f'{area}_{fn}_{n:03d}','',area,fn[0],n,identity,addr,'NO_INSERTAR_REVISION','Identidad/canal único en catálogo; variable y función definidas por ingeniería')
        # Rama E, conservando el transmisor compartido base. Probar identidad PLC, no sólo número.
        shared='ISLA_FAB_AI:7:I.Ch4Data'
        match=[r for r in cat if r['PLC']=='FABRICA' and r['Direccion_Modulo']==shared and 'B_PC_ESC_CAMPO_AUX' in r['Instancias_PID']]
        if len(match)!=1 or match[0]['Identidad_Fisica']!='CCV_S7_PT_VAP_ESCAPE':raise RuntimeError('Transmisor común no demostrado')
        if not all(x in prod for x in ('700_PT_024','700_PT_027','700_PIC_027','700_PXV_027')):raise RuntimeError('Rama E incompleta')
        for t in ('700_PT_024','700_PT_027'):
            if 'CCV_PT_VAP_ESCAPE' not in (prod[t][3]+' '+prod[t][4]):raise RuntimeError('Proveniencia compartida no demostrada: '+t)
        for old,new,op in [('700_PIC_027','700_PIC_024E','UPDATE'),('700_PXV_027','700_PXV_024E','UPDATE'),('700_PT_027','','DELETE')]:
            row('INGENIERIA_USUARIO_290926','COLECTOR_ESCAPE_RAMA_E',op,old,new,prod[old][1],'700','P','024' if new else '027','B_PC_ESC_CAMPO_AUX',shared,'NO_INSERTAR_REVISION','PT_024 conservado; 700_PT_027 duplicado por misma identidad de transmisor; Rama E')
        # Sólo los 18 otros renglones del estado de revisión; uno carece de dirección.
        reviews=[r for r in rows if r['Fuente_Fila'].startswith('propuesta_expansion_masiva_290926.csv:') and r['Estado_Propuesta']=='REVISION_TRAZABILIDAD_ENTRADA']
        if len(reviews)!=19:raise RuntimeError('Revisiones de entrada cambiaron')
        for r in reviews:
            if r['Tag_Origen_Efectivo']=='700_PT_027':continue
            old=r['Tag_Origen_Efectivo'];plc=r['PLC'];inst=r['Instancia_PID']
            matches=[x for x in bypid[(plc,r['Program'],inst)] if ':I' in x['Direccion_Modulo']]
            if len(matches)!=1 or not matches[0]['Direccion_Modulo']:
                r['Estado_Maestro']='REVISION_SIN_CANAL_UNICO'
                r['Nota_Maestra']='No se propone UPDATE sin canal de entrada inequívoco.'
                continue
            physical=matches[0]
            if old not in prod or prod[old][2]!=plc or old in PROTECTED:raise RuntimeError('Origen entrada inválido '+old)
            r['Operacion_Efectiva']='UPDATE'
            r['Tag_Destino_Efectivo']=old
            r['ID_Origen_Efectivo']=str(prod[old][1])
            r['Identidad_PLC_Efectiva']=physical['Identidad_Fisica']
            r['Direccion_Modulo_Efectiva']=physical['Direccion_Modulo']
            r['Estado_Maestro']='UPDATE_METADATOS_NO_RENOMBRAR'
            r['Nota_Maestra']='Anexar canal físico en trazabilidad; conservar nombre ISA y procedencia existente (no sustituir identidad PLC por canal).'
        # Validación global de ledger (incluidos conflictos cruzados entre fuentes).
        operations=[r for r in rows if r['Operacion_Efectiva'] in ('INSERT','UPDATE','DELETE')]
        origin_ops=defaultdict(list);dests=defaultdict(list)
        for r in operations:
            op=r['Operacion_Efectiva'];old=r['Tag_Origen_Efectivo'];new=r['Tag_Destino_Efectivo']
            if old in PROTECTED or new in PROTECTED:raise RuntimeError('Protegido en operación: '+old+' '+new)
            if op in ('UPDATE','DELETE'):
                if old not in prod or str(prod[old][1])!=r['ID_Origen_Efectivo']:raise RuntimeError('ID/origen inexistente: '+old)
                origin_ops[old].append(r)
            if op in ('INSERT','UPDATE'):
                if not new or not keytag(new):raise RuntimeError('Destino sin tag válido')
                dests[new].append(r)
        for old,rr in origin_ops.items():
            if len(rr)>1:raise RuntimeError('Doble operación sobre '+old)
        for new,rr in dests.items():
            if len(rr)>1:raise RuntimeError('Destino duplicado '+new)
            if new in prod and new not in origin_ops:raise RuntimeError('Colisión con producción no transformada '+new)
        counts=Counter(r['Operacion_Efectiva'] for r in operations)
        if len([r for r in rows if r['Bloque_Maestro']=='LAZOS_COMPLETOS_3_4' and r['Operacion_Efectiva']=='INSERT'])!=27 or len([r for r in rows if r['Bloque_Maestro']=='SENSORES_SIN_LAZO' and r['Operacion_Efectiva']=='INSERT'])!=12:raise RuntimeError('Grupos nuevos incompletos')
        if sha(DB)!=before:raise RuntimeError('DB cambió antes de emitir')
        with OUT.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,cols,delimiter=';',lineterminator='\n');w.writeheader();w.writerows(rows)
        parsed=read(OUT)
        if parsed!=rows or any(r['Escritura_SQLite']!='NO' for r in parsed):raise RuntimeError('CSV inválido')
        if sha(DB)!=before:raise RuntimeError('DB cambió después de emitir')
        print('FUENTES plan',len(p),'expansión',len(e),'nuevas',len(rows)-len(p)-len(e),'CSV total',len(rows))
        print('LAZOS',new_loops)
        print('BALANCE INSERT',counts['INSERT'],'UPDATE',counts['UPDATE'],'DELETE',counts['DELETE'],'TOTAL PROYECTADO',len(prod)+counts['INSERT']-counts['DELETE'])
        print('REVISIÓN sin canal inequívoco',[(r['Tag_Origen_Efectivo'],r['Instancia_PID']) for r in rows if r['Estado_Maestro']=='REVISION_SIN_CANAL_UNICO'])
        print('Funciones finales tentativas',sum(r['Estado_Maestro']=='CANDIDATO_FUNCION_FINAL_REVISAR' for r in rows))
        print('CSV SHA-256',sha(OUT))
        print('DB',len(prod),'SHA-256 antes/después',before,sha(DB),'mode=ro query_only=ON; cero escrituras')
    finally:con.close()

if __name__=='__main__':main()
