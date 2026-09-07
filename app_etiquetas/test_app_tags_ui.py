import os
import tempfile
import unittest

import database as db
from app_tags import DICCIONARIOS, TagGovernanceApp, traducir_tag_humano


class InterfazInicioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory(prefix="tags-ui-test-")
        cls._old_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls._temp.name, "tags_ui_test.db")

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls._old_db_path
        cls._temp.cleanup()

    def setUp(self):
        self.app = TagGovernanceApp()
        self.app.update_idletasks()

    def tearDown(self):
        self.app.destroy()

    def test_lista_existentes_tiene_scroll_propio_y_binding_directo_de_rueda(self):
        self.assertTrue(hasattr(self.app, "scroll_lista_existentes"))
        self.assertTrue(self.app.lista_existentes.cget("yscrollcommand"))
        self.assertTrue(self.app.lista_existentes.bind("<MouseWheel>"))
        self.assertEqual(self.app._on_mousewheel_lista_existentes(type("E", (), {"delta": -120, "num": None})()), "break")

    def test_seleccionar_lista_no_abre_edicion_y_habilita_boton_explicito(self):
        self.app.lista_existentes.insert("end", "200_LT_036  —  Instalado  —  Nivel tanque")
        self.app.lista_existentes.selection_set(0)
        self.app._on_lista_existentes_seleccion()
        self.assertIsNone(self.app.tag_en_edicion)
        self.assertEqual(str(self.app.btn_editar_existente.cget("state")), "normal")

    def test_boton_editar_reutiliza_el_flujo_de_edicion_sin_activarse_al_seleccionar(self):
        area_key = next(key for key, row in self.app.areas.items() if row["codigo"] == "200")
        variable_key = next(key for key, row in self.app.variables.items() if row["letra"] == "L")
        funcion_key = next(key for key, row in self.app.funciones.items() if row["letra"] == "IT")
        area, variable, funcion = self.app.areas[area_key], self.app.variables[variable_key], self.app.funciones[funcion_key]
        db.crear_tag(
            tag_completo="200_LIT_001", area_id=area["id"], variable_id=variable["id"], funcion_id=funcion["id"],
            numero_loop=1, descripcion="Nivel tanque de prueba", creado_por="prueba",
        )
        self.app.cb_area.set(area_key)
        self.app.cb_variable.set(variable_key)
        self.app.cb_funcion.set(funcion_key)
        self.app.actualizar_propuesta()
        self.app.lista_existentes.selection_set(0)
        self.app._on_lista_existentes_seleccion()
        self.assertIsNone(self.app.tag_en_edicion)
        self.app._editar_existente_seleccionado()
        self.assertEqual(self.app.tag_en_edicion, "200_LIT_001")

    def test_lectura_humana_traduce_it_en_vez_de_mostrar_solo_las_siglas(self):
        texto = traducir_tag_humano("200_LIT_001", DICCIONARIOS)
        self.assertIn("Transmisor Indicador", texto)
        self.assertNotIn("IT de Nivel", texto)

    def test_inicio_tiene_estilos_destacados_y_layout_adaptable(self):
        self.assertEqual(self.app.app_style.lookup("PropuestaTag.TLabel", "background"), "#FFBB02")
        self.assertEqual(self.app.app_style.lookup("PropuestaTag.TLabel", "foreground"), "#002157")
        self.assertTrue(hasattr(self.app, "_adaptar_layout_inicio"))
        self.app._adaptar_layout_inicio(ancho=800)
        self.assertEqual(self.app.panel_busqueda.grid_info()["row"], 1)
        self.app._adaptar_layout_inicio(ancho=1400)
        self.assertEqual(self.app.panel_busqueda.grid_info()["row"], 0)


if __name__ == "__main__":
    unittest.main()
