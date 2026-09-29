"""Homologación de etiquetas de estado del plan v5.

Etapa puramente de etiquetado: no toca números, áreas, tags ni operaciones.
Lee v5 y escribe plan_maestro_consolidado_v5_homologado_290926.csv.
SQLite en mode=ro + query_only; cero escrituras.
"""
import csv
import hashlib
import re
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / 'exports'
DB = ROOT / 'app_etiquetas/tags_ingenio.db'
ENTRADA = 'plan_maestro_consolidado_v5_290926.csv'
SALIDA = 'plan_maestro_consolidado_v5_homologado_290926.csv'
EXPECTED_DB = 'dc4d9c212588bb91e17556e08dde263727545987868b45fb11da8fe7ebe80522'
EXPECTED_V5 = 'b90c0739c8314674088342259eee7969823d71bf51686639d01456e12b7499f1'
PROTECTED = {'200_PIT_004', '200_PIC_004', '200_PV_004', '200_LT_035', '200_LIC_035',
             '200_LV_035', '200_FT_080', '200_FIC_080', '200_FV_080', '250_PV_001', '250_PV_002'}
VIEJO = 'REVISAR_ANTES_DE_APLICAR'
NUEVO_ACTIVO = 'NO_INSERTAR_REVISION'
NUEVO_MANTENER = 'MANTENER_HOMOLOGADO'
ESPERADO = {('INSERT', 23), ('UPDATE', 19), ('DELETE', 11), ('MANTENER', 13)}
LIBRES = {'Estado_Maestro', 'Estado_Revision', 'Estado_Homologacion_V5'}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def leer(nombre):
    with (EX / nombre).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f, delimiter=';'))


def main():
    antes = digest(DB)
    if antes != EXPECTED_DB:
        raise RuntimeError('SQLite cambió; no se homologa')
    if digest(EX / ENTRADA) != EXPECTED_V5:
        raise RuntimeError('v5 cambió; no se homologa')
    con = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        if con.execute('PRAGMA query_only').fetchone()[0] != 1:
            raise RuntimeError('query_only no activo')
        prod = {r[0] for r in con.execute('SELECT tag_completo FROM tags')}
        if len(prod) != 196 or not PROTECTED <= prod:
            raise RuntimeError('Base inesperada')
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Integridad rota')

        filas = leer(ENTRADA)
        if len(filas) != 722:
            raise RuntimeError('Universo v5 inesperado')
        cols = list(filas[0])
        if len(cols) != len(set(cols)):
            raise RuntimeError('Columnas duplicadas')

        objetivo = [f for f in filas if f['Estado_Maestro'] == VIEJO]
        reparto = Counter(f['Operacion_Efectiva'] for f in objetivo)
        if len(objetivo) != 66 or set(reparto.items()) != ESPERADO:
            raise RuntimeError('Objetivo distinto del autorizado: ' + str(dict(reparto)))

        for f in objetivo:
            if f['Operacion_Efectiva'] == 'MANTENER':
                f['Estado_Maestro'] = NUEVO_MANTENER
                f['Estado_Revision'] = NUEVO_MANTENER
                f['Estado_Homologacion_V5'] = NUEVO_MANTENER
            else:
                f['Estado_Maestro'] = NUEVO_ACTIVO
                f['Estado_Revision'] = NUEVO_ACTIVO
                f['Estado_Homologacion_V5'] = 'HOMOLOGADO'

        # Invariantes: nada fuera de las etiquetas de estado y de la columna derivada.
        for a, b in zip(leer(ENTRADA), filas):
            distintos = {c for c in cols if a[c] != b[c]}
            if distintos - LIBRES:
                raise RuntimeError('Cambio no autorizado en ' + str(distintos))
        cuenta = Counter(f['Operacion_Efectiva'] for f in filas)
        if {k: cuenta[k] for k in ('INSERT', 'UPDATE', 'DELETE', 'MANTENER')} != {
                'INSERT': 294, 'UPDATE': 43, 'DELETE': 12, 'MANTENER': 13}:
            raise RuntimeError('Balance alterado: ' + str(dict(cuenta)))
        activas = [f for f in filas if f['Operacion_Efectiva'] in ('INSERT', 'UPDATE', 'DELETE')]
        dist = Counter(f['Estado_Maestro'] for f in activas)
        if dist != {NUEVO_ACTIVO: 332, 'UPDATE_METADATOS_NO_RENOMBRAR': 17}:
            raise RuntimeError('Distribución inesperada: ' + str(dict(dist)))
        for col in ('Estado_Maestro', 'Estado_Revision'):
            restantes = [f for f in filas if f[col] == VIEJO]
            if restantes:
                raise RuntimeError(f'Quedan {len(restantes)} filas con {VIEJO} en {col}')
        destinos = [f['Tag_Destino_Efectivo'] for f in activas if f['Operacion_Efectiva'] in ('INSERT', 'UPDATE')]
        if len(destinos) != len(set(destinos)):
            raise RuntimeError('Destinos repetidos')
        if any(not re.fullmatch(r'\d{3}_[A-Z]+_\d{3}[A-Z]?', t) for t in destinos):
            raise RuntimeError('Tag con forma inválida')
        colision = {f['Tag_Destino_Efectivo'] for f in activas if f['Operacion_Efectiva'] == 'INSERT'} & prod
        colision |= {f['Tag_Destino_Efectivo'] for f in activas if f['Operacion_Efectiva'] == 'UPDATE'
                     and f['Tag_Destino_Efectivo'] != f['Tag_Origen_Efectivo']} & prod
        if colision:
            raise RuntimeError('Destino ocupado por producción: ' + str(sorted(colision)))
        if any(f['Tag_Origen_Efectivo'] in PROTECTED or f['Tag_Destino_Efectivo'] in PROTECTED for f in activas):
            raise RuntimeError('Tag manual en operaciones activas')
        if any(f['Escritura_SQLite'] != 'NO' for f in filas):
            raise RuntimeError('Escritura_SQLite distinta de NO')
        if digest(DB) != antes:
            raise RuntimeError('SQLite cambió antes de emitir')

        with (EX / SALIDA).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, cols, delimiter=';', lineterminator='\n')
            w.writeheader()
            w.writerows(filas)

        final = leer(SALIDA)
        if final != filas:
            raise RuntimeError('CSV releído distinto')
        print('HOMOLOGADAS:', len(objetivo), 'filas |', dict(reparto))
        print('  activas homologadas:', sum(1 for f in objetivo if f['Operacion_Efectiva'] != 'MANTENER'),
              '| MANTENER homologadas:', reparto['MANTENER'])
        print('ACTIVAS:', len(activas), dict(dist))
        print('REVISAR_ANTES_DE_APLICAR restantes en Estado_Maestro/Estado_Revision: 0 / 0')
        print('BALANCE INSERT', cuenta['INSERT'], 'UPDATE', cuenta['UPDATE'], 'DELETE', cuenta['DELETE'],
              'MANTENER', cuenta['MANTENER'], '| proyectado', len(prod) + cuenta['INSERT'] - cuenta['DELETE'])
        print('filas', len(final), 'SHA-256', digest(EX / SALIDA))
        print('DB', len(prod), 'SHA-256 antes/después', antes, digest(DB), 'mode=ro query_only=ON; cero escrituras SQLite')
        if digest(DB) != antes:
            raise RuntimeError('SQLite cambió después de emitir')
    finally:
        con.close()


if __name__ == '__main__':
    main()
