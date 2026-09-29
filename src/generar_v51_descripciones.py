"""Genera v5.1: solo Descripcion_Propuesta cambia respecto de v5.

La ruta canónica solicitada es propuesta_numeracion_masiva_180926.csv; se conserva un backup
pre-v5.1 para poder verificar/restaurar. No toca SQLite.
"""
from __future__ import annotations
import csv, re, shutil
from pathlib import Path

RAIZ=Path(__file__).resolve().parents[1]
E=RAIZ/'exports'
V5=E/'propuesta_numeracion_masiva_v5_210926.csv'
CANON=E/'propuesta_numeracion_masiva_180926.csv'
BACKUP=E/'propuesta_numeracion_masiva_180926_pre_v51.csv'
AREA={
 '000':'Recepción y Preparación de Caña (Desfibrador)','100':'Molienda','200':'Destilería','250':'Biodestilería',
 '300':'Calderas / Generación de Vapor','400':'Clarificación y Encalado','500':'Evaporación','600':'Cocimiento / Tachos',
 '700':'Centrifugado / Purga','800':'Secado y Envase','900':'Fuerza Motriz / Turbogeneradores','950':'Tratamiento de Agua y Servicios (Ósmosis)'}
OWNERS={
 '000_LT_008':['DIBACCO/MainProgram/AI_Gonella/CONTROL_NIVEL_02','DIBACCO/MainProgram/AI_Gonella/CONTROL_NIVEL_2_01'],
 '100_FT_031':['TRAPICHE2022/PID/Ctrol_CAUDAL_INMIBICION/B_FT_AGUA_INMIBICION','TRAPICHE2022/PID/Ctrol_CAUDAL_INMIBICION/CONTROL_NIVEL_08'],
 '600_TT_016':['FABRICA/FAB_COC/COC_CONDENSADOR_3RA/B_TC_COND_3RA','FABRICA/FAB_COC/COC_CONDENSADOR_3RA/B_TC_COND_3RA_AUXILIAR'],
 '700_PT_022':['B_PC_ALTA_ESC_L1','B_PC_ALTA_ESC_L2','B_PC_ESC_CAMPO','B_PC_ESC_CAMPO_AUX','B_PC_ESC_TACHOS'],
 '700_PT_023':['B_PC_TACHOS_CAMPO','B_PC_VG2_TACHOS'],
}

def normalize(text):
 def repl(m):
  code=m.group(1); return f"área {code} ({AREA.get(code, '')})" if code in AREA else m.group(0)
 return re.sub(r"área\s+(\d{3})(?!\s*\()", repl, text)

with open(V5,encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f,delimiter=';'))
shutil.copy2(CANON,BACKUP)
cols=list(rows[0]); changed=[]
for r in rows:
 old=r['Descripcion_Propuesta']
 tag=r['Tag_Propuesto']
 if 'SENSOR_COMPARTIDO' in r['Lazo']:
  owners=OWNERS[tag]
  r['Descripcion_Propuesta']=(f"Transmisor — sensor compartido; lazos poseedores: {' | '.join(owners)}; "
    f"Migrado de: {r['Migrado_De']}; rutina {r['Routine']}; área {r['Area']} ({AREA[r['Area']]})")
 else:
  r['Descripcion_Propuesta']=normalize(old)
 if r['Descripcion_Propuesta']!=old: changed.append(tag)
with open(CANON,'w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=cols,delimiter=';',lineterminator='\n');w.writeheader();w.writerows(rows)
print('rows',len(rows),'descriptions_changed',len(changed),'backup',BACKUP)
print('sensor_changed',[t for t in changed if t in OWNERS])
