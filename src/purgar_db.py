"""Purga autorizada: protege 200_P_004, 200_L_035, 200_F_080 y dos válvulas.
Por defecto solo muestra la selección. --ejecutar respalda y aplica la purga.
No inicializa catálogos ni modifica los registros protegidos.
"""
import argparse
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def protegido(tag):
    return int(tag in ('250_PV_001','250_PV_002') or bool(re.fullmatch(
        r'200_(?:P[A-Z]*_004|L[A-Z]*_035|F[A-Z]*_080)(?:[AB]|A/B)?',tag or '')))


def purgar(db):
    db=Path(db).resolve()
    with closing(sqlite3.connect(db.as_uri()+'?mode=rw',uri=True,isolation_level=None)) as c:
        c.create_function('protegido',1,protegido,deterministic=True)
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('BEGIN IMMEDIATE')
        try:
            if c.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('La base ya tiene referencias inválidas; se aborta')
            saved=c.execute('SELECT * FROM tags WHERE protegido(tag_completo) ORDER BY id').fetchall()
            if not saved:
                raise ValueError('No se encontraron protegidos; se aborta por seguridad')
            before=c.execute('SELECT count(*) FROM tags').fetchone()[0]
            backup=db.parent/'backups'/('tags_ingenio_antes_purga_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.db')
            backup.parent.mkdir(exist_ok=True)
            # Conexión separada: backup consistente también en WAL. El bloqueo
            # de escritura evita cambios entre el respaldo y el DELETE.
            with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(backup)) as dest:
                source.backup(dest)
                if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ValueError('Respaldo inválido')
                if list(source.iterdump())!=list(dest.iterdump()):
                    raise ValueError('Respaldo no coincide con origen')
            # Conservar la bitácora, sin referencias huérfanas ni borrar historia.
            c.execute("""UPDATE auditoria SET detalle=COALESCE(detalle,'') ||
                '\n[Purga: tag_id=' || tag_id || '; tag_original=' ||
                (SELECT tag_completo FROM tags WHERE tags.id=auditoria.tag_id) || ']',
                tag_id=NULL WHERE tag_id IN (SELECT id FROM tags WHERE NOT protegido(tag_completo))""")
            deleted=c.execute('DELETE FROM tags WHERE NOT protegido(tag_completo)').rowcount
            after=c.execute('SELECT * FROM tags ORDER BY id').fetchall()
            if after!=saved or before-deleted!=len(saved):
                raise ValueError('Falló verificación de protegidos; rollback')
            if c.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Referencias inválidas; rollback')
            c.execute('COMMIT')
            return dict(eliminados=deleted,protegidos=len(saved),backup=str(backup))
        except BaseException:
            if c.in_transaction: c.execute('ROLLBACK')
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=ROOT/'app_etiquetas/tags_ingenio.db')
    parser.add_argument('--ejecutar',action='store_true')
    args=parser.parse_args()
    if not args.ejecutar:
        with closing(sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            rows=c.execute('SELECT tag_completo FROM tags ORDER BY tag_completo').fetchall()
        keep=[r[0] for r in rows if protegido(r[0])]
        print('SIMULACIÓN: sin cambios\nProtegidos:\n'+'\n'.join(keep))
        print(f'A eliminar: {len(rows)-len(keep)}; a conservar: {len(keep)}')
        return
    result=purgar(args.db)
    print(f"Backup: {result['backup']}\nEliminados: {result['eliminados']}\nProtegidos conservados: {result['protegidos']}")


if __name__=='__main__': main()
