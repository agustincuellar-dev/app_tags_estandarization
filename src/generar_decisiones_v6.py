"""Genera decisiones_pendientes_v6.csv para los 10 casos fuera de v5.
Solo lee CSV/documentos; no abre SQLite.
"""
from __future__ import annotations
import csv
from pathlib import Path

RAIZ=Path(__file__).resolve().parents[1]
E=RAIZ/'exports'
FUERA=E/'decisiones_fuera_v5_210926.csv'
AN=E/'analisis_210_lazos_v4.csv'
OUT=E/'decisiones_pendientes_v6.csv'

MANUAL='Manual_Estandarizacion.md líneas 83-97: tabla oficial de áreas; 300 = Calderas / Generación de Vapor; 400 = Clarificación y Encalado; 500 = Evaporación; 600 = Cocimiento / Tachos; 700 = Centrifugado / Purga.'
ROADMAP='Roadmap_Arquitectura_Inteligente.md líneas 19-26: DES significa Destilería/área 200 salvo en Calderas_8_9_10_Desaireador, donde significa Desaireador/área 300; las excepciones requieren código explícito.'
OVERRIDE='Manual_Mantenimiento_Codigo.md líneas 110-112: MAPEO_AREA_OVERRIDE_POR_PLC = {"Calderas_8_9_10_Desaireador": {"DES": "300"}}.'


def read(p):
 with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f,delimiter=';'))

def rec(f):
 lazo=f['Lazo']; plc=f['PLC']; inst=f['Instancia']
 if not f['Area']:
  if 'SULFO_ENCALADO' in lazo:
   area='400 (recomendado; confirmar documentalmente)'
   just='El nombre SULFO_ENCALADO apunta a Clarificación y Encalado; Manual 83-97 define 400 para esa etapa, pero no existe prefijo ISA/override suficiente en la evidencia del lazo.'
  else:
   area='PENDIENTE (candidatos 500/700; no asignar)'
   just='FAB_ESCALADOS no tiene prefijo documentado inequívoco; requiere documentación de proceso o MAPEO_AREA_OVERRIDE_POR_PLC antes de numerar.'
 else:
  area=f["Area"]
  just='Área derivada del pase v4; verificar contra la tabla oficial antes de autorizar.'
 if 'CONTROL_NIVEL_06' in lazo:
  var='L'; fun='PENDIENTE'; just='El bloqueo tiene 12 entradas físicas compartidas y no cae en R-A/R-B/R-C; no se debe elegir variable/función por descarte.'
 elif 'FT_JUGO_SECUNDARIO' in lazo:
  var='F'; fun='Y';
 elif 'LT_TK_ENCALADO' in lazo or 'LT_TK_PESADO' in lazo:
  var='L'; fun='Y'
 elif 'C10_PC_HOGAR' in lazo or 'C8_PC_HOGAR' in lazo:
  var='P'; fun='PENDIENTE'; just='R-C identifica salidas analógicas paralelas, pero no demuestra que sean válvulas; D4 reserva V/XV a válvulas y exige identidad final.'
 elif 'BBA_AGUA_CENIZA' in lazo:
  var='L'; fun='PENDIENTE'; just='R-C identifica dos extremos físicos, pero no demuestra válvula frente a otro elemento final.'
 else:
  var='L'; fun='PENDIENTE'
 tags=f['Tags_Que_Se_Insertarian']
 return {
  'Lazo':lazo,'Clasificacion_Bloqueo':f['Clasificacion_Bloqueo'],'Regla_v5':f['Regla'],
  'Tags_Candidatos':tags,'Prefijos_Area_Conflicto':f['Criterio_Area'],
  'Evidencia_Manual_83_97':MANUAL,'Evidencia_Roadmap':ROADMAP,'Evidencia_MAPEO_AREA_OVERRIDE':OVERRIDE,
  'Recomendacion_Area':area,'Recomendacion_Variable':var,'Recomendacion_Funcion':fun,
  'Justificativo':just,'Evidencia_XML':f['Evidencia_XML'],'Motivo_Fuera_v5':f['Motivo_Fuera'],
  'Estado':'PENDIENTE_AUTORIZACION_EXPLICITA','Escritura_SQLite':'NO'
 }

rows=[rec(f) for f in read(FUERA)]
rows.sort(key=lambda x:x['Lazo'])
cols=list(rows[0])
with open(OUT,'w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=cols,delimiter=';',lineterminator='\n');w.writeheader();w.writerows(rows)
print(f'{len(rows)} decisiones -> {OUT}')
