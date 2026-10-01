"""Plan maestro "puro proceso" (29/09/2026): filtra los instrumentos electromecánicos
y de máquina del plan homologado v5 y renumera los INSERT resultantes.

Reglas pedidas:
  R1. Quitar INSERT con Variable_Efectiva I (corriente), S (velocidad) o V (vibración).
  R2. Quitar INSERT de T/P cuya identidad contenga MOTOR, BOBINA, ROD, CCM, COJINETE,
      ACEITE o AXIAL.
  R3. Incorporar los dos caudalímetros de proceso de TRAPICHE (vapor del desfibrador y
      agua de lavado de tamices).
  R4. Renumerar los INSERT resultantes para que no queden huecos en cada área.

El renumero respeta:
  - los números de lazo que ya existen en producción (196) y los que crean los renombres,
    que nunca se reasignan (un lazo sensor-controlador-válvula comparte número);
  - los INSERT que se suman a un lazo de producción existente (mantienen su número);
  - los números liberados por bajas/renombres, que no se reciclan.

Uso:  python src/generar_plan_puro_proceso_290926.py
"""
import csv
import pathlib
import sqlite3
import collections
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENTRADA = ROOT / 'exports/plan_maestro_consolidado_v5_homologado_290926.csv'
SALIDA = ROOT / 'exports/plan_maestro_puro_proceso_290926.csv'
REMAP = ROOT / 'exports/remap_numeracion_puro_proceso_290926.csv'
BASE196 = ROOT / 'app_etiquetas/backups/tags_ingenio_pre_v5_196tags_290926.db'
PALABRAS = ['MOTOR', 'BOBINA', 'ROD', 'CCM', 'COJINETE', 'ACEITE', 'AXIAL']
CAMPOS_IDENTIDAD = ('Identidad_PLC_Efectiva', 'Identidad_PLC', 'Destino_Fisico',
                    'Bloque_Maestro', 'Nota_Maestra')


def texto_identidad(r):
    return ' | '.join((r.get(c) or '') for c in CAMPOS_IDENTIDAD).upper()


def motor_electrico(r):
    """True si la fila es de variable I/S/V o es un T/P mecánico."""
    v = (r.get('Variable_Efectiva') or '').strip()
    if v in ('I', 'S', 'V'):
        return 'variable ' + v, v in ('I', 'S', 'V')
    if v in ('T', 'P'):
        hits = [p for p in PALABRAS if p in texto_identidad(r)]
        if hits:
            return 'T/P mecánico: ' + ','.join(hits), True
    return '', False


def lazos_base():
    """Números de lazo ocupados por área DESPUÉS de aplicar bajas y renombres del plan."""
    con = sqlite3.connect(BASE196.as_uri() + '?mode=ro', uri=True)
    con.execute('PRAGMA query_only=ON')
    filas = {r[0]: (r[1], int(r[2]), r[3]) for r in con.execute(
        'select t.id, a.codigo, t.numero_loop, t.tag_completo from tags t '
        'join areas a on a.id=t.area_id')}
    con.close()
    plan = list(csv.DictReader(ENTRADA.open(encoding='utf-8-sig'), delimiter=';'))
    ocupados = collections.defaultdict(set)
    for _id, (cod, num, _tag) in filas.items():
        ocupados[cod].add(num)
    reservados = collections.defaultdict(set)   # números liberados, no reciclables
    for r in plan:
        if r['Operacion_Efectiva'] == 'DELETE':
            cod, num, _ = filas[int(r['ID_Origen_Efectivo'])]
            ocupados[cod].discard(num)
            reservados[cod].add(num)
    for r in plan:
        if r['Operacion_Efectiva'] == 'UPDATE' and r['Tag_Origen_Efectivo'] != r['Tag_Destino_Efectivo']:
            cod, num, _ = filas[int(r['ID_Origen_Efectivo'])]
            nuevo_num = int(r['Tag_Destino_Efectivo'].split('_')[-1].rstrip('ABCDEF'))
            ocupados[cod].discard(num)
            ocupados[cod].add(nuevo_num)
            reservados[cod].add(num)
    return ocupados, reservados


