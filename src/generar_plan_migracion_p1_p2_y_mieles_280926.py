"""Plan de operaciones ISA: sólo lectura de SQLite; nunca aplica cambios."""
import csv, hashlib, re, sqlite3, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'app_etiquetas/tags_ingenio.db'
HIST=ROOT/'app_etiquetas/tags_ingenio - copia backup.db'
MIELES=ROOT/'exports/addendum_propuesta_mieles_230926.csv'
FRONT=ROOT/'exports/estado_tagueo_prioridad_1_2_280926.csv'
OUT=ROOT/'exports/plan_migracion_p1_p2_y_mieles_280926.csv'
PREVIOUS_SHA='6f8f9c349c992da112609613a05066d0d1964c843826b29ae8be27e0517fb0b8'
EXPECTED='dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522'
PROTECTED={'200_PIT_004','200_PIC_004','200_PV_004','200_LT_035','200_LIC_035','200_LV_035','200_FT_080','200_FIC_080','200_FV_080','250_PV_001','250_PV_002'}
FIELDS=['SHA_DB_Anterior','SHA_DB_Actual','Verificacion_Logica','Grupo','Fila_Origen','Instancia','PLC','Operacion','ID_Origen','Tag_Origen','Tag_Destino','Area_Origen','Area_Destino','Variable_ISA','Numero_Origen','Numero_Destino','Funcion_ISA','Rol','Identidad_PLC','Destino_Fisico','Evidencia_Produccion','Ocupacion_DB','Historico_Retirado','Inventario_Online','Estado_Revision','Nota','Escritura_SQLite']

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def ro(p):
 c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);c.execute('PRAGMA query_only=ON');return c

