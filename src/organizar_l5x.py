"""Inventario recursivo por fecha; no mueve ni modifica los fuentes."""
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def organizar(root=ROOT, reporte=None):
    root=Path(root).resolve()
    reporte=Path(reporte) if reporte else root/'exports/reporte_l5x.txt'
    rows=[]
    def fail(error):
        raise error
    for directory, _, files in os.walk(root, onerror=fail, followlinks=False):
        for name in files:
            if Path(name).suffix.lower()=='.l5x':
                path=Path(directory)/name
                rows.append((path.stat().st_mtime_ns,path))
    rows.sort(key=lambda row:(-row[0],str(row[1]).casefold()))
    lines=['Inventario L5X — más reciente a más antiguo',f'Raíz: {root}',
           'Fecha de modificación local con zona horaria | Ruta relativa',
           'La fecha no certifica que el archivo sea definitivo ni su coincidencia con Yanco.', '']
    for stamp,path in rows:
        date=datetime.fromtimestamp(stamp/1_000_000_000, timezone.utc).astimezone().isoformat(timespec='microseconds')
        lines.append(f'{date} | {path.relative_to(root)}')
    lines.append(f'\nTotal: {len(rows)}')
    reporte.parent.mkdir(parents=True,exist_ok=True)
    reporte.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return rows


if __name__=='__main__':
    rows=organizar()
    print((ROOT/'exports/reporte_l5x.txt').read_text(encoding='utf-8'))
