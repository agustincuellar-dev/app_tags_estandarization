"""Abre el monitor y arranca el barrido automáticamente (sin tocar Iniciar).

Es la misma entrada que el .exe: valida instancia única y arranca el barrido.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import monitor_calderas_gui as gui  # noqa: E402

gui.main()