def main():
 before=sha(DB)
 if before!=EXPECTED:raise RuntimeError('SHA producción inesperado: '+before)
 c=ro(DB);h=ro(HIST)
 try:
  data={r[1]:r for r in c.execute('SELECT * FROM tags')}
  cols=[x[1] for x in c.execute('PRAGMA table_info(tags)')]
  tags={t:dict(zip(cols,r)) for t,r in data.items()}
  if len(tags)!=196 or not PROTECTED<=tags.keys():raise RuntimeError('DB/protegidos incompletos')
  baseline=ro(ROOT/'app_etiquetas/backups/tags_ingenio_antes_ola5_20260923_111721_974548_byte_identico.db')
  try:
   q='SELECT id,tag_completo,area_id,descripcion FROM tags'
   previous_rows={r[0]:r for r in baseline.execute(q)}
   current_rows={r[0]:r for r in c.execute(q)}
   if len(previous_rows)!=119 or any(current_rows.get(i)!=r for i,r in previous_rows.items()):
    raise RuntimeError('La línea base anterior de 119 tags cambió lógicamente')
  finally:baseline.close()
  if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Integridad fallida')
  logical_note='196 registros e integridad OK; 119/119 filas del respaldo previo idénticas en ID/tag/área/descripción; faltan 77 filas de línea base 196 para acreditar identidad total'
  cat_areas={a[0]:a[1] for a in c.execute('SELECT codigo,id FROM areas')}
  if not {'100','200','250','400','500','600','700','000'}<=cat_areas.keys():raise RuntimeError('Áreas faltantes')
  hist={t for (t,) in h.execute('SELECT tag_completo FROM tags')}
  if h.execute('SELECT count(*) FROM tags').fetchone()[0]!=693:raise RuntimeError('Histórico incompleto')
  hist_by_area=defaultdict(set)
  for tag in hist:
   m=re.match(r'^(\d{3})_[A-Z]+_(\d{3})$',tag)
   if m:hist_by_area[m[1]].add(int(m[2]))
  with FRONT.open(encoding='utf-8-sig',newline='') as f:
   front={str(i):row for i,row in enumerate(csv.DictReader(f,delimiter=';'),1)}
  with MIELES.open(encoding='utf-8-sig',newline='') as f:miel=list(csv.DictReader(f,delimiter=';'))
  if len(miel)!=4:raise RuntimeError('Addendum no tiene cuatro filas')
  # Leer inventarios online, incluso donde el extractor anterior no declaraba 250/400.
  sys.path.insert(0,str(ROOT/'src'))
  from identificadores_vigentes import numero_de_identificador, quitar_prefijos
  import openpyxl
  variables={v for (v,) in c.execute('SELECT letra FROM variables')}
  funciones={v for (v,) in c.execute('SELECT letra FROM funciones')}
  inv=defaultdict(lambda:defaultdict(list)); raw=defaultdict(lambda:defaultdict(list))
  by_area={
   '100':[('inventario_plcs_20260806_085612-PLC_Trapiche.xlsx',None),('inventario_plcs_20260806_094422-PLC_Ctr_Turb_Moenda.xlsx',None)],
   '250':[('inventario_plcs_20260806_085228-PLC_Bio.xlsx',None)],
   '400':[('inventario_plcs_20260806_085528-PLC_Fabrica.xlsx',('SULFO','ENCAL'))],
   '500':[('inventario_plcs_20260806_085528-PLC_Fabrica.xlsx',('EVAP',))],
   '600':[('inventario_plcs_20260806_085528-PLC_Fabrica.xlsx',('COC',))],
   '700':[('inventario_plcs_20260806_085528-PLC_Fabrica.xlsx',('CCV','MIEL','TK_MIEL')),('inventario_plcs_20260806_094309-PLC_Centrifuga_1ra.xlsx',None)]}
  for area,sources in by_area.items():
   for filename,prefixes in sources:
    book=openpyxl.load_workbook(ROOT/'variables plc programa yanco'/filename,read_only=True,data_only=True)
    try:
     sheet=book['Tags'];it=sheet.iter_rows(values_only=True);header=list(next(it));ix=header.index('Tag')
     for values in it:
      tag=str(values[ix] or '')
      if not tag:continue
      base=quitar_prefijos(tag)
      if prefixes and not base.upper().startswith(prefixes):continue
      n=numero_de_identificador(tag,variables,funciones)
      if n is not None:inv[area][n].append(filename+':'+tag)
      # Informe literal independiente de la regla ISA: no equivale a ocupación.
      for num in (1,2,3,4,5,12,17,19,24,26,29,34,35,36):
       if re.search(r'(?<!\d)0?'+str(num)+r'(?!\d)',tag):
        if len(raw[area][num])<3:raw[area][num].append(filename+':'+tag)
    finally:book.close()
  original={(r['area_id'],r['numero_loop']) for r in tags.values()}
  def used(area,n):return (cat_areas[area],n) in original or n in inv[area]
  def free(area,n):
   if used(area,n):raise RuntimeError(f'Número ocupado {area}/{n}: '+str(inv[area].get(n,[])[:2]))
  for a,n in [('600',19),('100',35),('100',36),('250',3),('700',12)]:free(a,n)
  # El histórico es informativo, pero elegir 005 evita reutilizar los cuatro antiguos 400.
  sulfo=next(n for n in range(1,100) if not used('400',n) and n not in hist_by_area['400'])
  free('400',sulfo)
  rows=[]
  def make(group,line,instance,plc,operation,old='',new='',role='',identity='',physical='',note='',review='REVISAR_ANTES_DE_APLICAR'):
   if old and old not in tags:raise RuntimeError('Origen no existe: '+old)
   if new and new!=old and new in tags and operation!='MANTENER':raise RuntimeError('Destino ocupado: '+new)
   if old in PROTECTED or new in PROTECTED:raise RuntimeError('Tag manual protegido incluido: '+old+'/'+new)
   if operation=='INSERT' and old:raise RuntimeError('INSERT con origen')
   if operation in ('UPDATE','DELETE','MANTENER') and not old:raise RuntimeError('Operación sin origen')
   if operation=='DELETE' and new:raise RuntimeError('DELETE con destino')
   if operation=='MANTENER' and new!=old:raise RuntimeError('MANTENER cambia identidad')
   origin=tags.get(old,{});chosen=new or old
   m=re.match(r'^(\d{3})_([A-Z]+)_(\d{3})([A-D]?)$',chosen)
   dest_area=m[1] if m else '';num=int(m[3]) if m else None
   var=m[2][:1] if m else '';fun=m[2][1:] if m else ''
   row=dict.fromkeys(FIELDS,'')
   row.update(Grupo=group,Fila_Origen=str(line),Instancia=instance,PLC=plc,Operacion=operation,
              ID_Origen=str(origin.get('id','')),Tag_Origen=old,Tag_Destino=new,
              Area_Origen=old[:3] if old else '',Area_Destino=dest_area,Variable_ISA=var,
              Numero_Origen=str(origin.get('numero_loop','')),Numero_Destino=f'{num:03d}' if num is not None else '',
              Funcion_ISA=fun,Rol=role,Identidad_PLC=identity,Destino_Fisico=physical,
              Evidencia_Produccion=(origin.get('descripcion') or '') if old else '',
              Ocupacion_DB=('BASE_PROPIA_EXISTENTE' if operation in ('UPDATE','MANTENER') and used(dest_area,num) else
                            'LIBRE_EN_DB' if num is not None and not used(dest_area,num) else 'NO_APLICA'),
              Historico_Retirado=('REFERENCIA:'+','.join(sorted(t for t in hist if t.startswith(f'{dest_area}_') and t.endswith(f'_{num:03d}')))[:450] if num in hist_by_area[dest_area] else 'SIN_COINCIDENCIA') if num is not None else '',
              Inventario_Online=('ISA:'+(' | '.join(inv[dest_area].get(num,[])) or 'NINGUNO')+'; LITERAL_MUESTRA:'+(' | '.join(raw[dest_area].get(num,[])) or 'NINGUNO')) if num is not None and dest_area in by_area else 'NO_APLICA',
              Estado_Revision=review,Nota=note,Escritura_SQLite='NO')
   rows.append(row)
  def triplet(group,line,instance,plc,area,var,num,final='V',outputs=None):
   base=f'{area}_{var}';s=f'{num:03d}';source=front[str(line)]
   if outputs is None: outputs=[source['Salida_Fisica']]
   make(group,line,instance,plc,'INSERT',new=f'{base}T_{s}',role='ENTRADA',identity=source['Entrada_Camino'],physical=source['Entrada_Fisica'])
   make(group,line,instance,plc,'INSERT',new=f'{base}IC_{s}',role='CONTROLADOR',identity=instance)
   for i,endpoint in enumerate(outputs):
    suffix=chr(65+i) if len(outputs)>1 else ''
    make(group,line,instance,plc,'INSERT',new=f'{base}{final}_{s}{suffix}',role='SALIDA',identity=endpoint,physical=endpoint)
  triplet('A_NUEVO',22,'COC_LC_MELADO_T','FABRICA','600','L',19)
  triplet('A_NUEVO',39,'IC_CINTA_RAPIDA_2','TRAPICHE2022','100','I',35,final='Y')
  triplet('A_NUEVO',40,'PID_CONTROL_MESA_NORTE_SUR','TRAPICHE2022','100','L',36,final='XV')
  triplet('A_NUEVO',35,'B_Ctrol_FT_JUGO_SECUNDARIO','FABRICA','400','F',sulfo,final='XV',outputs=['Slot_IS_BBA_JUGO_SECUNDARIO_NORTE','Slot_IS_BBA_JUGO_SECUNDARIO_SUR'])
  for r in miel:
   if not r['Tag_Propuesto']:
    row=dict.fromkeys(FIELDS,'');row.update(Grupo='B_MIELES',Instancia=r['Instancia_AOI'],PLC=r['PLC'],Operacion='PENDIENTE_SIN_OPERACION',Rol=r['Rol'],Identidad_PLC=r['Migrado_De'],Estado_Revision='BLOQUEADO_NO_NUMERAR',Nota='Cuarta fila del Addendum sin número ni tag; no es INSERT ni MANTENER de una fila de producción.',Escritura_SQLite='NO');rows.append(row)
   else:
    if r['Tag_Propuesto'] in tags:raise RuntimeError('Mieles ya en producción')
    make('B_MIELES','',r['Instancia_AOI'],r['PLC'],'INSERT',new=r['Tag_Propuesto'],role=r['Rol'],identity=r['Migrado_De'],physical=r['AliasFor_Direccion_Fisica'],note='Addendum NO_INSERTAR; sujeto a revisión final.')
  def branch(group,entries,area,var,base,oldnums,final,identities):
   s=f'{base:03d}';root=f'{area}_{var}'
   for i,(line,inst,plc) in enumerate(entries):
    old=f'{oldnums[i]:03d}';letter=chr(65+i)
    if i==0:make(group,line,inst,plc,'MANTENER',f'{root}T_{s}',f'{root}T_{s}',role='ENTRADA')
    else:make(group,line,inst,plc,'DELETE',f'{root}T_{old}',role='TRANSMISOR_DUPLICADO',note='Unificado en '+f'{root}T_{s}')
    for fcode,rol in [('IC','CONTROLADOR'),(final,'SALIDA')]:
     oldtag=f'{root}{fcode}_{old}';new=f'{root}{fcode}_{s}{letter}'
     make(group,line,inst,plc,'UPDATE',oldtag,new,role=rol,identity=inst if rol=='CONTROLADOR' else identities[i],physical=identities[i] if rol=='SALIDA' else '')
  # En DIBACCO el 000_LT_008 ya es sensor compartido: se conserva su fila por UPDATE,
  # se eliminan exactamente los seis tags indicados y se crean cuatro ramas nuevas.
  make('C_GONELLA',5,'CONTROL_NIVEL_02','DIBACCO','UPDATE','000_LT_008','250_LT_003',role='ENTRADA',identity='GONELLA_LT_DESAIREADOR',physical='Local:16:I.Ch[2].Data',note='Preserva ID del transmisor compartido, no lo deja huérfano.')
  for i,(line,inst,number,endpoint) in enumerate([(5,'CONTROL_NIVEL_02','009','VALVULA_DESAGOTE_DES_G'),(6,'CONTROL_NIVEL_2_01','016','VALVULA_ALIMENTACION_DES')]):
   letter=chr(65+i)
   for fun,role in [('T','ENTRADA_DUPLICADA'),('IC','CONTROLADOR_ANTERIOR'),('V','SALIDA_ANTERIOR')]:
    make('C_GONELLA',line,inst,'DIBACCO','DELETE',f'000_L{fun}_{number}',role=role,note='Sustituido por sensor 250_LT_003 y rama '+letter)
   for fun,role,identity in [('IC','CONTROLADOR',inst),('V','SALIDA',endpoint)]:
    make('C_GONELLA',line,inst,'DIBACCO','INSERT',new=f'250_L{fun}_003{letter}',role=role,identity=identity,physical=endpoint if role=='SALIDA' else '')
  branch('C_ESCAPE',[(9,'B_PC_ALTA_ESC_L1','FABRICA'),(10,'B_PC_ALTA_ESC_L2','FABRICA'),(11,'B_PC_ESC_CAMPO','FABRICA'),(12,'B_PC_ESC_TACHOS','FABRICA')],'700','P',24,[24,25,26,28],'XV',['CCV_S15_PCV_ALTA_ESC_L1','CCV_S15_PCV_ALTA_ESC_L2','CCV_S15_PCV_ESC_CAMPO','CCV_S15_PCV_ESC_TACHOS'])
  branch('C_TACHOS',[(13,'B_PC_TACHOS_CAMPO','FABRICA'),(17,'B_PC_VG2_TACHOS','FABRICA')],'700','P',29,[29,31],'XV',['CCV_S16_PVC_TACHOS_CAMPO','CCV_S15_PCV_VG2_TACHOS'])
  branch('C_CONDENSADOR',[(20,'B_TC_COND_3RA','FABRICA'),(21,'B_TC_COND_3RA_AUXILIAR','FABRICA')],'600','T',17,[17,18],'XV',['COC_S15_TVC_COND_BAR_3RA','COC_S15_TVC_COND_BAR_3RA_AUX'])
  for group,line,inst,plc,area,n,ends in [
   ('C_EVAP',34,'EVAP_LC_JC_EVAPORACION','FABRICA','500',26,['EVAP_S2_FCV_JC_BBA_NORTE','EVAP_S2_FCV_JC_BBA_SUR','EVAP_S2_FCV_JC_BBA_LIQUIDACION']),
   ('C_COLADO',36,'B_Ctrl_JUGO_COLADO_2','TRAPICHE2022','100',34,['Slot_IS_JUGO_COLADO_ESTE','Slot_IS_JUGO_COLADO_OESTE'])]:
   for fun in ('T','IC'):
    tag=f'{area}_F{fun}_{n:03d}';make(group,line,inst,plc,'MANTENER',tag,tag,role='ENTRADA' if fun=='T' else 'CONTROLADOR')
   old=f'{area}_FXV_{n:03d}'
   for i,end in enumerate(ends):
    make(group,line,inst,plc,'UPDATE' if i==0 else 'INSERT',old=old if i==0 else '',new=old+chr(65+i),role='SALIDA',identity=end,physical=end,note='EVAP: verificar correspondencia de tres destinos JUGO_CLARO:O.Data adicionales presentes en la procedencia antigua.' if group=='C_EVAP' else '')
  for line,inst,plc,area,var,n,final in [(2,'B_CONTROL_BBA_MOSTO','DESTILERIA','200','L',96,'V'),(14,'B_PC_VG1_TACHOS','FABRICA','700','P',21,'XV')]:
   for fun,role in [('T','ENTRADA'),('IC','CONTROLADOR'),(final,'SALIDA')]:
    tag=f'{area}_{var}{fun}_{n:03d}';make('C_1A1',line,inst,plc,'MANTENER',tag,tag,role=role,note='MOSTO usa L en producción; solicitud previa decía F. Se mantiene sin corrección automática.' if line==2 else '')
  # Gates del plan: IDs únicos; todo origen para UPDATE/DELETE/MANTENER existe; destino final único.
  ids=[r['ID_Origen'] for r in rows if r['Operacion'] in ('UPDATE','DELETE','MANTENER')]
  if len(ids)!=len(set(ids)):raise RuntimeError('Un ID de origen afectado dos veces')
  dest=[r['Tag_Destino'] for r in rows if r['Operacion'] in ('INSERT','UPDATE','MANTENER')]
  if len(dest)!=len(set(dest)):raise RuntimeError('Tags finales duplicados')
  removed={r['Tag_Origen'] for r in rows if r['Operacion'] in ('UPDATE','DELETE')}
  untouched=set(tags)-removed
  if set(dest)&(untouched-{r['Tag_Origen'] for r in rows if r['Operacion']=='MANTENER'}):
   raise RuntimeError('Destino colisiona con un tag no modificado')
  if any(r['Tag_Origen'] in PROTECTED or r['Tag_Destino'] in PROTECTED for r in rows):raise RuntimeError('Manual afectado')
  if sha(DB)!=before:raise RuntimeError('Producción cambió durante el plan')
  for row in rows:
   row['SHA_DB_Anterior']=PREVIOUS_SHA
   row['SHA_DB_Actual']=before
   row['Verificacion_Logica']=logical_note
  with OUT.open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,FIELDS,delimiter=';',lineterminator='\n');w.writeheader();w.writerows(rows)
  with OUT.open(encoding='utf-8-sig',newline='') as f:
   reader=csv.DictReader(f,delimiter=';');assert len(reader.fieldnames)==len(set(reader.fieldnames));parsed=list(reader)
  if parsed!=rows:raise RuntimeError('Roundtrip CSV difiere')
  counts=Counter(r['Operacion'] for r in parsed);projected=len(tags)+counts['INSERT']-counts['DELETE']
  print('PLAN',OUT,'filas',len(rows));print('BALANCE',dict(counts),'proyectado',projected)
  print('ÁREA 400 número tentativo',sulfo,'(histórico 001-004 informado, no reutilizado)')
  for a,n in [('250',3),('400',sulfo),('600',19),('100',35),('100',36),('700',12)]:
   print('UNIVERSO',a,f'{n:03d}','DB',used(a,n),'histórico',n in hist_by_area[a],'ISA inventario',len(inv[a].get(n,[])),'literal muestra',raw[a].get(n,[]))
  print('PROTEGIDOS',len(PROTECTED),'NO TOCADOS');print('CSV SHA-256',sha(OUT));print('DB',len(tags),'SHA-256',sha(DB));print('HIST SHA-256',sha(HIST))
  if sha(DB)!=EXPECTED:raise RuntimeError('Producción alterada al final')
 finally:c.close();h.close()
if __name__=='__main__':main()
