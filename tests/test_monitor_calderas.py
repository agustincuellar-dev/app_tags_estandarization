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
    def test_inventario_completo_y_sin_repetidos(self):
        self.assertEqual(26, len(mc.SENALES))
        self.assertEqual(26, len({s.clave for s in mc.SENALES}))
        self.assertEqual(26, len({s.tag for s in mc.SENALES}))
        for s in mc.SENALES:
            self.assertIn(s.grupo, ("RPM", "CORRIENTE", "RTD"))
            self.assertIn(s.plc, mc.PLCS)

    def test_activas_y_archivadas(self):
        activas = mc.senales_activas()
        archivadas = [s for s in mc.senales_con_estado() if s.archivada]
        self.assertEqual(11, len(activas))
        self.assertEqual(15, len(archivadas))
        # toda archivada explica por qué, y ninguna se lee
        for s in archivadas:
            self.assertTrue(s.motivo.strip(), f"{s.clave} sin motivo")
        self.assertFalse({s.clave for s in activas} & {s.clave for s in archivadas})

    def test_rtd_activa_es_el_canal_1_del_modulo_7(self):
        rtd = [s for s in mc.senales_activas() if s.grupo == "RTD"]
        self.assertEqual(["C9_TT_ROD_VTI"], [s.clave for s in rtd])
        self.assertEqual("BP_ANALOGICA:7:I.Ch[1].Data", rtd[0].tag)

    def test_caldera_11_son_los_cinco_variadores_y_dos_corrientes(self):
        de11 = [s for s in mc.senales_activas() if s.plc == "cald11"]
        self.assertEqual(7, len(de11))
        self.assertEqual(5, len([s for s in de11 if s.grupo == "RPM"]))
        self.assertEqual(2, len([s for s in de11 if s.unidad == "%"]))
        self.assertEqual("192.168.10.251", mc.PLCS["cald11"])
        for s in de11:
            self.assertFalse(s.tag.startswith("Program:"))   # son tags de controlador

    def test_calderas_8_y_10_quedan_archivadas(self):
        archivadas = {s.clave for s in mc.senales_con_estado() if s.archivada}
        self.assertEqual(6, len({c for c in archivadas if c.startswith("C8_")}))
        self.assertEqual(6, len({c for c in archivadas if c.startswith("C10_")}))


class CorreccionSignoTests(unittest.TestCase):
    def test_rpm_negativo_se_corrige_con_el_desfase_int16(self):
        fuente = mc.FuentePLC("cald11")          # no conecta: sólo se usa _valor
        senal = next(s for s in mc.SENALES if s.clave == "CAL11_IDF1_RPM")
        self.assertAlmostEqual(416.04, fuente._valor(senal, -239.32), places=2)
        self.assertAlmostEqual(498.02, fuente._valor(senal, -157.34), places=2)
        self.assertAlmostEqual(750.0, fuente._valor(senal, 750.0), places=2)

    def test_señales_sin_correccion_no_se_tocan(self):
        fuente = mc.FuentePLC("calderas")
        senal = next(s for s in mc.SENALES if s.clave == "C9_ST_VTI")
        self.assertAlmostEqual(-5.0, fuente._valor(senal, -5.0), places=2)


class EstadoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="monitor_estado_"))
        self._original = mc.ESTADO_PATH
        mc.ESTADO_PATH = self.tmp / "senales_estado.json"

    def tearDown(self):
        mc.ESTADO_PATH = self._original
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reactivar_una_archivada_la_devuelve_a_la_lista(self):
        self.assertNotIn("C8_ST_VTF", {s.clave for s in mc.senales_activas()})
        mc.fijar_archivada("C8_ST_VTF", False)
        self.assertIn("C8_ST_VTF", {s.clave for s in mc.senales_activas()})
        self.assertEqual(12, len(mc.senales_activas()))

    def test_archivar_una_activa_la_saca_del_barrido(self):
        mc.fijar_archivada("C9_IT_VTI", True)
        self.assertNotIn("C9_IT_VTI", {s.clave for s in mc.senales_activas()})
        self.assertEqual(10, len(mc.senales_activas()))


class AlmacenYExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="monitor_test_"))
        self.almacen = mc.Almacen(self.tmp / "prueba.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _barrido(self, valor=500.0):
        return [{"clave": s.clave, "tag": s.tag, "descripcion": s.descripcion, "grupo": s.grupo,
                 "unidad": s.unidad, "valor": valor, "calidad": "OK", "error": None}
                for s in mc.senales_activas()]

    def test_guarda_una_fila_por_senal_activa(self):
        self.almacen.guardar_barrido("2026-10-30 10:00:00", self._barrido())
        total, primero, ultimo, instantes = self.almacen.resumen()
        self.assertEqual(11, total)
        self.assertEqual(1, instantes)
        self.assertEqual("2026-10-30 10:00:00", primero)

    def test_exporta_csv_con_punto_y_coma_y_bom(self):
        self.almacen.guardar_barrido("2026-10-30 10:00:00", self._barrido())
        ruta, n = mc.exportar_csv(self.almacen, self.tmp / "salida.csv")
        self.assertEqual(11, n)
        self.assertTrue(ruta.read_bytes().startswith(b"\xef\xbb\xbf"))
        filas = list(csv.DictReader(ruta.open(encoding="utf-8-sig"), delimiter=";"))
        self.assertEqual(11, len(filas))
        self.assertEqual(set(mc.COLUMNAS), set(filas[0]))

    def test_exporta_xlsx_con_hojas_lecturas_y_resumen(self):
        from openpyxl import load_workbook

        for ts in ("2026-10-30 10:00:00", "2026-10-30 10:00:30"):
            self.almacen.guardar_barrido(ts, self._barrido(valor=480.0))
        ruta, n = mc.exportar_xlsx(self.almacen, self.tmp / "salida.xlsx")
        self.assertEqual(22, n)
        wb = load_workbook(ruta)
        self.assertEqual(["Lecturas", "Resumen"], wb.sheetnames)
        self.assertEqual(23, wb["Lecturas"].max_row)      # encabezado + 22
        self.assertEqual(12, wb["Resumen"].max_row)       # encabezado + 11 activas


class BucleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="monitor_bucle_"))
        self.almacen = mc.Almacen(self.tmp / "bucle.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dos_ciclos_guardan_dos_barridos(self):
        n = mc.bucle_monitoreo(mc.FuenteSimulada(), self.almacen, intervalo=0.05, ciclos=2)
        self.assertEqual(2, n)
        total, _, _, instantes = self.almacen.resumen()
        self.assertEqual(22, total)
        self.assertGreaterEqual(instantes, 1)

    def test_el_bucle_se_detiene_con_el_evento(self):
        parar = threading.Event()
        threading.Thread(target=lambda: (parar.wait(0.2), parar.set()), daemon=True).start()
        n = mc.bucle_monitoreo(mc.FuenteSimulada(), self.almacen, intervalo=10, ciclos=None, parar=parar)
        self.assertGreaterEqual(n, 1)

    def test_persiste_calidad_sin_comunicacion(self):
        class FuenteRota:
            ip = "0.0.0.0"
            senales = tuple(mc.senales_activas())

            def leer(self):
                raise ConnectionError("sin respuesta")

            def cerrar(self):
                pass

        n = mc.bucle_monitoreo(FuenteRota(), self.almacen, intervalo=0.05, ciclos=1)
        self.assertEqual(1, n)
        import sqlite3

        con = sqlite3.connect(self.almacen.ruta)
        calidades = {r[0] for r in con.execute("SELECT DISTINCT calidad FROM lecturas")}
        filas = con.execute("SELECT COUNT(*) FROM lecturas").fetchone()[0]
        con.close()
        self.assertEqual({"SIN_COMUNICACION"}, calidades)
        self.assertEqual(11, filas)


if __name__ == "__main__":
    unittest.main(verbosity=2)
