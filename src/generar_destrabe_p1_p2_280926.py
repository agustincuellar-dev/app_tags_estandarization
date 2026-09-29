"""Concilia 20 filas de prioridad 1/2 con producción, sin escribir SQLite ni L5X."""
import csv
import hashlib
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'exports/estado_tagueo_prioridad_1_2_280926.csv'
TARGET = ROOT / 'exports/propuesta_destrabe_p1_p2_280926.csv'
DB = ROOT / 'app_etiquetas/tags_ingenio.db'
EXPECTED_SHA = '6f8f9c349c992da112609613a05066d0d1964c843826b29ae8be27e0517fb0b8'
COLS = ['Fila_Origen','Grupo','PLC','Program','Routine','Instancia','Prioridad','Estado_Revision','Area','Variable_ISA','Numero_Propuesto','Entrada_Fisica','Entrada_Camino','Salida_Fisica','Entrada_Tag_Propuesto','Controlador_Tag_Propuesto','Salidas_Tags_Propuestos','Tags_Vigentes_Produccion','Entrada_Tag_Vigente','Controlador_Tag_Vigente','Salidas_Tags_Vigentes','Esquema_Solicitado','Motivo','Requiere_Autorizacion','Escritura_SQLite']

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    before = digest(DB)
    if before != EXPECTED_SHA:
        raise RuntimeError('Hash de DB distinto al esperado: ' + before)
    with SOURCE.open(encoding='utf-8-sig', newline='') as f:
        rows = [(i, row) for i, row in enumerate(csv.DictReader(f, delimiter=';'), 1)
                if row['Estado_Elegibilidad'] == 'BLOQUEADO_NO_NUMERAR']
    if len(rows) != 20:
        raise RuntimeError(f'Se esperaban 20 bloqueadas; hay {len(rows)}')
    addendum = ROOT / 'exports/addendum_propuesta_mieles_230926.csv'
    with addendum.open(encoding='utf-8-sig', newline='') as f:
        reserved = {(r['Area'], int(r['Numero_Propuesto'])) for r in csv.DictReader(f, delimiter=';')
                    if r['Area'].isdigit() and r['Numero_Propuesto'].isdigit()}
    conn = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    try:
        conn.execute('PRAGMA query_only=ON')
        count = conn.execute('SELECT count(*) FROM tags').fetchone()[0]
        if count != 196:
            raise RuntimeError(f'Producción: {count} en vez de 196')
        live = conn.execute('SELECT t.tag_completo,t.plc_origen,t.descripcion,a.rango_inicio,t.numero_loop '
                            'FROM tags t JOIN areas a ON a.id=t.area_id').fetchall()
        occupied = {(str(a).zfill(3), n) for _, _, _, a, n in live} | reserved
        planned = set()
        def alloc(area):
            prior = [n for a,n in occupied | planned if a == area]
            n = max(prior, default=int(area)) + 1
            while (area,n) in occupied | planned:
                n += 1
            planned.add((area,n))
            return n
        # Sólo cinco XML concretos; el trazador analiza únicamente las cinco instancias del grupo D.
        sys.path.insert(0, str(ROOT / 'src'))
        from trazador_lazos_profundo import L5X
        cases = {'B_CONTROL_BBA_MOSTO','B_Ctrol_GRADO_BRIX_MOSTO','B_PC_VG1_TACHOS','CONTROL_NIVEL_06','IC_CINTA_RAPIDA_2'}
        cache = {}
        result = []
        for i, src in rows:
            inst, plc = src['Instancia'], src['PLC']
            out = {k:'' for k in COLS}
            out.update(Fila_Origen=str(i), PLC=plc, Program=src['Program'], Routine=src['Routine'],
                       Instancia=inst, Prioridad=src['Prioridad'], Entrada_Fisica=src['Entrada_Fisica'],
                       Entrada_Camino=src['Entrada_Camino'], Salida_Fisica=src['Salida_Fisica'],
                       Requiere_Autorizacion='SI', Escritura_SQLite='NO')
            if inst in cases:
                if plc not in cache:
                    cache[plc] = L5X(ROOT / 'L5X_Produccion' / (plc + '.L5X'))
                trace = cache[plc].analizar(plc,src['Program'],src['Routine'],inst)
                out['Entrada_Fisica'] = trace.get('entrada_fisica','')
                out['Entrada_Camino'] = trace.get('entrada_camino','')
                out['Salida_Fisica'] = trace.get('salida_fisica','')
            else:
                trace = None
            # Coincidencia exacta del delimitador de identidad, no substring de otro lazo.
            pattern = re.compile(r'\blazo ' + re.escape(inst) + r';')
            matches = [(tag,a,n) for tag,origin,desc,a,n in live if origin == plc and pattern.search(desc or '')]
            if inst in ('CONTROL_NIVEL_02','CONTROL_NIVEL_2_01'):
                out['Grupo']='B:Desaireador Gonella';out['Area']='000';out['Variable_ISA']='L'
            elif inst in ('B_PC_ALTA_ESC_L1','B_PC_ALTA_ESC_L2','B_PC_ESC_CAMPO','B_PC_ESC_TACHOS'):
                out['Grupo']='B:Colector Vapor Escape';out['Area']='700';out['Variable_ISA']='P'
            elif inst in ('B_PC_TACHOS_CAMPO','B_PC_VG2_TACHOS'):
                out['Grupo']='B:Vapor a Tachos';out['Area']='700';out['Variable_ISA']='P'
            elif inst in ('B_TC_COND_3RA','B_TC_COND_3RA_AUXILIAR'):
                out['Grupo']='B:Condensador 3ra';out['Area']='600';out['Variable_ISA']='T'
            elif inst in ('EVAP_LC_JC_EVAPORACION','B_Ctrl_JUGO_COLADO_2','B_Ctrol_FT_JUGO_SECUNDARIO'):
                out['Grupo']='C:Salidas paralelas';out['Area']={'EVAP_LC_JC_EVAPORACION':'500','B_Ctrl_JUGO_COLADO_2':'100','B_Ctrol_FT_JUGO_SECUNDARIO':'PENDIENTE_AREA'}[inst];out['Variable_ISA']='F'
            elif inst in ('COC_LC_MELADO_T','PID_CONTROL_MESA_NORTE_SUR'):
                out['Grupo']='A:1-a-1';out['Area']='600' if inst.startswith('COC_') else '100';out['Variable_ISA']='L'
            else:
                out['Grupo']='D:Analizador';out['Area']={'B_CONTROL_BBA_MOSTO':'200','B_PC_VG1_TACHOS':'700','IC_CINTA_RAPIDA_2':'100','CONTROL_NIVEL_06':'100','B_Ctrol_GRADO_BRIX_MOSTO':'200'}[inst]
                out['Variable_ISA']={'B_CONTROL_BBA_MOSTO':'F','B_PC_VG1_TACHOS':'P','IC_CINTA_RAPIDA_2':'I','CONTROL_NIVEL_06':'L','B_Ctrol_GRADO_BRIX_MOSTO':''}[inst]
            if out['Grupo'].startswith('B:'):
                members = {'CONTROL_NIVEL_02':['CONTROL_NIVEL_02','CONTROL_NIVEL_2_01'],
                           'CONTROL_NIVEL_2_01':['CONTROL_NIVEL_02','CONTROL_NIVEL_2_01'],
                           'B_PC_ALTA_ESC_L1':['B_PC_ALTA_ESC_L1','B_PC_ALTA_ESC_L2','B_PC_ESC_CAMPO','B_PC_ESC_TACHOS'],
                           'B_PC_ALTA_ESC_L2':['B_PC_ALTA_ESC_L1','B_PC_ALTA_ESC_L2','B_PC_ESC_CAMPO','B_PC_ESC_TACHOS'],
                           'B_PC_ESC_CAMPO':['B_PC_ALTA_ESC_L1','B_PC_ALTA_ESC_L2','B_PC_ESC_CAMPO','B_PC_ESC_TACHOS'],
                           'B_PC_ESC_TACHOS':['B_PC_ALTA_ESC_L1','B_PC_ALTA_ESC_L2','B_PC_ESC_CAMPO','B_PC_ESC_TACHOS'],
                           'B_PC_TACHOS_CAMPO':['B_PC_TACHOS_CAMPO','B_PC_VG2_TACHOS'],
                           'B_PC_VG2_TACHOS':['B_PC_TACHOS_CAMPO','B_PC_VG2_TACHOS'],
                           'B_TC_COND_3RA':['B_TC_COND_3RA','B_TC_COND_3RA_AUXILIAR'],
                           'B_TC_COND_3RA_AUXILIAR':['B_TC_COND_3RA','B_TC_COND_3RA_AUXILIAR']}[inst]
                letter = 'ABCD'[members.index(inst)]
                out['Esquema_Solicitado']=f"{out['Area']}_{out['Variable_ISA']}T_<NUM>; rama {letter}: {out['Area']}_{out['Variable_ISA']}IC_<NUM>{letter} + {out['Area']}_{out['Variable_ISA']}XV_<NUM>{letter} (sujeto a revisión de función final)"
            elif out['Grupo'].startswith('C:'):
                finals=[x.strip().split(' (')[0] for x in out['Salida_Fisica'].split(' | ') if x.strip()]
                out['Esquema_Solicitado']='Entrada y controlador sin sufijo; finales: '+ ' | '.join(f'{chr(65+j)}={s}' for j,s in enumerate(finals))
            if matches:
                out['Tags_Vigentes_Produccion']=' | '.join(t for t,_,_ in matches)
                for tag, _, _ in matches:
                    func = tag.split('_')[1]
                    key = ('Entrada_Tag_Vigente' if func.endswith('T') else
                           'Controlador_Tag_Vigente' if func.endswith('IC') else 'Salidas_Tags_Vigentes')
                    out[key] += (' | ' if out[key] else '') + tag
                out['Estado_Revision']='YA_TAGUEADO_EN_PRODUCCION_REQUIERE_CONCILIACION'
                out['Motivo']='La instantánea de bloqueados es obsoleta: identidad ya numerada en producción. No crear ni renumerar sin migración autorizada; esquema de sufijos es sólo conceptual.'
                if trace: out['Motivo'] += ' Trazador: '+trace['clasificacion']+'; '+trace['nota']
            elif inst in ('B_Ctrol_GRADO_BRIX_MOSTO','CONTROL_NIVEL_06'):
                out['Estado_Revision']='BLOQUEADO_NO_NUMERAR';out['Motivo']=trace['nota']
            elif out['Area']=='PENDIENTE_AREA':
                out['Estado_Revision']='BLOQUEADO_NO_NUMERAR';out['Motivo']='Sin área SULFO_ENCALADO establecida en DB; no inferir del nombre del programa.'
            elif inst in ('COC_LC_MELADO_T','PID_CONTROL_MESA_NORTE_SUR','IC_CINTA_RAPIDA_2'):
                area,var=out['Area'],out['Variable_ISA']
                if trace and trace['clasificacion']!='CERRABLE_HOY':
                    out['Estado_Revision']='BLOQUEADO_NO_NUMERAR';out['Motivo']=trace['nota']
                else:
                    n=alloc(area);num=f'{n:03d}';out['Numero_Propuesto']=num
                    out['Entrada_Tag_Propuesto']=f'{area}_{var}T_{num}'
                    out['Controlador_Tag_Propuesto']=f'{area}_{var}IC_{num}'
                    final='Y' if inst=='IC_CINTA_RAPIDA_2' else ('V' if inst=='COC_LC_MELADO_T' else 'XV')
                    out['Salidas_Tags_Propuestos']=f'{area}_{var}{final}_{num}'
                    out['Estado_Revision']='CANDIDATO_NO_INSERTAR'
                    out['Motivo']='Número posterior al máximo ocupado en DB y reservas Addendum de Mieles; requiere revisión de otros universos e ingeniería antes de insertar.'
                    if trace: out['Motivo'] += ' Trazador: '+trace['nota']
            else:
                raise RuntimeError('Caso sin clasificación: '+inst)
            result.append(out)
        if len(result)!=20: raise RuntimeError('Cantidad de salida inesperada')
        # No escribir parcialmente si la DB cambió durante la lectura.
        if digest(DB)!=before: raise RuntimeError('La DB cambió durante el análisis')
        with TARGET.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=COLS,delimiter=';',lineterminator='\n');w.writeheader();w.writerows(result)
        with TARGET.open(encoding='utf-8-sig',newline='') as f:
            check=list(csv.DictReader(f,delimiter=';'))
        if len(check)!=20 or len({(x['PLC'],x['Program'],x['Routine'],x['Instancia']) for x in check})!=20:
            raise RuntimeError('CSV inválido')
        newtags=[x[k] for x in check for k in ('Entrada_Tag_Propuesto','Controlador_Tag_Propuesto','Salidas_Tags_Propuestos') if x[k]]
        if len(newtags)!=len(set(newtags)) or any(t in {v[0] for v in live} for t in newtags):
            raise RuntimeError('Colisión de tags nuevos')
        print('Fila | Instancia | Estado | Tags candidatos / vigentes')
        for x in check:
            print(f"{x['Fila_Origen']:>4} | {x['Instancia']} | {x['Estado_Revision']} | {x['Entrada_Tag_Propuesto']} {x['Controlador_Tag_Propuesto']} {x['Salidas_Tags_Propuestos']} / {x['Tags_Vigentes_Produccion']}")
        print('Resumen:',dict(Counter(x['Estado_Revision'] for x in check)))
        print('CSV:',TARGET,'SHA-256:',digest(TARGET))
        print('Producción:',count,'SHA-256:',digest(DB))
        if digest(DB)!=EXPECTED_SHA: raise RuntimeError('Hash DB final distinto')
    finally:
        conn.close()

if __name__=='__main__':
    main()
