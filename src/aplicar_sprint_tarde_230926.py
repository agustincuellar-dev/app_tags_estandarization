"""Parte 2 del sprint tarde 23/09: áreas + alias_for, con backup y auditoría.

La propuesta v5 se aplica solo a tags que EXISTEN en producción (119 tras el rollback del delta).
Los 77 tags ausentes se reportan y no se inventan.
"""
from __future__ import annotations
import csv, hashlib, os, shutil, sqlite3, sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

RAIZ=Path(__file__).resolve().parents[1]
DB=RAIZ/'app_etiquetas/tags_ingenio.db'
BACKUPS=RAIZ/'app_etiquetas/backups'
V3=RAIZ/'exports/propuesta_numeracion_masiva_180926.csv'
V5=RAIZ/'exports/propuesta_numeracion_masiva_v5_210926.csv'
USER='agustin (via Hermes)'
AREA_NAMES={
 '000':'Recepción y Preparación de Caña','100':'Molienda','200':'Destilería','250':'Biodestilería',
 '300':'Calderas / Generación de Vapor','400':'Clarificación y Encalado','500':'Evaporación',
 '600':'Cocimiento / Tachos','700':'Centrifugado / Purga','800':'Secado y Envase',
 '900':'Fuerza Motriz / Turbogeneradores','950':'Tratamiento de Agua y Servicios',
}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ro(p):
 c=sqlite3.connect('file:'+str(Path(p).resolve())+'?mode=ro',uri=True);c.execute('pragma query_only=on');return c

def main():
 before=sha(DB)
 mark=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
 BACKUPS.mkdir(parents=True,exist_ok=True)
 byte=BACKUPS/f'tags_ingenio_antes_sprint_tarde_230926_{mark}_byte_identico.db'
 api=BACKUPS/f'tags_ingenio_antes_sprint_tarde_230926_{mark}_api.db'
 shutil.copy2(DB,byte)
 with closing(sqlite3.connect(str(DB))) as src, closing(sqlite3.connect(str(api))) as dst: src.backup(dst)
 with closing(ro(byte)) as c:
  assert c.execute('pragma integrity_check').fetchone()[0]=='ok'
 with closing(ro(api)) as c:
  assert c.execute('pragma integrity_check').fetchone()[0]=='ok'
  assert c.execute('select count(*) from tags').fetchone()[0]==119

 with open(V5,encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f,delimiter=';'))
 with closing(ro(DB)) as c:
  existing={r[0]:r[1] for r in c.execute('select tag_completo,alias_for from tags')}
 desired={r['Tag_Propuesto']: ('' if r['Migrado_De'].startswith('CANAL_CRUDO:') else r['AliasFor_Direccion_Fisica'])
          for r in rows if r['Tag_Propuesto'] in existing}
 alias_updates={k:v for k,v in desired.items() if existing[k] != v}
 missing=sorted(k for k in {r['Tag_Propuesto'] for r in rows} if k not in existing)
 area_updates=[]
 with closing(ro(DB)) as c:
  cur={r[0]:r[1] for r in c.execute('select codigo,nombre from areas')}
 for code,name in AREA_NAMES.items():
  if code in cur and cur[code]!=name: area_updates.append((code,cur[code],name))

 con=sqlite3.connect(str(DB),isolation_level=None)
 try:
  con.execute('pragma foreign_keys=on');con.execute('begin immediate')
  for code,old,new in area_updates:
   aid=con.execute('select id from areas where codigo=?',(code,)).fetchone()[0]
   con.execute('update areas set nombre=? where codigo=?',(new,code))
   con.execute("insert into auditoria(tag_id,accion,detalle,usuario) values(NULL,'MODIFICACION',?,?,?)".replace('?,?,?','?,?'),(f'Área {code}: nombre {old!r} -> {new!r}',USER))
  for tag,alias in alias_updates.items():
   tid=con.execute('select id from tags where tag_completo=?',(tag,)).fetchone()[0]
   con.execute('update tags set alias_for=? where tag_completo=?',(alias,tag))
   con.execute("insert into auditoria(tag_id,accion,detalle,usuario) values(?, 'MODIFICACION', ?, ?)",(tid,f'Backfill alias_for desde propuesta v5: {alias}',USER))
  con.execute('commit')
 except Exception:
  con.execute('rollback');con.close();raise
 finally:
  try: con.close()
  except: pass
 with closing(ro(DB)) as c:
  print('backup_byte',byte);print('backup_api',api)
  print('sha_before',before);print('sha_after',sha(DB))
  print('areas_updated',len(area_updates),'aliases_updated',len(alias_updates),'v5_missing',len(missing))
  print('integrity',c.execute('pragma integrity_check').fetchone()[0],'tags',c.execute('select count(*) from tags').fetchone()[0])
  print('area_updates_detail',area_updates)
  print('alias_nonempty_after',c.execute("select count(*) from tags where alias_for is not null and alias_for<>''").fetchone()[0])
  print('missing_tags',missing)
 return 0
if __name__=='__main__': raise SystemExit(main())
