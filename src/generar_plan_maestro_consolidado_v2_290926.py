"""Revisión v2: 11 actuadores, 241 identidades XML y 22 lazos; SQLite sólo lectura."""
import csv
import hashlib
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EX=ROOT/'exports'
DB=ROOT/'app_etiquetas/tags_ingenio.db'
OUT=EX/'plan_maestro_consolidado_v2_290926.csv'
EXPECTED='dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522'
MANUAL={'200_PIT_004','200_PIC_004','200_PV_004','200_LT_035','200_LIC_035','200_LV_035','200_FT_080','200_FIC_080','200_FV_080','250_PV_001','250_PV_002'}
MAP={'DESTILERIA_16062026':'DESTILERIA','Calderas_8_9_10_Des':'Calderas_8_9_10_Desaireador','CENTRIFUGA_2_de_primera':'CENTRIFUGA_DE_PRIMERA'}
NEW=['Evidencia_XML_V2','Archivo_XML_V2','PLC_Fuente_V2','Resolucion_V2']

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def read(name):
 with (EX/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f,delimiter=';'))

def matches(text,name):
 return bool(re.search(r'(?<![A-Za-z0-9_])'+re.escape(name)+r'(?![A-Za-z0-9_])',text,re.I))

def main():
 before=sha(DB)
 if before!=EXPECTED:raise RuntimeError('DB hash fuera de baseline')
 con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
 try:
  con.execute('PRAGMA query_only=ON')
  if con.execute('PRAGMA query_only').fetchone()[0]!=1:raise RuntimeError('No query_only')
  prod={x[0]:x for x in con.execute('SELECT tag_completo,id,plc_origen,COALESCE(descripcion,\'\'),COALESCE(comentarios,\'\'),COALESCE(alias_for,\'\') FROM tags')}
  if len(prod)!=196 or not MANUAL<=prod.keys() or con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('DB inesperada')
  parent=read('plan_maestro_consolidado_290926.csv');history=read('reconciliacion_catalogo_isa_v3.csv');catalog=read('catalogo_candidatos_expansion_280926.csv')
  if len(parent)!=268 or len([r for r in history if r['Accion']=='SIN_LAZO' and r['PLC_Origen'] in MAP])!=241:raise RuntimeError('Fuentes cambiaron')
  rows=[dict(r) for r in parent]
  cols=list(rows[0])+NEW
  for r in rows:
   for k in NEW:r[k]=''
  roots={};decls={};modules={};lxs={}
  sys.path.insert(0,str(ROOT/'src'))
  from trazador_lazos_profundo import L5X
  from catalogar_candidatos_expansion_280926 import physical
  for source,target in MAP.items():
   path=ROOT/'L5X_Produccion'/(target+'.L5X')
   ctrl=ET.parse(path).getroot().find('Controller')
   if ctrl is None or ctrl.get('Name')!=target:raise RuntimeError('Controlador no coincide: '+target)
   roots[target]=ctrl
   decls[target]={('Controller',t.get('Name')):t for t in ctrl.findall('Tags/Tag')}
   for pr in ctrl.findall('Programs/Program'):
    decls[target].update({('Program:'+pr.get('Name'),t.get('Name')):t for t in pr.findall('Tags/Tag')})
   modules[target]={m.get('Name') for m in ctrl.findall('Modules/Module')}
   lxs[target]=L5X(path)
  # Identificaciones tipadas apoyadas en alias o lógica, no sólo en el nombre del pin MV.
  results={
   '700_LXV_001':('PENDIENTE','', 'FABRICA.L5X FAB_ESCALADOS/AGITADORES_JUGO_DESTIL_PID ORef ID 37; salida sin alias exacto; actuador indeterminado'),
   '300_PV_026A':('Y','300_PY_026A','Calderas_8_9_10_Desaireador.L5X C8/C8_PC_HOGAR: MV de B_C8_PC_HOGAR -> PROPORCION_AM B_C8_RELACION_VTI_NORTE -> BP_ANALOGICA:10:O.Ch6Data; VTI = ventilador de tiro inducido, no válvula'),
   '300_PV_026B':('Y','300_PY_026B','Calderas_8_9_10_Desaireador.L5X C8/C8_PC_HOGAR: MV -> PROPORCION_AM B_C8_RELACION_VTI_SUR -> BP_ANALOGICA:10:O.Ch7Data; VTI motor'),
   '300_PV_027A':('Y','300_PY_027A','Calderas_8_9_10_Desaireador.L5X C10/C10_PC_HOGAR: MV -> PROPORCION_AM B_C10_RELACION_VTI_ESTE -> BP_ANALOGICA:12:O.Ch3Data; VTI motor'),
   '300_PV_027B':('Y','300_PY_027B','Calderas_8_9_10_Desaireador.L5X C10/C10_PC_HOGAR: MV -> PROPORCION_AM B_C10_RELACION_VTI_OESTE -> BP_ANALOGICA:12:O.Ch4Data; VTI motor'),
   '300_LY_028A':('Y','300_LY_028A','Calderas_8_9_10_Desaireador.L5X MainProgram/PID_NIVEL: CONTROL_NIVEL PID_CONTROL_NIVEL_BBA_AGUA_CENIZA MV -> BP_DIGITALES:1:O.Ch6Data; BBA/motor, no válvula'),
   '300_LY_028B':('Y','300_LY_028B','Calderas_8_9_10_Desaireador.L5X MainProgram/PID_NIVEL: CONTROL_NIVEL PID_CONTROL_NIVEL_BBA_AGUA_CENIZA MV -> BP_DIGITALES:1:O.Ch7Data; BBA/motor, no válvula'),
   '250_PV_004':('PENDIENTE','','DIBACCO.L5X MainProgram/PID ORef 11 Local:14:O.Ch6Data; MV_VALV_NC sin alias exacto de válvula'),
   '400_PV_003':('PENDIENTE','','FABRICA.L5X SULFO_ENCALADO/PID ORef 51 SULFO_ENCALADO:7:O.Ch[0].Data; MV_VALV_NC sin alias exacto'),
   '700_PV_002':('PENDIENTE','','FABRICA.L5X FAB_CCV/CCV_PC_ALTA_ESCAPE ORef 22 ISLA_FAB_AI:13:O.Ch[6].Data; alias exacto EVAP_S13_LCD_MELADO_5TO_EFE contradice función/área propuesta'),
   '400_PV_004':('V','400_PV_004','FABRICA.L5X FAB_CCV/CCV_PC_ALTA_ESCAPE ORef 23 SULFO_ENCALADO:8:O.Ch7Data; alias exacto Slot3_PV_VAL_CTROL_LT_J_ENCALADO; válvula PV; variable P vs referencia LT requiere revisión separada'),
  }
  tentative=[r for r in rows if r['Estado_Maestro']=='CANDIDATO_FUNCION_FINAL_REVISAR']
  if {r['Tag_Destino_Efectivo'] for r in tentative}!=set(results):raise RuntimeError('11 actuadores cambiaron')
  for r in tentative:
   t=r['Tag_Destino_Efectivo'];kind,new,ev=results[t];addr=r['Direccion_Modulo_Efectiva']
   plc=('Calderas_8_9_10_Desaireador' if t.startswith('300_') else 'DIBACCO' if t.startswith('250_') else 'FABRICA')
   # La evidencia debe apuntar al mismo canal literal en XML.
   ctrl=roots.get(plc)
   if ctrl is None:
    path=ROOT/'L5X_Produccion'/(plc+'.L5X');ctrl=ET.parse(path).getroot().find('Controller');roots[plc]=ctrl
   refs=[x for x in ctrl.findall('.//*[@Operand]') if x.get('Operand')==addr]
   if not refs:raise RuntimeError('Dirección no existe como operand XML: '+addr)
   r['Evidencia_XML_V2']=ev;r['Archivo_XML_V2']='L5X_Produccion/'+plc+'.L5X';r['PLC_Fuente_V2']=plc;r['Resolucion_V2']=kind
   if kind!='PENDIENTE':
    if new:r['Tag_Destino_Efectivo']=new
    r['Estado_Maestro']='NO_INSERTAR_REVISION' if t!='400_PV_004' else 'REVISION_VARIABLE_CONFLICTO'
    r['Nota_Maestra']+='; tipo final confirmado por alias/uso FBD (sin prueba runtime)'
   else:r['Estado_Maestro']='REVISION_ACTUADOR_NO_CONFIRMADO';r['Nota_Maestra']+='; no cambiar función sin evidencia del elemento'
  # Cruzar las 241 identidades con declaración EXACTA (PLC, scope, Name), y canal válido.
  sourced=[];audit=Counter();seen_sources=defaultdict(list)
  for h in history:
   if h['Accion']!='SIN_LAZO' or h['PLC_Origen'] not in MAP:continue
   target=MAP[h['PLC_Origen']];ident=h['Tag_Original_PLC'];scope=h['Alcance'];decl=decls[target].get((scope,ident));audit['source']+=1
   if decl is None:audit['no_exact']+=1;continue
   audit['exact']+=1
   alias=(decl.get('AliasFor') or '').strip()
   if alias:addresses=[alias];via='AliasFor de declaración exacta'
   else:
    trace=lxs[target].resolver_terminal(ident)
    addresses=[addr for _,addr,_ in trace['fisicos']] if trace['estado']=='FISICO' else []
    via='writer a terminal: '+' <- '.join(trace['camino'][:5])
   dirs={a:physical(a,modules[target]) for a in addresses}
   valid={a:d for a,d in dirs.items() if d}
   if len(valid)!=1 or len(set(addresses))!=1:
    audit['sin_canal_unico']+=1;continue
   addr,direction=next(iter(valid.items()));audit['canal_unico']+=1
   sourced.append((h,target,ident,addr,direction,via,bool(alias)))
   seen_sources[(target,addr)].append(ident)
  # Reservas: producción y ambos planes; tags por área+N antes de asignar nuevos.
  occupied=defaultdict(set);destinations={}
  for r in rows:
   if r['Operacion_Efectiva'] in ('INSERT','UPDATE'):
    t=r['Tag_Destino_Efectivo'];destinations.setdefault(t,[]).append(r)
  for t in set(prod)|set(destinations):
   mm=re.match(r'^(\d{3})_[A-Z]+_(\d{3})[A-Z]?$',t or '')
   if mm:occupied[mm[1]].add(int(mm[2]))
  def free(area):
   for n in range(1,1000):
    if n not in occupied[area]:occupied[area].add(n);return n
   raise RuntimeError('No libre: '+area)
  proposed_channels={(r['PLC_Fuente_V2'] or r.get('PLC',''),r['Direccion_Modulo_Efectiva']) for r in rows if r['Operacion_Efectiva']=='INSERT' and r['Direccion_Modulo_Efectiva']}
  catalog_pid={(x['PLC'],x['Direccion_Modulo']) for x in catalog if x['Es_Lazo_PID']=='SI'}
  catalog_prod={(x['PLC'],x['Direccion_Modulo']) for x in catalog if x['Coincidencia_Produccion']}
  all_prod_text=defaultdict(list)
  for tag,(_,_,plc,desc,comm,alias) in prod.items():all_prod_text[plc].append((tag,' '.join((desc,comm,alias))))
  chosen=[];reject=Counter()
  for h,plc,name,addr,direction,via,explicit in sourced:
   # Los miembros calculados de un canal no son instrumentos físicos individuales.
   if not explicit and not re.match(r'^(?:TT_CUBA_\d+|DES_2_S1_LT_TK_ALCOHOL_\d+)$',name):reject['derivado_no_instrumento']+=1;continue
   if len(set(seen_sources[(plc,addr)]))>1:
    # La única excepción segura: alias e interno con el mismo nombre físico tras Slot_.
    normalized={re.sub(r'^Slot_','',z,flags=re.I) for z in seen_sources[(plc,addr)]}
    if len(normalized)!=1:reject['canal_compartido']+=1;continue
   if (plc,addr) in catalog_pid or (plc,addr) in catalog_prod or (plc,addr) in proposed_channels:
    reject['canal_en_lazo_o_plan']+=1;continue
   if h['PLC_Origen']=='DESTILERIA_16062026':
    if h['Alcance']=='Controller' and name.startswith('Slot_FT_') and direction=='I':area='200';function='FT';evar='F';why='PLC DESTILERIA, alias Slot_FT de fermentación'
    elif name.startswith('TT_CUBA_') and direction=='I':area='200';function='TT';evar='T';why='PLC DESTILERIA, identidad TT_CUBA'
    else:reject['area_o_variable_no_probada']+=1;continue
   elif h['PLC_Origen']=='Calderas_8_9_10_Des':
    if re.fullmatch(r'DES_2_S1_LT_TK_ALCOHOL_\d+',name) and direction=='I':area='200';function='LT';evar='L';why='Desaireador_2 y TK_ALCOHOL; área Destilería 200'
    elif re.fullmatch(r'DES_2_S2_[IS]T_BBA_\d+_AGUA_DESTI_(?:ESTE|OESTE)',name) and direction=='I':
     area='200';evar=name.split('_S2_')[1][0];function=evar+'T';why='AGUA_DESTI; área Destilería 200'
    else:reject['area_o_variable_no_probada']+=1;continue
   else:reject['centrifuga_sin_canal_instrumental']+=1;continue
   if any(matches(text,name) or (name.startswith('Slot_') and matches(text,name[5:])) or addr in text for _,text in all_prod_text[plc]):
    reject['identidad_ya_produccion']+=1;continue
   chosen.append((plc,name,addr,area,evar,function,why,via,h['PLC_Origen']))
  if audit['source']!=241:raise RuntimeError('No se analizaron 241 identidades')
  for plc,name,addr,area,var,fn,why,via,source in sorted(chosen):
   n=free(area);tag=f'{area}_{fn}_{n:03d}'
   template=dict.fromkeys(cols,'')
   template.update({'Fuente_Fila':'RESCATE_XML_241','Bloque_Maestro':'MONITOREO_SIN_LAZO','Operacion_Efectiva':'INSERT','Tag_Destino_Efectivo':tag,'Area_Efectiva':area,'Variable_Efectiva':var,'Numero_Efectivo':str(n),'Identidad_PLC_Efectiva':name,'Direccion_Modulo_Efectiva':addr,'Estado_Maestro':'NO_INSERTAR_REVISION','Nota_Maestra':'Sensor físico propuesto; '+why+'; verificar en campo','Escritura_SQLite':'NO','Archivo_XML_V2':'L5X_Produccion/'+plc+'.L5X','PLC_Fuente_V2':source,'Evidencia_XML_V2':f'Controller Name={plc}; {via}; Alias/identidad {name} -> {addr}','Resolucion_V2':'CANAL_UNICO'})
   rows.append(template)
  # El usuario nombró 22 grupos; verificar su estado mediante el trazador dirigido.
  wanted=['B_C8_LC_DOMO','B_C9_LC_DOMO','B_C10_LC_DOMO','B_C10_PC_VAPOR','PID_CONTROL_NIVEL_TK_CONDENSADO','PID_CONTROL_NIVEL_1ER_EFECTO','PID_CONTROL_QUIEBRE_VACIO','PID_Ctrol_Grado_Alcohol','B_Ctrl_VALV_CAUDAL_MELADO','CONTROL_NIVEL_BBA_DESTILADORA','B_LC_CAJA_6','B_LC_CAJA_11','B_LC_COND_CAJA_6','B_LC_COND_CAJA_7_8','B_PC_VG1R_FAB','B_PC_ESC_DEST','CONTROL_CAUDAL_JUGO_DEST','CONTROL_NIVEL_TK_SUR','B_Ctrl_JUGO_1ERA_EXTRACCION','CONTROL_CINTA_R_2_02','PID_PULMON_LAVADO','PID_TK_AGUA_LIMPIA']
  front=read('frontera_controladores_con_invocacion_xml.csv');fr=[r for r in front if r['Instancia'] in wanted]
  if len(fr)!=22 or len({r['Instancia'] for r in fr})!=22:raise RuntimeError('22 instancias frontera no coinciden')
  closable=0;already=0
  cache={}
  for r in fr:
   plc=r['PLC'];cache.setdefault(plc,L5X(ROOT/'L5X_Produccion'/(plc+'.L5X')))
   z=cache[plc].analizar(plc,r['Program'],r['Routine'],r['Instancia'])
   instance=r['Instancia']
   if instance=='B_Ctrl_JUGO_1ERA_EXTRACCION':
    old='100_LXV_032';new='100_LY_032';address='VDF_1ERA_EXTRACCION_SUR:O.Reference'
    if 'Local:7:I.Ch[5].Data' not in z['entrada_fisica'] or address not in z['salida_fisica'] or not all(t in prod for t in ('100_LT_032','100_LIC_032',old)) or 'PowerFlex 753' not in z['salida_fisica']:raise RuntimeError('Lazo JUGO cambió')
    closable+=1;already+=1
    update=dict.fromkeys(cols,'')
    update.update({'Fuente_Fila':'TRAZADO_XML_FRONTERA_22','Bloque_Maestro':'CORRECCION_FINAL_FRONTERA','Operacion_Efectiva':'UPDATE','Tag_Origen_Efectivo':old,'Tag_Destino_Efectivo':new,'ID_Origen_Efectivo':str(prod[old][1]),'Area_Efectiva':'100','Variable_Efectiva':'L','Numero_Efectivo':'32','Identidad_PLC_Efectiva':instance,'Direccion_Modulo_Efectiva':address,'Estado_Maestro':'NO_INSERTAR_REVISION','Nota_Maestra':'Cambio de función propuesto: salida PowerFlex 753 (variador), no válvula. LT/LIC de lazo 032 intactos.','Escritura_SQLite':'NO','PLC_Fuente_V2':plc,'Archivo_XML_V2':'L5X_Produccion/'+plc+'.L5X','Evidencia_XML_V2':z['entrada_camino']+'; '+z['salida_camino'],'Resolucion_V2':'CERRADO_YA_PRODUCCION_CORREGIR_FUNCION'})
    rows.append(update)
   if instance=='B_C10_PC_VAPOR':
    addresses=[x.split(' (',1)[0] for x in z['salida_fisica'].split(' | ')]
    old='300_PV_044'
    if len(addresses)!=6 or len(set(addresses))!=6 or not all(a.startswith('Cal_10_Dosificador_') and ':O.' in a for a in addresses) or 'BP_ANALOGICA:3:I.Ch[4].Data' not in z['entrada_fisica'] or z['entrada_operando']!='C10_PT_DOMO_CALDERA' or not all(t in prod for t in ('300_PT_044','300_PIC_044',old)) or not all('PowerFlex 525' in x for x in z['salida_fisica'].split(' | ')):raise RuntimeError('C10_VAPOR cambió')
    closable+=1;already+=1
    for suffix,addr in zip('ABCDEF',sorted(addresses)):
     item=dict.fromkeys(cols,'')
     item.update({'Fuente_Fila':'TRAZADO_XML_FRONTERA_22','Bloque_Maestro':'DESGLOSE_FINAL_FRONTERA','Operacion_Efectiva':'UPDATE' if suffix=='A' else 'INSERT','Tag_Origen_Efectivo':old if suffix=='A' else '','Tag_Destino_Efectivo':'300_PY_044'+suffix,'ID_Origen_Efectivo':str(prod[old][1]) if suffix=='A' else '','Area_Efectiva':'300','Variable_Efectiva':'P','Numero_Efectivo':'44','Identidad_PLC_Efectiva':instance,'Direccion_Modulo_Efectiva':addr,'Estado_Maestro':'NO_INSERTAR_REVISION','Nota_Maestra':'Desglose candidato de seis dosificadores PowerFlex 525 en A-F; entrada PT_044 y controlador PIC_044 existentes. Verificar campo antes de aplicar.','Escritura_SQLite':'NO','PLC_Fuente_V2':plc,'Archivo_XML_V2':'L5X_Produccion/'+plc+'.L5X','Evidencia_XML_V2':z['entrada_camino']+'; '+z['salida_camino'],'Resolucion_V2':'CERRADO_YA_PRODUCCION_RAMAS_MULTIPLES'})
     rows.append(item)
   if instance=='CONTROL_NIVEL_TK_SUR' and z['salida_fisica']:
    raise RuntimeError('Área AGUA_CONDENSADA requiere revisar destino y no se numeró')
   v2=dict.fromkeys(cols,'')
   status='YA_TAGUEADO_EN_PRODUCCION_REVISAR_FUNCION' if instance in ('B_Ctrl_JUGO_1ERA_EXTRACCION','B_C10_PC_VAPOR') else 'REVISION_SIN_LAZO_NUEVO'
   note=('Grupo completo pero ya catalogado; corregir final Y en operaciones adjuntas' if instance in ('B_Ctrl_JUGO_1ERA_EXTRACCION','B_C10_PC_VAPOR') else 'Sin extremo único/variable inequívoca o ya catalogado; no crear familia nueva')
   if instance=='CONTROL_NIVEL_TK_SUR':
    note='AGUA_CONDENSADA: MV alimenta IS_BBA_NORTE_TK_SUR y IS_BBA_SUR_TK_SUR; en rutina ESCALADOS, SCL_IS_BBA_NORTE_TK_SUR Out -> AGUA_CONDENSADA:5:O.Ch01.Data y SCL_IS_BBA_SUR_TK_SUR Out -> AGUA_CONDENSADA:5:O.Ch00.Data. Dos salidas físicas demostradas, pero el destino del tanque no prueba área ISA. PENDIENTE_AREA, sin número.'
    pr=roots[plc].find("Programs/Program[@Name='AGUA_CONDENSADA']")
    rr=pr.find("Routines/Routine[@Name='ESCALADOS']") if pr is not None else None
    wires={(w.get('FromID'),w.get('FromParam'),w.get('ToID')) for w in rr.findall('.//Wire')} if rr is not None else set()
    nodes={x.get('ID'):x.get('Operand') for x in rr.findall('.//*[@ID]')} if rr is not None else {}
    if not {('140','Out','127'),('143','Out','126')}<=wires or nodes.get('127')!='AGUA_CONDENSADA:5:O.Ch01.Data' or nodes.get('126')!='AGUA_CONDENSADA:5:O.Ch00.Data':raise RuntimeError('Trazado cruzado AGUA_CONDENSADA cambió')
   elif instance=='PID_Ctrol_Grado_Alcohol':note='Entrada HART secundaria y salida física visibles, pero DENSIDAD_ALCOHOL no fija variable ISA inequívoca; no numerar.'
   elif instance=='B_Ctrl_VALV_CAUDAL_MELADO':note='Par físico trazado, pero 200_FT/FIC/FV_085 ya figura en producción; salida compartida con B_Ctrl_GRADO_BRIX_JUGO. No crear segundo lazo.'
   v2.update({'Fuente_Fila':'AUDITORIA_FRONTERA_22','Bloque_Maestro':'FRONTERA_3_4_AUDITORIA','Operacion_Efectiva':'','Estado_Maestro':status,'Nota_Maestra':note,'Escritura_SQLite':'NO','PLC_Fuente_V2':plc,'Archivo_XML_V2':'L5X_Produccion/'+plc+'.L5X','Identidad_PLC_Efectiva':instance,'Evidencia_XML_V2':'PV '+z.get('entrada_operando','')+' -> '+z['entrada_fisica']+'; MV -> '+z['salida_fisica']+'; '+z['nota']})
   rows.append(v2)
  # Unión completa: cada operación tiene origen único y destino único; ningún manual cambia.
  ops=[r for r in rows if r['Operacion_Efectiva'] in ('INSERT','UPDATE','DELETE')]
  origins=defaultdict(list);dests=defaultdict(list)
  for r in ops:
   old=r['Tag_Origen_Efectivo'];new=r['Tag_Destino_Efectivo'];op=r['Operacion_Efectiva']
   if old in MANUAL or new in MANUAL:raise RuntimeError('Protegido: '+old+' '+new)
   if op in ('UPDATE','DELETE'):
    if old not in prod or str(prod[old][1])!=r['ID_Origen_Efectivo']:raise RuntimeError('ID/origen inválido '+old)
    origins[old].append(r)
   if op in ('UPDATE','INSERT'):
    if not re.fullmatch(r'\d{3}_[A-Z]+_\d{3}[A-Z]?',new):raise RuntimeError('Tag no válido: '+new)
    dests[new].append(r)
  if any(len(z)!=1 for z in origins.values()) or any(len(z)!=1 for z in dests.values()):raise RuntimeError('Origen/destino duplicado')
  if any(t in prod and t not in origins for t in dests):raise RuntimeError('Destino colisiona con producción')
  if rows[:len(parent)] and any({k:r[k] for k in parent[i] if k!='Tag_Destino_Efectivo'}.get('Operacion_Efectiva')!=parent[i]['Operacion_Efectiva'] for i,r in enumerate(rows[:len(parent)])):raise RuntimeError('Operación heredada modificada')
  if sha(DB)!=before:raise RuntimeError('DB cambió antes de salida')
  with OUT.open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,cols,delimiter=';',lineterminator='\n');w.writeheader();w.writerows(rows)
  parsed=read(OUT)
  if parsed!=rows or any(x['Escritura_SQLite']!='NO' for x in parsed):raise RuntimeError('CSV no reproducible')
  counts=Counter(r['Operacion_Efectiva'] for r in parsed)
  print('ACTUADORES confirmados',sum(kind!='PENDIENTE' for kind,_,_ in results.values()),'pendientes',sum(kind=='PENDIENTE' for kind,_,_ in results.values()))
  print('241 SIN_LAZO',dict(audit),'rescatados',len(chosen),'descartes',dict(reject))
  print('FRONTERA 22; cierre topológico defendible',closable,'ya en producción',already,'altas nuevas',0)
  print('BALANCE INSERT',counts['INSERT'],'UPDATE',counts['UPDATE'],'DELETE',counts['DELETE'],'TOTAL PROYECTADO',len(prod)+counts['INSERT']-counts['DELETE'])
  print('CSV filas',len(rows),'SHA-256',sha(OUT))
  print('DB',len(prod),'SHA-256 antes/después',before,sha(DB),'mode=ro query_only=ON; cero escrituras SQLite')
  if sha(DB)!=before:raise RuntimeError('DB cambió tras emitir')
 finally:con.close()

if __name__=='__main__':main()
