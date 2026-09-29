"""Plan v3 candidato: evidencia dirigida XML, auditoría de exclusiones y SQLite RO."""
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
OUT=EX/'plan_maestro_consolidado_v3_290926.csv'
EXPECTED_DB='dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522'
EXPECTED_V2='f4d49799caf63baf9c2a43bc05b9249414ed17bd701d217378fac8e7122ea9a3'
PROTECTED={'200_PIT_004','200_PIC_004','200_PV_004','200_LT_035','200_LIC_035','200_LV_035','200_FT_080','200_FIC_080','200_FV_080','250_PV_001','250_PV_002'}
MAP={'DESTILERIA_16062026':'DESTILERIA','Calderas_8_9_10_Des':'Calderas_8_9_10_Desaireador','CENTRIFUGA_2_de_primera':'CENTRIFUGA_DE_PRIMERA'}
EXTRA=['Evidencia_XML_V3','Estado_Auditoria_V3']

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def read(name):
 with (EX/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f,delimiter=';'))

def main():
 before=digest(DB)
 if before!=EXPECTED_DB or digest(EX/'plan_maestro_consolidado_v2_290926.csv')!=EXPECTED_V2:raise RuntimeError('Baseline cambiado; no emitir v3')
 con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
 try:
  con.execute('PRAGMA query_only=ON')
  if con.execute('PRAGMA query_only').fetchone()[0]!=1:raise RuntimeError('query_only no activo')
  prod={r[0]:r for r in con.execute('SELECT tag_completo,id,plc_origen,COALESCE(descripcion,\'\'),COALESCE(comentarios,\'\'),COALESCE(alias_for,\'\') FROM tags')}
  if len(prod)!=196 or not PROTECTED<=prod.keys() or con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Base inesperada')
  original=read('plan_maestro_consolidado_v2_290926.csv')
  hist=read('reconciliacion_catalogo_isa_v3.csv')
  catalog=read('catalogo_candidatos_expansion_280926.csv')
  if len(original)!=316 or len([x for x in hist if x['Accion']=='SIN_LAZO' and x['PLC_Origen'] in MAP])!=241:raise RuntimeError('Universo modificado')
  cols=list(original[0])+EXTRA
  rows=[]
  for x in original:
   item=dict(x);item.update({k:'' for k in EXTRA});rows.append(item)
  def add(source,block,op='',old='',new='',area='',var='',number='',identity='',address='',status='NO_INSERTAR_REVISION',note='',plc='',evidence='',id_old=''):
   x=dict.fromkeys(cols,'')
   x.update({'Fuente_Fila':source,'Bloque_Maestro':block,'Operacion_Efectiva':op,'Tag_Origen_Efectivo':old,'Tag_Destino_Efectivo':new,'ID_Origen_Efectivo':str(id_old),'Area_Efectiva':area,'Variable_Efectiva':var,'Numero_Efectivo':str(number),'Identidad_PLC_Efectiva':identity,'Direccion_Modulo_Efectiva':address,'Estado_Maestro':status,'Nota_Maestra':note,'PLC_Fuente_V2':plc,'Evidencia_XML_V3':evidence,'Estado_Auditoria_V3':status,'Escritura_SQLite':'NO'})
   rows.append(x);return x
  occupied=defaultdict(set)
  for name in set(prod)|{r['Tag_Destino_Efectivo'] for r in rows}|{r['Tag_Origen_Efectivo'] for r in rows}:
   m=re.fullmatch(r'(\d{3})_[A-Z]+_(\d{3})[A-Z]?',name or '')
   if m:occupied[m[1]].add(int(m[2]))
  def free(area):
   for i in range(1,1000):
    if i not in occupied[area]:occupied[area].add(i);return i
   raise RuntimeError('Sin número libre en '+area)
  sys.path.insert(0,str(ROOT/'src'))
  from trazador_lazos_profundo import L5X
  from catalogar_candidatos_expansion_280926 import physical
  cache={}
  def xml(plc):
   if plc not in cache:
    path=ROOT/'L5X_Produccion'/(plc+'.L5X');root=ET.parse(path).getroot().find('Controller')
    if root is None or root.get('Name')!=plc:raise RuntimeError('XML no corresponde: '+plc)
    cache[plc]=(root,L5X(path),{m.get('Name') for m in root.findall('Modules/Module')})
   return cache[plc]
  # Definiciones de ingeniería: el campo PV/Y se autoriza aquí, no se imputa al XML.
  to_confirm={'250_PV_004':('DIBACCO','MainProgram','PID','Ctrol_Presion_Escape_Tamiz','Local:14:O.Ch6Data'),'400_PV_003':('FABRICA','SULFO_ENCALADO','PID','CONTROL_PRESION_BIO','SULFO_ENCALADO:7:O.Ch[0].Data')}
  for t,(plc,program,routine,instance,address) in to_confirm.items():
   result=[r for r in rows if r['Tag_Destino_Efectivo']==t and r['Estado_Maestro']=='REVISION_ACTUADOR_NO_CONFIRMADO']
   if len(result)!=1:raise RuntimeError('Final pendiente ausente '+t)
   root,_,_=xml(plc)
   rr=root.find(f"Programs/Program[@Name='{program}']/Routines/Routine[@Name='{routine}']")
   if rr is None:raise RuntimeError('Rutina ausente '+t)
   valid=[]
   for sh in rr.findall('.//Sheet'):
    ns={n.get('ID'):n for n in sh if n.get('ID')}
    valid.extend(ns.get(w.get('FromID')) is not None and ns[w.get('FromID')].get('Operand')==instance and w.get('FromParam')=='MV_VALV_NC' and ns.get(w.get('ToID')) is not None and ns[w.get('ToID')].get('Operand')==address for w in sh.findall('Wire'))
   if not any(valid):raise RuntimeError('MV_VALV_NC no alimenta ORef '+t)
   result[0]['Estado_Maestro']='NO_INSERTAR_REVISION'
   result[0]['Nota_Maestra']+='; válvula PV adoptada por definición de ingeniería 29/09; MV_VALV_NC es pin lógico, no prueba de campo'
   result[0]['Evidencia_XML_V3']=f'{plc}.L5X: AOI MV_VALV_NC -> {address}; función V confirmada por ingeniería, no por alias físico'
   result[0]['Estado_Auditoria_V3']='INGENIERIA_FUNCION_V'
  mieles=[r for r in rows if r['Tag_Destino_Efectivo']=='700_LXV_001' and r['Estado_Maestro']=='REVISION_ACTUADOR_NO_CONFIRMADO']
  if len(mieles)!=1:raise RuntimeError('Mieles ausente')
  fab,_,_=xml('FABRICA')
  routine=fab.find("Programs/Program[@Name='FAB_ESCALADOS']/Routines/Routine[@Name='AGITADORES_JUGO_DESTIL_PID']")
  if routine is None or not any(w.get('FromID')=='49' and w.get('FromParam')=='MV_VALV_NC' and w.get('ToID')=='37' for w in routine.findall('.//Wire')) or not any(x.get('ID')=='37' and x.get('Operand')=='FLEX5000_MIELES:2:O.Ch00.Data' for x in routine.findall('.//*[@Operand]')):raise RuntimeError('Pin mieles cambió')
  mieles[0]['Evidencia_XML_V3']='FABRICA.L5X FAB_ESCALADOS/AGITADORES_JUGO_DESTIL_PID: CONTROL_NIVEL_TK_MIEL1 ID49 MV_VALV_NC -> ORef ID37 FLEX5000_MIELES:2:O.Ch00.Data; el mismo AOI deriva también a WEG_MIEL; no hay alias que identifique actuador'
  mieles[0]['Estado_Auditoria_V3']='PENDIENTE_TIPO_CAMPO'
  mieles[0]['Nota_Maestra']+='; pin MV_VALV_NC no resuelve válvula vs agitador/motor WEG; no promover función'
  # Dos lazos autorizados expresamente; no duplicar canales ni números de v2.
  lookup={(r['PLC'],r['Direccion_Modulo']) for r in catalog if r['Es_Lazo_PID']=='SI' and r['Coincidencia_Produccion']}
  fablx=xml('FABRICA')[1];destlx=xml('DESTILERIA')[1]
  m=destlx.analizar('DESTILERIA','JW','PID_JW','PID_Ctrol_Grado_Alcohol')
  if m['entrada_operando']!='DENSIDAD_ALCOHOL' or 'fermerntacion2022_islas:2:I.HART.Ch4SV' not in m['entrada_fisica'] or 'fermerntacion2022_islas:8:O.Ch4Data' not in m['salida_fisica']:raise RuntimeError('Densidad no trazada')
  # Revalidar específicamente el pin In del SCL: constantes de escala no cuentan como fuente.
  ctrl=xml('DESTILERIA')[0]
  sheets=ctrl.find("Programs/Program[@Name='JW']/Routines/Routine[@Name='ESCLADOS_PT_FT_LT_TT']")
  if sheets is None:raise RuntimeError('No hay rutina de escalado de densidad')
  addr='fermerntacion2022_islas:2:I.HART.Ch4SV'
  nodes={x.get('ID'):x for x in sheets.findall('.//*[@ID]')}
  wires={(w.get('FromID'),w.get('FromParam'),w.get('ToID'),w.get('ToParam')) for w in sheets.findall('.//Wire')}
  if not {('103',None,'116','In'),('116','Out','104',None)}<=wires or nodes['103'].get('Operand')!=addr or nodes['116'].get('Operand')!='SCL_DENSIDAD_ALCOHOL' or nodes['104'].get('Operand')!='DENSIDAD_ALCOHOL':raise RuntimeError('Cadena HART -> SCL.In -> DENSIDAD_ALCOHOL no demostrada')
  n=free('200')
  for role,fn,identity,address in [('Entrada','DT','DENSIDAD_ALCOHOL',addr),('Controlador','DIC','PID_Ctrol_Grado_Alcohol',''),('Salida','DV','fermerntacion2022_islas:8:O.Ch4Data','fermerntacion2022_islas:8:O.Ch4Data')]:
   add('INGENIERIA_290926_DENSIDAD','LAZO_NUEVO_DENSIDAD','INSERT',new=f'200_{fn}_{n:03d}',area='200',var='D',number=n,identity=identity,address=address,plc='DESTILERIA',status='NO_INSERTAR_REVISION',note='Área 200 y D autorizadas por ingeniería; función final V designada por ingeniería, confirmar dispositivo en campo',evidence=m['entrada_camino']+'; '+m['salida_camino'])
  m=fablx.analizar('FABRICA','AGUA_CONDENSADA','CONTROL_NIVEL','CONTROL_NIVEL_TK_SUR')
  if 'AGUA_CONDENSADA:1:I.Ch06.Data' not in m['entrada_fisica']:raise RuntimeError('Entrada TK_SUR cambió')
  rr=fab.find("Programs/Program[@Name='AGUA_CONDENSADA']/Routines/Routine[@Name='ESCALADOS']")
  wires={(w.get('FromID'),w.get('FromParam'),w.get('ToID')) for w in rr.findall('.//Wire')}
  operands={x.get('ID'):x.get('Operand') for x in rr.findall('.//*[@ID]')}
  if not {('140','Out','127'),('143','Out','126')}<=wires or operands.get('127')!='AGUA_CONDENSADA:5:O.Ch01.Data' or operands.get('126')!='AGUA_CONDENSADA:5:O.Ch00.Data':raise RuntimeError('Dos salidas TK_SUR no probadas')
  n500=free('500')
  for fn,identity,address in [('LT','LT_TK_SUR','AGUA_CONDENSADA:1:I.Ch06.Data'),('LIC','CONTROL_NIVEL_TK_SUR',''),('LYA','IS_BBA_NORTE_TK_SUR','AGUA_CONDENSADA:5:O.Ch01.Data'),('LYB','IS_BBA_SUR_TK_SUR','AGUA_CONDENSADA:5:O.Ch00.Data')]:
   # LY+A/B es función Y con sufijo de rama, no dos funciones distintas.
   final=fn if fn in ('LT','LIC') else fn[:2]+'_'+''
   tag=f'500_{fn}_{n500:03d}' if fn in ('LT','LIC') else f'500_LY_{n500:03d}{fn[-1]}'
   add('INGENIERIA_290926_TK_SUR','LAZO_NUEVO_TK_SUR','INSERT',new=tag,area='500',var='L',number=n500,identity=identity,address=address,plc='FABRICA',status='NO_INSERTAR_REVISION',note='Área 500 y función Y confirmadas por ingeniería; dos canales de salida trazados cruzando ESCALADOS',evidence='FABRICA.L5X AGUA_CONDENSADA/CONTROL_NIVEL -> IS_BBA_NORTE/SUR_TK_SUR; ESCALADOS SCL_... Out -> ORef Ch01/Ch00')
  # El v2 conserva sus filas de auditoría, pero se marca resolución sin doble conteo.
  for r in rows:
   if r['Fuente_Fila']=='AUDITORIA_FRONTERA_22' and r['Identidad_PLC_Efectiva'] in ('PID_Ctrol_Grado_Alcohol','CONTROL_NIVEL_TK_SUR'):
    r['Estado_Maestro']='SUPERADO_POR_LAZO_V3'
    r['Nota_Maestra']+='; completado como grupo candidato v3 por decisión de ingeniería; fila de auditoría no operacional'
    r['Estado_Auditoria_V3']='RESUELTO_INGENIERIA'
  # Señales independientes: elegir el primer valor de proceso tras el escalado,
  # nunca un totalizador ni un duplicado de un canal ya asignado.
  MONITOR_DEST=['FT_JUGO','LT_TK_VINO','TT_MOSTO','FT_CAUDAL_ALCOHOL_m3','PT_VAPOR_ENTRADA']
  MONITOR_DEST += [f'TT_{i}' for i in (101,102,103,104,105,107,109,201,202,203,204,205,206,208,209)]
  MONITOR_CAL=['TT_CHIMENEA_CAL_8','TT_CHIMENEA_CAL_9','TT_CHIMENEA_CAL_10_ESTE','TT_CHIMENEA_CAL_10_OESTE']
  sourcehist={(h['PLC_Origen'],h['Tag_Original_PLC']):h for h in hist if h['Accion']=='SIN_LAZO'}
  planned_channels={(r['PLC_Fuente_V2'],r['Direccion_Modulo_Efectiva']) for r in rows if r['Operacion_Efectiva'] in ('INSERT','UPDATE') and r['Direccion_Modulo_Efectiva']}
  if len(sourcehist)!=len([h for h in hist if h['Accion']=='SIN_LAZO']):raise RuntimeError('Histórico con identidades duplicadas')
  marked={}
  for source,prefixes,area in (('DESTILERIA_16062026',MONITOR_DEST,'200'),('Calderas_8_9_10_Des',MONITOR_CAL,'300')):
   target=MAP[source];root,lx,modules=xml(target)
   for prefix in prefixes:
    candidates=[h for (plc,name),h in sourcehist.items() if plc==source and (name==prefix if prefix in MONITOR_DEST[:5] else bool(re.fullmatch(re.escape(prefix)+r'(?:_[A-Z][A-Z0-9_]*)?',name)))]
    if len(candidates)!=1:raise RuntimeError('Selección histórica ambigua: '+prefix)
    h=candidates[0];name=h['Tag_Original_PLC']
    state=lx.resolver_terminal(name)
    raw=sorted({a for _,a,_ in state['fisicos'] if physical(a,modules) and ':I.' in a})
    if len(raw)!=1:raise RuntimeError('Monitor sin una sola entrada: '+name+' '+str(raw))
    addr=raw[0]
    if (target,addr) in planned_channels:raise RuntimeError('Canal ya planificado '+name)
    actual='FT_ALCOHOL_JW' if name=='FT_CAUDAL_ALCOHOL_m3' else name
    if actual=='FT_ALCOHOL_JW':
     sh=root.find("Programs/Program[@Name='JW']/Routines/Routine[@Name='ESCLADOS_PT_FT_LT_TT']")
     ed={(w.get('FromID'),w.get('FromParam'),w.get('ToID'),w.get('ToParam')) for w in sh.findall('.//Wire')}
     nd={n.get('ID'):n.get('Operand') for n in sh.findall('.//*[@ID]')}
     if not any(nd.get(a)==addr and nd.get(b)=='B_CAUDAL_ALCOHOL1' and pin=='In' for a,_,b,pin in ed) or not any(nd.get(a)=='B_CAUDAL_ALCOHOL1' and pin=='Out' and nd.get(b)=='FT_ALCOHOL_JW' for a,pin,b,_ in ed):raise RuntimeError('Primer escalado no probado FT_ALCOHOL_JW')
    var=prefix[0] if prefix.startswith(('FT_','LT_','TT_','PT_')) else None
    if var not in ('F','L','T','P'):raise RuntimeError('Variable no probada '+name)
    tag=f'{area}_{var}T_{free(area):03d}'
    status='NO_INSERTAR_REVISION'
    add('RESCATE_XML_241_V3','MONITOREO_SIN_LAZO_V3','INSERT',new=tag,area=area,var=var,number=int(tag.split('_')[-1]),identity=actual,address=addr,plc=target,status=status,note=f'Entrada física única; primera PV={actual}; identidad histórica {name}; propuesta para revisión de campo/área y pertenencia a lazo, no alta',evidence=f'{target}.L5X {h["Alcance"]}.{name} → {state["camino"]}; módulo {addr}; área {area} por programa/sector')
    planned_channels.add((target,addr));marked[(source,name)]=('RESCATADO_MONITOREO_V3',actual,tag)
  if len(marked)!=24:raise RuntimeError('No hubo 24 señales distintas')
  # USINA no declara AliasFor, pero sí MOV físico -> espejo -> SCL.In -> SCL.Out.
  usroot,_,usmodules=xml('USINA_LA_FLORIDA')
  usprog=usroot.find("Programs/Program[@Name='MainProgram']")
  ent=usprog.find("Routines/Routine[@Name='ENTRADA_TURBINA']")
  esp=usprog.find("Routines/Routine[@Name='ESPELHO_ENTRADAS']")
  movs=defaultdict(set)
  for text in esp.findall('.//Rung/Text'):
   for raw,idx in re.findall(r'MOV\(([^,]+),ESPELHO_AI0\[(\d+)\]\)',text.text or ''):movs[int(idx)].add(raw)
  unit={};dupe=[]
  for sh in ent.findall('.//Sheet'):
   nodes={x.get('ID'):x for x in sh if x.get('ID')}
   wires=sh.findall('Wire')
   for b in sh.findall('Block'):
    name=b.get('Operand') or ''
    if b.get('Type')!='SCL' or not name.startswith(('PRESSAO_','PRESION_VAP_CAMARA','TEMP_','RPM_')):continue
    ins=[nodes[w.get('FromID')].get('Operand') for w in wires if w.get('ToID')==b.get('ID') and w.get('ToParam')=='In']
    outs=[nodes[w.get('ToID')].get('Operand') for w in wires if w.get('FromID')==b.get('ID') and w.get('FromParam')=='Out']
    if len(ins)!=1 or len(outs)!=1:raise RuntimeError('SCL USINA ambiguo '+name)
    a=re.fullmatch(r'ESPELHO_AI0\[(\d+)\]',ins[0] or '')
    if not a or len(movs[int(a[1])])!=1:raise RuntimeError('Espejo USINA no único '+name)
    addr=next(iter(movs[int(a[1])]))
    if not physical(addr,usmodules) or ':I.' not in addr:raise RuntimeError('Módulo USINA no válido '+addr)
    if addr in unit:dupe.append((name,unit[addr][0],addr));continue
    unit[addr]=(name,outs[0],int(a[1]),addr)
  if len(unit)!=18 or len(dupe)!=1 or set(dupe[0][:2])!={'RPM_GERADOR_5','RPM_PRESYS'}:raise RuntimeError('Inventario USINA no corresponde '+str((len(unit),dupe)))
  for name,pv,index,addr in sorted(unit.values(),key=lambda v:v[2]):
   var='P' if name.startswith(('PRESSAO_','PRESION_')) else 'T' if name.startswith('TEMP_') else 'S'
   if ( 'USINA_LA_FLORIDA',addr) in planned_channels:raise RuntimeError('Canal USINA duplicado '+addr)
   number=free('900');tag=f'900_{var}T_{number:03d}'
   add('TRAZA_MOV_SCL_USINA','MONITOREO_SIN_LAZO_USINA','INSERT',new=tag,area='900',var=var,number=number,identity=pv,address=addr,plc='USINA_LA_FLORIDA',status='NO_INSERTAR_REVISION',note=f'{name} es SCL de medición; área 900 Usina según manual; índice ESPELHO_AI0[{index}]; confirmar instrumento en campo',evidence=f'USINA_LA_FLORIDA.L5X MainProgram/ESPELHO_ENTRADAS MOV({addr},ESPELHO_AI0[{index}]); ENTRADA_TURBINA ESPELHO_AI0[{index}] → {name}.In → {name}.Out → {pv}')
   planned_channels.add(('USINA_LA_FLORIDA',addr))
  # Cinco pares Entrada+Controlador sin final inequívoco. No se presentan como
  # lazos completos y conservan el bloqueo NO_INSERTAR_REVISION.
  pairs=[
   ('FABRICA','FAB_EVAP','EVAP_LC_C6','B_LC_CAJA_6','EVAP_S3_LT_CAJA_6','ISLA_FAB_AI:3:I.Ch[5].Data','500','L','MV no cableado'),
   ('cenizas2020','PID_Control','PID_LAVADO_DE_GRILLA','PID_PULMON_LAVADO','LT_PULMON_LAVADO','Local:2:I.Ch[2].Data','300','L','MV no cableado; nivel_pulmon es alias del mismo canal'),
   ('cenizas2020','PID_Control','PID_LAVADO_DE_GRILLA','PID_TK_AGUA_LIMPIA','LT_TK_AGUA_LIMPIA','Local:9:I.Ch[1].Data','300','L','MV no cableado; LT_030_PV_Escalado comparte canal'),
   ('DESTILERIA','EVAPORADOR','PID_EVAPORADOR','PID_CONTROL_NIVEL_1ER_EFECTO','B_LT_VASO_1ER_EFECTO_A.Out','EVAPORADOR:2:I.Ch0Data','200','L','MV_VALV_NC a EVAPORADOR:6:O.Ch0Data; tipo de campo pendiente'),
   ('DESTILERIA','EVAPORADOR','PID_EVAPORADOR','PID_CONTROL_QUIEBRE_VACIO','B_PT_VASO_1ER_EFECTO.Out','EVAPORADOR:2:I.Ch6Data','200','P','MV_VALV_NA a EVAPORADOR:6:O.Ch2Data; tipo de campo pendiente'),
  ]
  paired={}
  for plc,program,routine,instance,measure,address,area,var,blocker in pairs:
   root,lx,mods=xml(plc)
   rr=root.find(f"Programs/Program[@Name='{program}']/Routines/Routine[@Name='{routine}']")
   if rr is None or not any(n.get('Operand')==instance and n.tag in ('Block','AddOnInstruction') for n in rr.findall('.//*[@Operand]')):raise RuntimeError('Invocación ausente '+instance)
   if not physical(address,mods) or ':I.' not in address or (plc,address) in planned_channels:raise RuntimeError('Entrada par no exclusiva '+instance)
   if plc=='DESTILERIA':
    chains=[]
    for sh in rr.findall('.//Sheet'):
     edges={(w.get('FromID'),w.get('FromParam'),w.get('ToID'),w.get('ToParam')) for w in sh.findall('Wire')}
     nodes={n.get('ID'):n for n in sh if n.get('ID')}
     chains.append(any(nodes.get(a) is not None and nodes[a].get('Operand')==measure and nodes.get(b) is not None and nodes[b].get('Operand')==instance and to=='PV' for a,_,b,to in edges))
    if not any(chains):raise RuntimeError('SCL.Out -> PV no probado '+instance)
    scalings=[]
    for scaling_routine in root.findall(f"Programs/Program[@Name='{program}']/Routines/Routine"):
     for sh in scaling_routine.findall('.//Sheet'):
      ns={n.get('ID'):n for n in sh if n.get('ID')}
      scalings.append(any(ns.get(w.get('FromID')) is not None and ns[w.get('FromID')].get('Operand')==address and ns.get(w.get('ToID')) is not None and ns[w.get('ToID')].get('Operand')==measure.split('.')[0] and w.get('ToParam')=='In' for w in sh.findall('Wire')))
    if not any(scalings):raise RuntimeError('Canal -> SCL.In no probado '+instance)
   else:
    m=lx.analizar(plc,program,routine,instance)
    if address not in m['entrada_fisica']:raise RuntimeError('Entrada del par no trazada '+instance)
   num=free(area)
   for fn,identity,ch in ((var+'T',measure,address),(var+'IC',instance,'')):
    add('AUDITORIA_FRONTERA_V3_PARES','PAR_ENTRADA_CONTROLADOR_V3','INSERT',new=f'{area}_{fn}_{num:03d}',area=area,var=var,number=num,identity=identity,address=ch,plc=plc,status='NO_INSERTAR_REVISION',note=f'Par físico de control; salida sin final exclusivo/tipo validado: {blocker}; no lazo completo ni alta',evidence=f'{plc}.L5X {program}/{routine}: {address} → {measure} → {instance}.PV; {blocker}')
   paired[instance]=(address,blocker)
   planned_channels.add((plc,address))
  # Dictamen de los 17 grupos pedidos, incluso los bloqueados: se conserva la
  # fila v2 y se añade una fila no operacional para el detalle nuevo.
  frontier={
   'B_C8_LC_DOMO':('Calderas_8_9_10_Desaireador','BP_ANALOGICA:1:I.Ch[2].Data | BP_ANALOGICA:1:I.Ch[3].Data','SEL_01.In1/In2 desde SCL B_C8_LT_DOMO_NORTE/SUR; SEL_01.Out -> PV; MV -> BP_ANALOGICA:10:O.Ch3Data; final no identificado'),
   'B_C9_LC_DOMO':('Calderas_8_9_10_Desaireador','BP_ANALOGICA:2:I.Ch[2].Data | BP_ANALOGICA:2:I.Ch[3].Data','SEL_02.In1/In2 desde SCL B_C9_LT_DOMO_NORTE/SUR; SEL_02.Out -> PV; MV -> BP_ANALOGICA:11:O.Ch5Data; final no identificado'),
   'B_C10_LC_DOMO':('Calderas_8_9_10_Desaireador','BP_ANALOGICA:4:I.Ch[1].Data | BP_ANALOGICA:3:I.Ch[3].Data','SEL_01.In1/In2 desde SCL B_C10_LT_DOMO_NORTE/SUR; SEL_01.Out -> PV; MV -> BP_ANALOGICA:12:O.Ch2Data; final no identificado'),
   'PID_CONTROL_NIVEL_1ER_EFECTO':('DESTILERIA','EVAPORADOR:2:I.Ch0Data','SCL B_LT_VASO_1ER_EFECTO_A.In/Out -> PV; MV_VALV_NC -> EVAPORADOR:6:O.Ch0Data; final no probado'),
   'PID_CONTROL_QUIEBRE_VACIO':('DESTILERIA','EVAPORADOR:2:I.Ch6Data','SCL B_PT_VASO_1ER_EFECTO.In/Out -> PV; MV_VALV_NA -> EVAPORADOR:6:O.Ch2Data; final no probado'),
   'CONTROL_CAUDAL_JUGO_DEST':('FABRICA','','FT_JUGO_DESTIL REAL sin escritor :I; SCL B_FT_JUGO_DEST.Out -> PV; MV_VALV_NC -> SCL_09.Out -> FLEX5000_MIELES:2:O.Ch01.Data / Ch02.Data; área/final pendientes'),
   'B_LC_CAJA_6':('FABRICA','ISLA_FAB_AI:3:I.Ch[5].Data','EVAP_S3_LT_CAJA_6 -> PV; MV sin cable físico'),
   'B_LC_CAJA_11':('FABRICA','ISLA_FAB_AI:4:I.Ch[2].Data','MV_VALV_NC y B_LC_CAJA_9_10.MV_VALV_NC seleccionados en SEL_02 hacia ISLA_FAB_DI:4:O.Ch2Data/Ch3Data; salida compartida'),
   'B_LC_COND_CAJA_6':('FABRICA','ISLA_FAB_AI:5:I.Ch[0].Data','sensor y SEL_08 salida ISLA_FAB_AI:14:O.Ch[5].Data compartidos con B_LC_COND_CAJA_7_8'),
   'B_LC_COND_CAJA_7_8':('FABRICA','ISLA_FAB_AI:5:I.Ch[0].Data','sensor y SEL_08 salida ISLA_FAB_AI:14:O.Ch[5].Data compartidos con B_LC_COND_CAJA_6'),
   'B_PC_ESC_DEST':('FABRICA','ISLA_FAB_AI:8:I.Ch7Data','PV compartida con B_PC_VG1R_DEST; MV sin salida física'),
   'B_PC_VG1R_FAB':('FABRICA','ISLA_FAB_AI:7:I.Ch5Data','PV compartida como protección de B_PC_VG1R_DEST y PV de B_PC_VG1_TACHOS; MV sin salida física'),
   'PID_CONTROL_NIVEL_TK_CONDENSADO':('DESTILERIA','EVAPORADOR:2:I.Ch1Data','MV_VALV_NC cruza ARRANQUE_MOTORES -> SCL_09/10 -> BBA_CONDENSADO_ESTE/OESTE:O.Reference; dos motores y selección, sin final exclusivo'),
   'CONTROL_NIVEL_BBA_DESTILADORA':('DESTILERIA','fermerntacion2022_islas:3:I.Ch[1].Data','LT_COLUMNA_DESTILADORA_CD101 alimenta también PID_Ctrol_NIVEL_Destiladora; REF_BBA_VINAZA_COLUMNA_DESTILADORA sin salida física'),
   'PID_PULMON_LAVADO':('cenizas2020','Local:2:I.Ch[2].Data','LT_PULMON_LAVADO comparte alias nivel_pulmon; MV no conectado'),
   'PID_TK_AGUA_LIMPIA':('cenizas2020','Local:9:I.Ch[1].Data','LT_TK_AGUA_LIMPIA comparte alias LT_030_PV_Escalado; MV no conectado'),
   'CONTROL_CINTA_R_2_02':('TRAPICHE2022','Local:8:I.Ch[6].Data','NIVEL_CONDUCTOR_mts alimenta también PID_CONTROL_MESA_NORTE_SUR; MV entra SCL_16.In sin cable Out -> :O'),
  }
  if len(frontier)!=17 or len(paired)!=5:raise RuntimeError('Cobertura de frontera incompleta')
  for name,(plc,address,evidence) in frontier.items():
   old=[r for r in original if r['Bloque_Maestro']=='FRONTERA_3_4_AUDITORIA' and r['Identidad_PLC_Efectiva']==name]
   if len(old)!=1:raise RuntimeError('Grupo de frontera ausente '+name)
   add('FRONTERA_3_4_AUDITORIA_V3','AUDITORIA_FRONTERA_V3',identity=name,address=address,plc=plc,status='REVISION_NO_NUMERAR',note=('PAR_PROPUESTO_NO_COMPLETO' if name in paired else 'BLOQUEADO_SIN_LAZO_EXCLUSIVO')+'; '+evidence,evidence=f'{plc}.L5X: '+evidence)['Estado_Auditoria_V3']='PAR_PROPUESTO' if name in paired else 'SIN_LAZO_COMPLETO'
  # Auditar las otras 222 de los 241, con motivo por identidad, sin convertir
  # tags derivados (ACUM, PV calculado) en instrumentos físicos adicionales.
  rescued={(r['PLC_Fuente_V2'],r['Identidad_PLC_Efectiva']) for r in original if r['Fuente_Fila']=='RESCATE_XML_241'}
  audit=Counter()
  for source,target in MAP.items():
   root,lx,modules=xml(target)
   decl={('Controller',t.get('Name')):t for t in root.findall('Tags/Tag')}
   for pr in root.findall('Programs/Program'):
    decl.update({('Program:'+pr.get('Name'),t.get('Name')):t for t in pr.findall('Tags/Tag')})
   for h in hist:
    if h['Accion']!='SIN_LAZO' or h['PLC_Origen']!=source:continue
    name=h['Tag_Original_PLC'];scope=h['Alcance'];audit['reviewed']+=1
    if (source,name) in rescued:audit['already_rescued']+=1;continue
    d=decl.get((scope,name));via='';addresses=[]
    if (source,name) in marked:
     status='RESCATADO_MONITOREO_V3';via='canal único de entrada; '+marked[(source,name)][2]
    elif name=='DENSIDAD_ALCOHOL':status='INCORPORADO_LAZO_DENSIDAD_V3'
    elif d is None:status='DECLARACION_NO_EXACTA'
    else:
     alias=(d.get('AliasFor') or '').strip()
     if alias:addresses=[alias];via='AliasFor exacto'
     else:
      trace=lx.resolver_terminal(name)
      if trace['estado']=='FISICO':addresses=[a for _,a,_ in trace['fisicos']]
      via='seguimiento de escritor '+trace['estado']
     good=sorted({a for a in addresses if physical(a,modules)})
     if not good:status='SIN_CANAL_FISICO_VALIDO'
     elif len(good)>1:status='MULTIPLES_CANALES_FISICOS'
     elif any(name in r[3] and r[2]==target for r in prod.values()):status='YA_EN_PRODUCCION_POR_IDENTIDAD'
     elif (target,good[0]) in lookup:status='CANAL_DE_LAZO_PRODUCTIVO'
     elif (target,good[0]) in {(r['PLC_Fuente_V2'],r['Direccion_Modulo_Efectiva']) for r in rows if r['Operacion_Efectiva']=='INSERT'}:status='CANAL_YA_PROPUESTO'
     elif re.search(r'(?:ACUM|TOTAL|_m3$|CORREGIDO)',name,re.I):status='DERIVADO_NO_INSTRUMENTO_INDEPENDIENTE'
     elif alias and source=='Calderas_8_9_10_Des':status='AREA_MULTISECTOR_NO_CONFIRMADA'
     elif alias:status='ALIAS_FISICO_SIN_LAZO_O_AREA'
     else:status='INTERNO_ESCALADO_PENDIENTE_EXCLUSIVIDAD'
    audit[status]+=1
    add('AUDITORIA_SIN_LAZO_241','AUDITORIA_222_EXCLUSIONES',identity=name,address=' | '.join(sorted(set(addresses))),plc=source,status='REVISION_NO_NUMERAR',note=status+'; '+via+'; alcance '+scope+'; área histórica '+h['Area']+' (no prueba área actual)',evidence=f'PLC_Origen={source}; XML={target}.L5X; declaracion '+scope+'.'+name+'; '+via+'; canales '+(' | '.join(sorted(set(addresses))) or 'ninguno'))['Estado_Auditoria_V3']=status
  if audit['reviewed']!=241 or audit['already_rescued']!=19 or sum(v for k,v in audit.items() if k not in ('reviewed','already_rescued'))!=222:raise RuntimeError('No se particionaron 222 descartes')
  # Los dos PLC adicionales: inventariar AliasFor físicos exactos, sin inventar instrumentos.
  for plc in ('USINA_LA_FLORIDA','CENTRIFUGA_DE_PRIMERA'):
   root,_,modules=xml(plc)
   alltags=root.findall('Tags/Tag')+[tag for pr in root.findall('Programs/Program') for tag in pr.findall('Tags/Tag')]
   aliases=[t for t in alltags if t.get('AliasFor') and physical(t.get('AliasFor'),modules)]
   audit[plc+'_alias_fisicos']=len(aliases)
   add('BARRIDO_ALIAS_V3','AUDITORIA_PLC_ADICIONALES',identity=plc,plc=plc,status='REVISION_NO_NUMERAR',note=f'AliasFor físicos exactos declarados: {len(aliases)}; no sumar operaciones sin señal independiente, variable y área',evidence='L5X_Produccion/'+plc+'.L5X')
  # Verificación de conservación, exclusividad, destinos y no tocar 11 manuales.
  ops=[r for r in rows if r['Operacion_Efectiva'] in ('INSERT','UPDATE','DELETE')]
  origins=defaultdict(list);dests=defaultdict(list)
  for r in ops:
   op=r['Operacion_Efectiva'];old=r['Tag_Origen_Efectivo'];new=r['Tag_Destino_Efectivo']
   if old in PROTECTED or new in PROTECTED:raise RuntimeError('Manual tocado')
   if op in ('UPDATE','DELETE'):
    if old not in prod or str(prod[old][1])!=r['ID_Origen_Efectivo']:raise RuntimeError('Origen ID inválido '+old)
    origins[old].append(r)
   if op in ('INSERT','UPDATE'):
    if not re.fullmatch(r'\d{3}_[A-Z]+_\d{3}[A-Z]?',new or ''):raise RuntimeError('Tag inválido '+new)
    dests[new].append(r)
  if any(len(v)!=1 for v in origins.values()) or any(len(v)!=1 for v in dests.values()) or any(t in prod and t not in origins for t in dests):raise RuntimeError('Colisión de origen/destino')
  if digest(DB)!=before:raise RuntimeError('DB cambió antes de emitir')
  with OUT.open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,cols,delimiter=';',lineterminator='\n');w.writeheader();w.writerows(rows)
  parsed=read('plan_maestro_consolidado_v3_290926.csv')
  if parsed!=rows or any(r['Escritura_SQLite']!='NO' for r in parsed):raise RuntimeError('CSV inválido')
  counts=Counter(r['Operacion_Efectiva'] for r in parsed)
  print('ACTUADORES función por ingeniería',len(to_confirm),'previos confirmados por XML',7,'pendientes',len([r for r in parsed if r['Estado_Maestro']=='REVISION_ACTUADOR_NO_CONFIRMADO']))
  print('RESCATE PLC omitidos',len(marked),'USINA MOV+SCL',len(unit),'CENTRIFUGA numerados',0)
  print('LAZOS completos nuevos por ingeniería',2,'FRONTERA adicional cerrada',0,'PARES incompletos',len(paired),'miembros nuevos de lazos completos',7)
  print('AUDITORIA_241',dict(audit))
  print('BALANCE INSERT',counts['INSERT'],'UPDATE',counts['UPDATE'],'DELETE',counts['DELETE'],'TOTAL PROYECTADO',196+counts['INSERT']-counts['DELETE'])
  print('CSV filas',len(parsed),'SHA-256',digest(OUT))
  print('DB',len(prod),'SHA-256 antes/después',before,digest(DB),'mode=ro query_only=ON; cero escrituras SQLite')
  if digest(DB)!=before:raise RuntimeError('DB cambió después')
 finally:con.close()

if __name__=='__main__':main()
