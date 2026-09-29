"""Catálogo de extremos físicos candidatos; producción SQLite estrictamente de lectura."""
import csv,hashlib,re,sqlite3,sys,xml.etree.ElementTree as ET
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; EXPORT=ROOT/'exports'; DB=ROOT/'app_etiquetas/tags_ingenio.db'
OUT=EXPORT/'catalogo_candidatos_expansion_280926.csv'
FRONT=EXPORT/'frontera_controladores_con_invocacion_xml.csv'; HIST=EXPORT/'reconciliacion_catalogo_isa_v3.csv'
COLS=['Origen','PLC','Program','Identidad_Fisica','Direccion_Modulo','Area_Inferida','Variable_ISA','Tipo_Instrumento','Es_Lazo_PID','Instancias_PID','Estado_Catalogacion','Evidencia_Area','Evidencia_Fisica','Coincidencia_Produccion','Observacion','Escritura_SQLite']
VAR=set('PTLFIS')
AREA_PLC={'CALD_LA_FLORIDA':'300','Calderas_8_9_10_Desaireador':'300','cenizas2020':'300','DESTILERIA':'200','DIBACCO':'250','TRAPICHE2022':'100','USINA_LA_FLORIDA':'900'}
PREFIX={'COC':'600','EVAP':'500','CCV':'700','SULFO':'400','CLAR':'400','MIEL':'700','TK_MIEL':'700','CAL':'300'}
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def read(path):
 with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f,delimiter=';'))
def area(plc,prog,identity,legacy=''):
 if plc=='FABRICA':
  if prog=='SULFO_ENCALADO':return '400','Ingeniería: SULFO_ENCALADO=400'
  for text in (identity,prog):
   u=text.upper().lstrip('\\')
   if u.startswith(('TK_MIEL','MIEL_','FLEX5000_MIELES')) or '_MIEL_CENT' in u or '_MIEL_RICA' in u:return '700','Decisión Mieles=700'
   for prefix,n in PREFIX.items():
    if u.startswith(prefix+'_') or u.startswith(prefix+'.'):return n,'Prefijo '+prefix
  return '','FABRICA multiarea sin prefijo demostrable'
 if plc in AREA_PLC:
  declared=AREA_PLC[plc]
  if legacy and legacy!=declared:
   if plc=='DIBACCO':return declared,'Ingeniería: DIBACCO=250; histórico '+legacy+' contradice'
   return '','Conflicto histórico '+legacy+' vs PLC '+declared
  return declared,'Área PLC '+plc+'='+declared
 return '','PLC sin mapeo de área confirmado'
def variable(name):
 text=name.upper().lstrip('\\')
 codes=[m.group(1) for m in re.finditer(r'(?<![A-Z0-9])([PTLFIS])(?:IT|T|SH|SL|S|IC|CV|XV|V)(?=[_\W]|$)',text)]
 return codes[0] if len(set(codes))==1 else ''
def instrument(name,direction):
 u=name.upper()
 if direction=='I':
  if re.search(r'(?<![A-Z0-9])(?:[PTLFIS]S[HL]?|SWITCH)(?=[_\W]|$)',u):return 'Switch'
  if re.search(r'(?<![A-Z0-9])[PTLFIS](?:IT|T)(?=[_\W]|$)',u):return 'Transmisor'
 else:
  if re.search(r'(?:^|[_\.])(?:VALVULA|VALVE|[PTLFIS]CV|[PTLFIS]XV|[PTLFIS]V)(?:[_\.]|$)',u):return 'Válvula'
 return ''
def physical(addr,modules):
 # Sólo módulos declarados y rutas :I/:O; no inferir :C ni aliases intermedios.
 addr=(addr or '').strip();m=re.match(r'^([^:]+)(?::\d+)?:([IO])(?:\.|\[|$)',addr,re.I)
 if m and m[1] in modules and not re.search(r'\.(?:modulo|module)$',addr,re.I) and re.search(r':(?:I|O)(?:\.(?:Ch|Data|Output|Input|Reference|Freq|Current|Voltage|Status)|\[)',addr,re.I):return m[2].upper()
 return ''
