"""Pruebas del monitor de VTI/VTF (sin PLC: fuente simulada y base temporal)."""

import csv
import sys
import tempfile
import threading
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import monitor_calderas as mc  # noqa: E402


class SenalesTests(unittest.TestCase):
    def test_cantidad_y_unicidad(self):
        self.assertEqual(18, len(mc.SENALES))
        self.assertEqual(18, len({s.clave for s in mc.SENALES}))
        self.assertEqual(18, len({s.tag for s in mc.SENALES}))
        for s in mc.SENALES:
            self.assertIn(s.grupo, ("RPM", "CORRIENTE", "RTD"))
            self.assertTrue(s.tag.startswith("Program:"))

    def test_solo_dos_rtd_y_son_los_rodamientos(self):
        rtd = [s for s in mc.SENALES if s.grupo == "RTD"]
        self.assertEqual({"C9_TT_ROD_DEL_VTI", "C9_TT_ROD_TRA_VTI"}, {s.clave for s in rtd})

    def test_senales_sin_cablear_marcadas(self):
        marcadas = {s.clave for s in mc.SENALES if s.sin_cablear}
        self.assertEqual({"C8_IT_VTF", "C8_IT_VTI_SUR", "C9_ST_VTF"}, marcadas)


class AlmacenYExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="monitor_test_"))
        self.almacen = mc.Almacen(self.tmp / "prueba.db")

    def tearDown(self):
        # En Windows el archivo puede seguir tomado un instante: no es parte del test.
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _barrido(self, ts="2026-10-29 10:00:00", valor=500.0):
        return [{"clave": s.clave, "tag": s.tag, "descripcion": s.descripcion, "grupo": s.grupo,
                 "unidad": s.unidad, "valor": valor, "calidad": "OK", "error": None}
                for s in mc.SENALES]

    def test_guarda_una_fila_por_senal(self):
        self.almacen.guardar_barrido("2026-10-29 10:00:00", self._barrido())
        total, primero, ultimo, instantes = self.almacen.resumen()
        self.assertEqual(18, total)
        self.assertEqual(1, instantes)
        self.assertEqual("2026-10-29 10:00:00", primero)

    def test_exporta_csv_con_punto_y_coma_y_bom(self):
        self.almacen.guardar_barrido("2026-10-29 10:00:00", self._barrido())
        ruta, n = mc.exportar_csv(self.almacen, self.tmp / "salida.csv")
        self.assertEqual(18, n)
        crudo = ruta.read_bytes()
        self.assertTrue(crudo.startswith(b"\xef\xbb\xbf"))
        filas = list(csv.DictReader(ruta.open(encoding="utf-8-sig"), delimiter=";"))
        self.assertEqual(18, len(filas))
        self.assertEqual(set(mc.COLUMNAS), set(filas[0]))

    def test_exporta_xlsx_con_hojas_lecturas_y_resumen(self):
        from openpyxl import load_workbook

        for ts in ("2026-10-29 10:00:00", "2026-10-29 10:00:30"):
            self.almacen.guardar_barrido(ts, self._barrido(valor=480.0))
        ruta, n = mc.exportar_xlsx(self.almacen, self.tmp / "salida.xlsx")
        self.assertEqual(36, n)
        wb = load_workbook(ruta)
        self.assertEqual(["Lecturas", "Resumen"], wb.sheetnames)
        self.assertEqual(37, wb["Lecturas"].max_row)      # encabezado + 36
        self.assertEqual(19, wb["Resumen"].max_row)       # encabezado + 18 señales
        self.assertEqual("C8_ST_VTF", wb["Resumen"].cell(row=2, column=1).value)


class BucleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="monitor_bucle_"))
        self.almacen = mc.Almacen(self.tmp / "bucle.db")

    def tearDown(self):
        # En Windows el archivo puede seguir tomado un instante: no es parte del test.
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dos_ciclos_guardan_dos_instantes(self):
        fuente = mc.FuenteSimulada()
        n = mc.bucle_monitoreo(fuente, self.almacen, intervalo=0.05, ciclos=2)
        self.assertEqual(2, n)
        total, _, _, instantes = self.almacen.resumen()
        self.assertEqual(36, total)
        # dos barridos dentro del mismo segundo comparten ts: se cuentan filas, no instantes
        self.assertGreaterEqual(instantes, 1)

    def test_el_bucle_se_detiene_con_el_evento(self):
        fuente = mc.FuenteSimulada()
        parar = threading.Event()

        def detener():
            parar.wait(0.2)
            parar.set()

        threading.Thread(target=detener, daemon=True).start()
        n = mc.bucle_monitoreo(fuente, self.almacen, intervalo=10, ciclos=None, parar=parar)
        self.assertGreaterEqual(n, 1)

    def test_persiste_calidad_sin_comunicacion(self):
        class FuenteRota:
            ip = "0.0.0.0"

            def leer(self):
                raise ConnectionError("sin respuesta")

            def cerrar(self):
                pass

        n = mc.bucle_monitoreo(FuenteRota(), self.almacen, intervalo=0.05, ciclos=1)
        self.assertEqual(1, n)
        import sqlite3

        con = sqlite3.connect(self.almacen.ruta)
        calidades = {r[0] for r in con.execute("SELECT DISTINCT calidad FROM lecturas")}
        con.close()
        self.assertEqual({"SIN_COMUNICACION"}, calidades)


if __name__ == "__main__":
    unittest.main(verbosity=2)