def main():
    plan = list(csv.DictReader(ENTRADA.open(encoding='utf-8-sig'), delimiter=';'))
    campos = list(plan[0].keys())
    for c in ('Tag_PreFiltro', 'Numero_PreFiltro', 'Motivo_Filtro', 'Motivo_Renumero'):
        if c not in campos:
            campos.append(c)
    ocupados, reservados = lazos_base()

    activos = [r for r in plan if r['Operacion_Efectiva'] in ('INSERT', 'UPDATE', 'DELETE')]
    ins = [r for r in plan if r['Operacion_Efectiva'] == 'INSERT']
    fuera, quedan = [], []
    for r in ins:
        motivo, es = motor_electrico(r)
        (fuera if es else quedan).append((r, motivo))

    print('=== FILTRO (paso 2) ===')
    print(f'  INSERT en el plan homologado : {len(ins)}')
    print(f'  fuera por ser electromecánico: {len(fuera)}')
    por_var = collections.Counter(r['Variable_Efectiva'] for r, _ in fuera)
    print('    por variable:', dict(sorted(por_var.items())))
    for r, m in fuera:
        if m.startswith('T/P'):
            print(f'      {r["Tag_Destino_Efectivo"]:16s} {m:22s} {r["Identidad_PLC_Efectiva"][:56]}')
    print(f'  quedan (proceso puro)        : {len(quedan)}')

    # R3: los dos caudalímetros de TRAPICHE
    nuevos = []
    for tag, canal, ident in (('100_FT_031', 'Local:3:I.Ch2Data', 'FT_VAPOR_DESFIBRADOR'),
                              ('100_FT_032', 'Local:3:I.Ch4Data', 'FT_AGUA_LAVADO_TAMIS')):
        nuevos.append({'Tag_Destino_Efectivo': tag, 'Area_Efectiva': '100', 'Variable_Efectiva': 'F',
                       'Identidad_PLC_Efectiva': ident, 'Direccion_Modulo_Efectiva': canal,
                       'Operacion_Efectiva': 'INSERT', 'Estado_Maestro': 'NO_INSERTAR_REVISION',
                       'Estado_Homologacion_V5': 'HOMOLOGADO', 'Estado_Revision': 'NO_INSERTAR_REVISION',
                       'Bloque_Maestro': 'DESTRABE_TRAPICHE_PURO_PROCESO',
                       'Nota_Maestra': f'Caudalímetro de proceso de TRAPICHE ({canal}); '
                                       'identidad tomada del bloque vivo de la rutina CAUDAL.'})
    print('\n=== R3: caudalímetros de TRAPICHE agregados ===')
    for n in nuevos:
        print(f'  {n["Tag_Destino_Efectivo"]}  {n["Direccion_Modulo_Efectiva"]}  {n["Identidad_PLC_Efectiva"]}')

    # R4: renumero de los lazos NUEVOS (los que extienden un lazo de producción conservan número)
    grupos = collections.defaultdict(list)
    for r, _ in quedan:
        grupos[(r['Area_Efectiva'], int(r['Numero_Efectivo']))].append(r)
    for n in nuevos:
        grupos[(n['Area_Efectiva'], 'NUEVO_' + n['Tag_Destino_Efectivo'])].append(n)

    asignados = collections.defaultdict(set)
    remap = []
    for r, _ in quedan:                       # las extensiones de lazo conservan su número
        cod, num = r['Area_Efectiva'], int(r['Numero_Efectivo'])
        if num in ocupados[cod]:
            asignados[cod].add(num)
    orden = sorted(grupos.items(), key=lambda kv: (kv[0][0], isinstance(kv[0][1], str), kv[0][1]))
    for (cod, clave), filas in orden:
        num_orig = 0 if isinstance(clave, str) else clave
        if num_orig and num_orig in ocupados[cod]:
            continue                          # extiende un lazo existente: no se toca
        libre = 1
        while libre in ocupados[cod] or libre in reservados[cod] or libre in asignados[cod]:
            libre += 1
        asignados[cod].add(libre)
        for r in filas:
            viejo = r.get('Tag_Destino_Efectivo', '')
            morfema = viejo.split('_')[1]
            cola = viejo.rsplit('_', 1)[1]
            sufijo = cola[3:] if len(cola) > 3 else ''
            nuevo = f'{cod}_{morfema}_{libre:03d}{sufijo}'
            r['Tag_PreFiltro'] = viejo
            r['Numero_PreFiltro'] = r.get('Numero_Efectivo', '')
            r['Tag_Destino_Efectivo'] = nuevo
            r['Numero_Efectivo'] = str(libre)
            r['Motivo_Renumero'] = (f'lazo nuevo del área {cod}: {num_orig or "nuevo"} → {libre}'
                                    if str(num_orig) != str(libre) else 'sin cambio')
            remap.append((cod, num_orig, libre, viejo, nuevo))

    # ---- verificación dura antes de emitir
    destinos = [r['Tag_Destino_Efectivo'] for r, _ in quedan] + [n['Tag_Destino_Efectivo'] for n in nuevos]
    assert len(destinos) == len(set(destinos)), 'destinos duplicados tras el renumero'
    con = sqlite3.connect(BASE196.as_uri() + '?mode=ro', uri=True)
    prod = {r[0] for r in con.execute('select tag_completo from tags')}
    con.close()
    for r in [x for x, _ in quedan] + nuevos:
        assert r['Tag_Destino_Efectivo'] not in prod, 'colisión con producción: ' + r['Tag_Destino_Efectivo']
    for cod, num_orig, libre, viejo, nuevo in remap:
        if num_orig and num_orig in ocupados[cod]:
            assert viejo == nuevo, 'se renumeró un lazo existente'
    por_area = collections.Counter(r['Area_Efectiva'] for r, _ in quedan)
    for n in nuevos:
        por_area['100'] += 1

    # ---- emisión
    salida = []
    for r in plan:
        if r['Operacion_Efectiva'] == 'INSERT':
            if any(r is f for f, _ in fuera):
                continue
            salida.append(r)
        else:
            salida.append(r)
    salida.extend(nuevos)
    with SALIDA.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=';', extrasaction='ignore')
        w.writeheader()
        for r in salida:
            w.writerow({c: r.get(c, '') for c in campos})
    with REMAP.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Area', 'Numero_PreFiltro', 'Numero_Nuevo', 'Tag_PreFiltro', 'Tag_Nuevo'])
        w.writerows(sorted(remap, key=lambda x: (x[0], x[1])))

    proy = 196 + len(quedan) + len(nuevos) - 12
    print('\n=== RESULTADO ===')
    print(f'  INSERT: {len(quedan)} + {len(nuevos)} = {len(quedan) + len(nuevos)}')
    print(f'  UPDATE: {sum(1 for r in plan if r["Operacion_Efectiva"] == "UPDATE")} | '
          f'DELETE: {sum(1 for r in plan if r["Operacion_Efectiva"] == "DELETE")}')
    print(f'  proyección: 196 + {len(quedan) + len(nuevos)} - 12 = {proy} tags')
    print('  INSERT por área:', dict(sorted(por_area.items())))
    print(f'  renumerados: {sum(1 for x in remap if x[3] != x[4])} de {len(remap)} grupos')
    print(f'\n  {SALIDA.relative_to(ROOT)}\n  {REMAP.relative_to(ROOT)}')


if __name__ == '__main__':
    sys.exit(main())