def main():
 before=digest(DB);con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
 try:
  con.execute('PRAGMA query_only=ON')
  prod=con.execute('SELECT tag_completo,plc_origen,COALESCE(comentarios,\'\'),COALESCE(descripcion,\'\'),COALESCE(alias_for,\'\') FROM tags').fetchall()
  if len(prod)!=196 or con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('DB conteo o integridad inesperados')
  front=read(FRONT);history=read(HIST)
  if len([r for r in history if r['Accion']=='SIN_LAZO'])!=578:raise RuntimeError('SIN_LAZO != 578')
  chosen=[r for r in front if r['Prioridad'] in ('3','4') and r['Invocacion_XML_Demostrada']=='SI']
  if len(chosen)!=102:raise RuntimeError('Prioridad 3/4 actual !=102: '+str(len(chosen)))
  sys.path.insert(0,str(ROOT/'src'))
  from trazador_lazos_profundo import L5X
  needed={r['PLC'] for r in chosen}|{r['PLC_Origen'] for r in history if r['Accion']=='SIN_LAZO'}
  cache={};declarations={};modules={};missing=[]
  for plc in sorted(needed):
   path=ROOT/'L5X_Produccion'/(plc+'.L5X')
   if not path.exists():missing.append(plc);continue
   xml=ET.parse(path).getroot().find('Controller')
   if xml is None:raise RuntimeError('Sin Controller: '+plc)
   declarations[plc]={('Controller',t.get('Name')):t for t in xml.findall('Tags/Tag')}
   for program in xml.findall('Programs/Program'):
    declarations[plc].update({('Program:'+program.get('Name',''),t.get('Name')):t for t in program.findall('Tags/Tag')})
   modules[plc]={m.get('Name') for m in xml.findall('Modules/Module')}
   cache[plc]=L5X(path)
  # La entrada es una identidad física candidata, no un número ISA propuesto.
  found={};stats=Counter()
  def already(plc,identity,address):
   matches=[]
   for tag,p,c,d,alias in prod:
    if p!=plc:continue
    source=c+' | '+d
    if alias==address or (address and re.search(r'(?<![A-Za-z0-9_])'+re.escape(address)+r'(?![A-Za-z0-9_])',source)) or re.search(r'(?<![A-Za-z0-9_])'+re.escape(identity)+r'(?![A-Za-z0-9_])',source):matches.append(tag)
   return sorted(set(matches))
  def add(origin,plc,program,identity,address,area_val,area_evidence,var,typ,pid,instance,evidence):
   if not physical(address,modules.get(plc,set())):
    stats['DIRECCION_NO_DEMOSTRADA']+=1;return
   if not area_val and not pid:
    stats['SIN_LAZO_AREA_INDETERMINADA']+=1;return
   ready=bool(area_val and var in VAR and typ)
   if not ready:stats['EXTREMO_NO_CATALOGABLE']+=1
   key=(plc,program,identity,address,typ)
   existing=already(plc,identity,address)
   entry=found.get(key)
   if entry:
    if instance:entry['_instances'].add(instance)
    entry['_origins'].add(origin)
    if pid:entry['Es_Lazo_PID']='SI'
    return
   found[key]={'Origen':origin,'PLC':plc,'Program':program,'Identidad_Fisica':identity,'Direccion_Modulo':address,
    'Area_Inferida':area_val,'Variable_ISA':var,'Tipo_Instrumento':typ,'Es_Lazo_PID':'SI' if pid else 'NO',
    'Instancias_PID':'','Estado_Catalogacion':('YA_REPRESENTADO_EN_PRODUCCION' if existing else 'CANDIDATO_FISICO_REVISAR_LAZO' if ready else 'PENDIENTE_AREA_VARIABLE_TIPO'),
    'Evidencia_Area':area_evidence,'Evidencia_Fisica':evidence,'Coincidencia_Produccion':' | '.join(existing),
    'Observacion':'SIN_LAZO no acredita lazo ni autorización para numerar' if not pid else 'Invocación XML, no ejecución runtime ni grupo insertable',
    'Escritura_SQLite':'NO','_instances':{instance} if instance else set(),'_origins':{origin}}
  traced=Counter()
  for r in chosen:
   plc=r['PLC'];lx=cache.get(plc)
   if not lx:raise RuntimeError('Falta L5X de frontera: '+plc)
   result=lx.analizar(plc,r['Program'],r['Routine'],r['Instancia']);sides=0
   input_physical=[]
   for side in ('entrada','salida'):
    val=result.get(side+'_fisica','')
    for part in val.split(' | '):
     m=re.match(r'^(.*?) \((.*?)\)$',part.strip())
     if not m:continue
     identity,address=m.groups();direction=physical(address,modules[plc])
     if not direction or direction!=('I' if side=='entrada' else 'O'):continue
     sides+=1
     if side=='entrada':input_physical.append(identity)
     ar,reason=area(plc,r['Program'],identity)
     var=variable(identity) or (variable(result.get('entrada_operando','')) if side=='entrada' else '')
     if side=='salida' and not var:
      vs={variable(i) for i in input_physical}-{''}
      if len(vs)==1:var=next(iter(vs))
     add('FRONTERA_3_4',plc,r['Program'],identity,address,ar,reason,var,instrument(identity,direction),True,r['Instancia'],result.get(side+'_camino','') or result['nota'])
   traced['con_extremo' if sides else 'sin_extremo']+=1
  for r in history:
   if r['Accion']!='SIN_LAZO':continue
   plc=r['PLC_Origen'];lx=cache.get(plc)
   if not lx:stats['SIN_LAZO_XML_AUSENTE']+=1;continue
   raw=r['Tag_Original_PLC'];scope=r['Alcance'];decl=declarations[plc].get((scope,raw))
   if decl is None:stats['SIN_LAZO_DECLARACION_NO_EXACTA']+=1;continue
   # Un alias es evidencia directa. Para tags internos seguir escritores del analizador actual,
   # pero no aceptar referencias sin módulo declarado ni otras direcciones implícitas.
   alias=(decl.get('AliasFor') or '').strip();fys=[]
   if physical(alias,modules[plc]):fys=[(raw,alias,'AliasFor en declaración exacta')]
   else:
    trace=lx.resolver_terminal(raw)
    if trace['estado']=='FISICO':
     fys=[(name,address,' <- '.join(trace['camino'][:8])) for name,address,_ in trace['fisicos'] if physical(address,modules[plc])]
   if not fys:stats['SIN_LAZO_SIN_DIRECCION']+=1;continue
   if not alias and len({a for _,a,_ in fys})>1:
    stats['SIN_LAZO_AGREGADO_MULTISENSOR']+=1;continue
   program=scope.split(':',1)[1] if scope.startswith('Program:') else ''
   for physical_name,address,evidence in fys:
    direction=physical(address,modules[plc]);ar,reason=area(plc,program,raw,r['Area'])
    # No usar la variable del catálogo histórico como prueba; exigir morfema de identidad real.
    var=variable(raw) or variable(physical_name)
    typ=instrument(raw,direction) or instrument(physical_name,direction)
    add('SIN_LAZO',plc,program,raw,address,ar,reason,var,typ,False,'',evidence)
  rows=[]
  channel_users=defaultdict(set)
  for (plc,program,identity,address,typ),item in found.items():
   channel_users[(plc,address)].add(identity)
  for key,r in sorted(found.items()):
   if len(channel_users[(r['PLC'],r['Direccion_Modulo'])])>1 and r['Estado_Catalogacion']=='CANDIDATO_FISICO_REVISAR_LAZO':
    r['Estado_Catalogacion']='REVISION_CANAL_COMPARTIDO'
    r['Observacion']='Múltiples identidades sobre el mismo canal: '+ ' | '.join(sorted(channel_users[(r['PLC'],r['Direccion_Modulo'])]))
   r['Instancias_PID']=' | '.join(sorted(r.pop('_instances')))
   r['Origen']=' | '.join(sorted(r.pop('_origins')))
   rows.append(r)
  if digest(DB)!=before:raise RuntimeError('DB cambió durante barrido')
  with OUT.open('w',encoding='utf-8-sig',newline='') as f:
   writer=csv.DictWriter(f,COLS,delimiter=';',lineterminator='\n');writer.writeheader();writer.writerows(rows)
  check=read(OUT)
  if check!=rows or len({(r['PLC'],r['Program'],r['Identidad_Fisica'],r['Direccion_Modulo'],r['Tipo_Instrumento']) for r in check})!=len(check):raise RuntimeError('CSV inválido')
  new=[r for r in check if r['Estado_Catalogacion']=='CANDIDATO_FISICO_REVISAR_LAZO']
  print('FRONTERA: 102 invocados P3/P4;',traced['con_extremo'],'con extremo; ',traced['sin_extremo'],'sin extremo')
  print('SIN_LAZO: 578; XML ausente',stats['SIN_LAZO_XML_AUSENTE'],'sin dirección',stats['SIN_LAZO_SIN_DIRECCION'],'declaración no exacta',stats['SIN_LAZO_DECLARACION_NO_EXACTA'])
  print('CATÁLOGO',len(check),'extremos físicos; nuevos candidatos clasificados sin canal compartido',len(new),'ya representados',sum(r['Estado_Catalogacion']=='YA_REPRESENTADO_EN_PRODUCCION' for r in check),'canales compartidos',sum(r['Estado_Catalogacion']=='REVISION_CANAL_COMPARTIDO' for r in check),'pendientes de área/variable/tipo',sum(r['Estado_Catalogacion']=='PENDIENTE_AREA_VARIABLE_TIPO' for r in check))
  print('CONTROLADORES CON EXTREMO CATALOGADO',len({(r['PLC'],r['Program'],i) for r in check for i in r['Instancias_PID'].split(' | ') if i}))
  print('SIN_LAZO agregados multisensor no contados',stats['SIN_LAZO_AGREGADO_MULTISENSOR'],'sin área',stats['SIN_LAZO_AREA_INDETERMINADA'])
  print('POR ÁREA',dict(sorted(Counter(r['Area_Inferida'] for r in new).items())))
  print('POR VARIABLE',dict(sorted(Counter(r['Variable_ISA'] for r in new).items())))
  print('POR TIPO',dict(sorted(Counter(r['Tipo_Instrumento'] for r in new).items())))
  print('POR ÁREA Y VARIABLE',dict(sorted(Counter((r['Area_Inferida'],r['Variable_ISA']) for r in new).items())))
  print('XML ausentes:',missing)
  print('CSV',OUT,'SHA-256',digest(OUT));print('DB',len(prod),'SHA-256 antes/después',before,digest(DB))
  if digest(DB)!=before:raise RuntimeError('DB final alterada')
 finally:con.close()
if __name__=='__main__':main()
