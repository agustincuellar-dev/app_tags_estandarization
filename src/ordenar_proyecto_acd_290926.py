"""Ordenamiento de carpetas: ACD de Studio 5000, catálogo vigente y exports.

Uso:
  python src/ordenar_proyecto_acd_290926.py            # sólo plan (no toca nada)
  python src/ordenar_proyecto_acd_290926.py --apply    # copia y mueve

Reglas:
  - No toca app_etiquetas/, src/, tests/, L5X_Produccion/, docs/.
  - No mueve nada que src/ o tests/ referencien por ruta (exports/*.csv).
  - Escribe MAPA_MOVIMIENTOS_290926.csv para poder revertir cada movimiento.
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'app_etiquetas/tags_ingenio.db'
EXPECTED_DB = '601519b9c76d1d789b50d77df613fe642c92531f1cbf7c9259c618fb61c6f92b'
REVISION = ROOT / '00_REVISION_STUDIO5000_HOY'
ORDENADO = ROOT / 'archivo_ordenado'
CATALOGO = ORDENADO / 'ACD_Catalogo_Vigentes'
HISTORICOS = ORDENADO / 'ACD_Historicos_y_Backups'
EXPORTS = ROOT / 'exports'
HIST_EXPORTS = EXPORTS / 'historico_iteraciones'
MIN_MB = 2.0
PLCS = [('TRAPICHE2022', 'trapiche2022'), ('DESTILERIA', 'destileria'),
        ('Calderas_8_9_10_Desaireador', 'calderas_8_9_10'), ('FABRICA', 'fabrica'),
        ('DIBACCO', 'dibacco'), ('CALD_LA_FLORIDA', 'cald_la_florida'),
        ('cenizas2020', 'cenizas2020'), ('CENTRIFUGA_DE_PRIMERA', 'centrifuga_de_primera'),
        ('USINA_LA_FLORIDA', 'usina_la_florida')]
REVISION_PLCS = {'TRAPICHE2022', 'DESTILERIA', 'Calderas_8_9_10_Desaireador'}
ORIGEN = {'archivos ACD y L5X auditados': 'auditados', 'ACD_Para_Convertir': 'paraconvertir',
          'data_historica': 'datahistorica', 'auto_agustin': 'autoagustin', 'p pasar': 'ppasar'}
MAESTROS = ['plan_maestro_consolidado_v5_homologado_290926.csv',
            'plan_maestro_consolidado_v5_290926.csv',
            'estado_tagueo_prioridad_1_2_280926.csv']


def fecha(t):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(t))


def inventario_acd():
    inv = []
    for dp, dirs, files in os.walk(ROOT):
        for f in files:
            if f.lower().endswith(('.acd', '.bak')):
                p = Path(dp) / f
                try:
                    st = p.stat()
                except OSError:
                    continue
                inv.append({'abs': p, 'rel': p.relative_to(ROOT).as_posix(), 'size': st.st_size,
                            'mtime': st.st_mtime})
    return inv


def seleccionar(inv):
    """Vigente por PLC: el .acd/.bak más reciente con tamaño de proyecto completo."""
    candidatos = defaultdict(list)
    for r in inv:
        base = Path(r['rel']).name.lower()
        if '__dup' in base or '__17' in base or r['size'] < MIN_MB * 1048576:
            continue
        for plc, pref in PLCS:
            if base.startswith(pref):
                candidatos[plc].append(r)
                break
    elegidos, alternativas = {}, {}
    for plc, _ in PLCS:
        lista = sorted(candidatos[plc], key=lambda r: -r['mtime'])
        if not lista:
            raise SystemExit('Sin candidato para ' + plc)
        elegidos[plc] = lista[0]
        alternativas[plc] = lista[1:4]
    return elegidos, alternativas


def plan_exports():
    """Un CSV se conserva si su nombre aparece citado en src/, tests/ o app_etiquetas/."""
    texto = []
    for carpeta in ('src', 'tests', 'app_etiquetas'):
        for dp, dirs, files in os.walk(ROOT / carpeta):
            if '__pycache__' in dp:
                continue
            for f in files:
                if f.endswith('.py'):
                    texto.append((Path(dp) / f).read_text(encoding='utf-8', errors='ignore'))
    blob = '\n'.join(texto)
    mover, quedar = [], []
    for f in sorted(EXPORTS.iterdir()):
        if f.name in MAESTROS or f.name == HIST_EXPORTS.name or f.name in blob:
            quedar.append(f)
        else:
            mover.append(f)
    referenciados = {f.name for f in quedar} - set(MAESTROS)
    return mover, quedar, referenciados


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    if hashlib.sha256(DB.read_bytes()).hexdigest() != EXPECTED_DB:
        raise SystemExit('tags_ingenio.db no está en el estado esperado de 478 tags')

    inv = inventario_acd()
    elegidos, alternativas = seleccionar(inv)
    seleccionados = {r['abs'] for r in elegidos.values()}
    a_mover = [r for r in inv if r['abs'] not in seleccionados]
    mueve_exp, queda_exp, referenciados = plan_exports()

    # destino corto y único por archivo (se conserva el origen como subcarpeta)
    plan, usados = [], Counter()
    for r in a_mover:
        top = r['rel'].split('/')[0]
        grupo = ORIGEN.get(top, 'otros')
        destino = HISTORICOS / grupo / Path(r['rel']).name
        while destino.exists() or str(destino) in usados:
            usados[str(destino)] += 1
            destino = destino.with_name(f'{destino.stem}__{usados[str(destino)] + 1}{destino.suffix}')
        usados[str(destino)] += 1
        plan.append({'origen': r['abs'], 'destino': destino, 'rel': r['rel'],
                     'size': r['size'], 'mtime': r['mtime']})

    print('=== SELECCIÓN DE VIGENTES (regla: .acd/.bak sin marca de duplicado, >= 2 MB, más reciente) ===')
    for plc, _ in PLCS:
        r = elegidos[plc]
        rol = 'REVISION' if plc in REVISION_PLCS else 'catalogo'
        print(f'  {rol:9s} {plc:32s} {fecha(r["mtime"])}  {r["size"] / 1048576:6.2f} MB  {r["rel"]}')
        for a in alternativas[plc][:2]:
            print(f'            alternativa: {fecha(a["mtime"])}  {a["size"] / 1048576:6.2f} MB  {a["rel"]}')
    print(f'\n=== ACD PARA ARCHIVAR: {len(plan)} archivos ({len(inv)} totales - {len(elegidos)} vigentes) ===')
    print('  por origen:', dict(Counter(p['destino'].relative_to(HISTORICOS).parts[0] for p in plan)))
    print(f'\n=== exports/: {len(mueve_exp)} a historico_iteraciones, {len(queda_exp)} quedan en la raíz ===')
    print('  quedan:', sorted(f.name for f in queda_exp)[:30])
    print('  referenciados por src/tests (no se mueven):', len(referenciados))

    if not args.apply:
        print('\nPLAN: no se copió ni movió nada. Volvé a correr con --apply.')
        return

    # ---- copias visibles
    REVISION.mkdir(exist_ok=True)
    CATALOGO.mkdir(parents=True, exist_ok=True)
    nombres_rev = {'TRAPICHE2022': '1_TRAPICHE2022.ACD', 'DESTILERIA': '2_DESTILERIA.ACD',
                   'Calderas_8_9_10_Desaireador': '3_Calderas_8_9_10_Desaireador.ACD'}
    copias = []
    for plc, nombre in nombres_rev.items():
        shutil.copy2(elegidos[plc]['abs'], REVISION / nombre)
        copias.append((REVISION / nombre, elegidos[plc]))
    for plc, _ in PLCS:
        if plc in REVISION_PLCS:
            continue
        shutil.copy2(elegidos[plc]['abs'], CATALOGO / f'{plc}.ACD')
        copias.append((CATALOGO / f'{plc}.ACD', elegidos[plc]))
    for destino, r in copias:
        if not destino.exists() or destino.stat().st_size != r['size']:
            raise SystemExit('Copia incompleta: ' + str(destino))
    print(f'\nCOPIAS: {len(copias)} archivos (3 en revisión + 6 en catálogo)')

    # ---- movimientos
    HISTORICOS.mkdir(parents=True, exist_ok=True)
    movidos, fallidos = 0, []
    for p in plan:
        try:
            p['destino'].parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p['origen']), str(p['destino']))
            movidos += 1
        except OSError as e:
            fallidos.append((p['rel'], str(e)))
    mapa = ORDENADO / 'MAPA_MOVIMIENTOS_290926.csv'
    with mapa.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Ruta_Original', 'Ruta_Nueva', 'Bytes', 'Fecha_Original'])
        for p in plan:
            w.writerow([p['rel'], p['destino'].relative_to(ROOT).as_posix(), p['size'], fecha(p['mtime'])])
    print(f'MOVIMIENTOS: {movidos} movidos, {len(fallidos)} fallidos -> mapa en {mapa.relative_to(ROOT)}')
    for f_ in fallidos[:5]:
        print('  falló:', f_)

    HIST_EXPORTS.mkdir(exist_ok=True)
    for f in mueve_exp:
        shutil.move(str(f), str(HIST_EXPORTS / f.name))
    print(f'exports/: {len(mueve_exp)} entradas movidas a historico_iteraciones/')

    print('SHA-256 tags_ingenio.db:', hashlib.sha256(DB.read_bytes()).hexdigest())
    con = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    con.execute('PRAGMA query_only=ON')
    print('tags:', con.execute('select count(*) from tags').fetchone()[0],
          '| integridad:', con.execute('pragma integrity_check').fetchone()[0])
    con.close()
    (ORDENADO / 'inventario_acd_y_exports_290926.json').write_text(
        json.dumps({'vigentes': {k: v['rel'] for k, v in elegidos.items()},
                    'alternativas': {k: [a['rel'] for a in v] for k, v in alternativas.items()},
                    'movidos': len(plan), 'fallidos': len(fallidos),
                    'exports_a_historico': [f.name for f in mueve_exp],
                    'exports_retenidos': [f.name for f in queda_exp]}, indent=2, ensure_ascii=False),
        encoding='utf-8')


if __name__ == '__main__':
    sys.exit(main())
