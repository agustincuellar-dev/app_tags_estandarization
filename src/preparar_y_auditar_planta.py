"""Prepara los 10 L5X definitivos y ejecuta la auditoría topológica maestra.

El catálogo SQLite se abre exclusivamente mediante la capa read-only del auditor.
No modifica L5X ni tags_ingenio.db. La numeración se reserva en memoria para el
conjunto completo, evitando colisiones entre PLCs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sys
from pathlib import Path

try:
    from . import auditar_l5x as auditor
except ImportError:
    import auditar_l5x as auditor

ROOT = Path(__file__).resolve().parents[1]
PLCS_DEFINITIVOS = (
    'CALD_LA_FLORIDA.L5X',
    'CENTRIFUGA_DE_PRIMERA.L5X',
    'Calderas_8_9_10_Desaireador.L5X',
    'DESTILERIA.L5X',
    'DIBACCO.L5X',
    'FABRICA.L5X',
    'Painel_Ctr_Turb_Moenda.L5X',
    'TRAPICHE2022.L5X',
    'USINA_LA_FLORIDA.L5X',
    'cenizas2020.L5X',
)
TAGS_MANUALES_PROTEGIDOS = frozenset({
    '200_PIT_004', '200_PIC_004', '200_PV_004',
    '200_LT_035', '200_LIC_035', '200_LV_035',
    '200_FT_080', '200_FIC_080', '200_FV_080',
    '250_PV_001', '250_PV_002',
})
CAMPOS_MAESTROS = ['PLC_Origen', *auditor.CAMPOS_PROPUESTAS]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _resolver_fuentes(root: Path) -> dict[str, Path]:
    preferida = root / 'auto_agustin' / 'L5X_Auditados_Finales'
    resolved = {}
    for name in PLCS_DEFINITIVOS:
        primary = preferida / name
        if primary.is_file():
            resolved[name] = primary
            continue
        candidates = [path for path in root.rglob(name)
                      if path.is_file() and 'L5X_Produccion' not in path.parts]
        if len(candidates) != 1:
            detail = 'no encontrado' if not candidates else f'{len(candidates)} duplicados fuera de la carpeta prioritaria'
            raise FileNotFoundError(f'{name}: {detail}')
        resolved[name] = candidates[0]
    return resolved


def preparar_clean_room(root=ROOT) -> list[Path]:
    """Prevalida los 10 fuentes, vacía la sala y copia verificando contenido."""
    root = Path(root).resolve()
    sources = _resolver_fuentes(root)
    clean = root / 'L5X_Produccion'
    if clean.exists():
        if not clean.is_dir():
            raise NotADirectoryError(str(clean))
        shutil.rmtree(clean)
    clean.mkdir()
    copied = []
    try:
        for name in PLCS_DEFINITIVOS:
            destination = clean / name
            shutil.copy2(sources[name], destination)
            if _sha256(sources[name]) != _sha256(destination):
                raise OSError(f'Copia no coincide: {name}')
            copied.append(destination)
            print(f'[COPIADO {len(copied):02d}/10] {name}')
        actual = {p.name for p in clean.iterdir() if p.is_file()}
        if actual != set(PLCS_DEFINITIVOS):
            raise OSError('La sala limpia no contiene exactamente los 10 PLCs')
    except BaseException:
        shutil.rmtree(clean, ignore_errors=True)
        raise
    print('[OK] Se encontraron y copiaron correctamente los 10 archivos L5X.')
    return copied


def auditar_clean_room(clean_dir, db_path, output_path):
    """Audita solo la sala limpia y asigna números globalmente en memoria."""
    clean = Path(clean_dir).resolve()
    db = Path(db_path).resolve(strict=True)
    output = Path(output_path).resolve()
    expected = [clean / name for name in PLCS_DEFINITIVOS]
    actual = {p.name for p in clean.iterdir() if p.is_file()}
    if actual != set(PLCS_DEFINITIVOS) or not all(p.is_file() for p in expected):
        raise ValueError('L5X_Produccion debe contener exclusivamente los 10 PLCs definitivos')

    db_before = _sha256(db)
    catalog = auditor.leer_catalogo_solo_lectura(db)
    catalog_names = {row['tag_completo'] for row in catalog['tags']}
    missing = sorted(TAGS_MANUALES_PROTEGIDOS - catalog_names)
    if missing:
        raise ValueError('Faltan tags manuales protegidos: ' + ', '.join(missing))

    all_groups = []
    per_plc = []
    for index, path in enumerate(expected, 1):
        print(f'[AUDITANDO {index:02d}/10] {path.name}')
        top = auditor.parsear_topologia_l5x(path)
        groups = auditor.extraer_lazos_control(top)
        auditor.validar_lazos_con_catalogo(groups, catalog, top)
        for group in groups:
            group['_plc_origen_archivo'] = path.name
        all_groups.extend(groups)
        per_plc.append((path.name, groups))
        print(f'  Lazos topológicos detectados: {len(groups)}')

    # Una sola reserva global para toda la planta; el catálogo permanece intacto.
    auditor.proponer_familias_nuevas(all_groups, catalog)
    rows = []
    for filename, groups in per_plc:
        for row in auditor._filas_propuestas(groups):
            rows.append({'PLC_Origen': filename, **row})

    high_confidence = sum(bool(group.get('propuestas')) for group in all_groups)
    protected = sum(bool(group.get('protegido')) for group in all_groups)
    review = sum(bool(group.get('problemas')) and not group.get('protegido') for group in all_groups)
    if _sha256(db) != db_before:
        raise RuntimeError('La base cambió durante la auditoría; no se escribe el CSV')

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8-sig', newline='') as destination:
            writer = csv.DictWriter(destination, fieldnames=CAMPOS_MAESTROS, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)

    result = {
        'copiados': len(expected), 'lazos': len(all_groups),
        'alta_confianza': high_confidence, 'protegidos': protected,
        'tags_manuales_protegidos': len(TAGS_MANUALES_PROTEGIDOS),
        'revision': review, 'filas_csv': len(rows), 'csv': str(output),
        'db_sha256': db_before,
    }
    print(f'[OK] Catálogo abierto en modo solo lectura; los {len(TAGS_MANUALES_PROTEGIDOS)} tags manuales están protegidos.')
    print(f'[OK] CSV maestro: {output}')
    print(f"[RESUMEN] Lazos={result['lazos']} | Alta confianza={high_confidence} | Tags manuales protegidos={len(TAGS_MANUALES_PROTEGIDOS)} | Lazos coincidentes protegidos={protected} | Revisión={review} | Filas CSV={len(rows)}")
    return result


def ejecutar_pipeline(root=ROOT, db_path=None, output_path=None):
    root = Path(root).resolve()
    db = Path(db_path) if db_path else root / 'app_etiquetas' / 'tags_ingenio.db'
    output = Path(output_path) if output_path else root / 'exports' / 'auditoria_planta_completa.csv'
    copied = preparar_clean_room(root)
    return auditar_clean_room(copied[0].parent, db, output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--db', type=Path)
    parser.add_argument('--salida', type=Path)
    args = parser.parse_args(argv)
    try:
        ejecutar_pipeline(args.root, args.db, args.salida)
        return 0
    except Exception as error:
        print(f'[ABORTADO] {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
