import os
import tempfile
import unittest

import database as db
import app_tags
from app_tags import DICCIONARIOS, TagGovernanceApp, plc_para_tabla, traducir_tag_humano


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

    def test_lectura_humana_traduce_xv_todo_nada_en_las_dos_areas_fabrica(self):
        cache_anterior = app_tags._AREAS_CATALOGO_CACHE
        app_tags._AREAS_CATALOGO_CACHE = {
            "500": "Evaporacion",
            "700": "Centrifugado / Purga",
        }
        try:
            self.assertEqual(
                traducir_tag_humano("500_LXV_008", DICCIONARIOS),
                "Válvula Todo/Nada de Nivel, lazo 008, área 500 (Evaporacion)",
            )
            self.assertEqual(
                traducir_tag_humano("700_PXV_008", DICCIONARIOS),
                "Válvula Todo/Nada de Presión, lazo 008, área 700 (Centrifugado / Purga)",
            )
        finally:
            app_tags._AREAS_CATALOGO_CACHE = cache_anterior

    def test_detalle_muestra_procedencia_desde_comentarios_o_guion(self):
        area_key = next(key for key, row in self.app.areas.items() if row["codigo"] == "200")
        variable_key = next(key for key, row in self.app.variables.items() if row["letra"] == "L")
        funcion_key = next(key for key, row in self.app.funciones.items() if row["letra"] == "T")
        area, variable, funcion = self.app.areas[area_key], self.app.variables[variable_key], self.app.funciones[funcion_key]
        db.crear_tag(
            tag_completo="200_LT_099", area_id=area["id"], variable_id=variable["id"], funcion_id=funcion["id"],
            numero_loop=99, descripcion="Prueba", comentarios="Migrado de: EVAP_S13_LCV_ENT_JG_A_CAJA_1", creado_por="prueba",
        )
        self.app.mostrar_detalle_tag("200_LT_099")
        self.assertEqual(self.app.detalle_vars["comentarios"].get(), "Migrado de: EVAP_S13_LCV_ENT_JG_A_CAJA_1")

    def _crear_tag_con_plc(self, tag, plc, descripcion="Prueba", tipo_senal="Analógico", entrada_salida="Entrada"):
        area_key = next(key for key, row in self.app.areas.items() if row["codigo"] == "200")
        variable_key = next(key for key, row in self.app.variables.items() if row["letra"] == "L")
        funcion_key = next(key for key, row in self.app.funciones.items() if row["letra"] == "T")
        area, variable, funcion = self.app.areas[area_key], self.app.variables[variable_key], self.app.funciones[funcion_key]
        db.crear_tag(
            tag_completo=tag, area_id=area["id"], variable_id=variable["id"], funcion_id=funcion["id"],
            numero_loop=int(tag.rsplit("_", 1)[1]), descripcion=descripcion, creado_por="prueba",
            tipo_senal=tipo_senal, entrada_salida=entrada_salida, fluido_proceso="Vino",
        )
        # plc_origen no se carga desde el formulario: se fija aquí, sobre la base temporal del test.
        conexion = db.get_connection()
        conexion.execute("UPDATE tags SET plc_origen = ? WHERE tag_completo = ?", (plc, tag))
        conexion.commit()
        conexion.close()

    def test_busqueda_expandida_tiene_columna_plc_despues_de_estado(self):
        columnas = list(self.app.tree_tags["columns"])
        self.assertEqual(columnas[1], "estado")
        self.assertEqual(columnas[2], "plc", "la columna PLC debe ir inmediatamente después de Estado")
        self.assertEqual(self.app.tree_tags.heading("plc")["text"], "PLC")
        ancho = int(self.app.tree_tags.column("plc")["width"])
        self.assertLessEqual(ancho, 100, "la columna PLC solo muestra dos octetos: debe ser angosta")

    def test_cada_fila_tiene_una_celda_por_columna_y_la_plc_va_alineada(self):
        """Regresión: con una celda de menos, toda la fila se corre y la descripción queda vacía."""
        self._crear_tag_con_plc("200_LT_101", "FABRICA")
        self._crear_tag_con_plc("200_LT_102", None, descripcion="Sin PLC de origen")
        self._crear_tag_con_plc("200_LT_103", "PLC_RARO_SIN_INVENTARIO")
        self.app._indice_busqueda_expandida = None
        self.app._refrescar_grilla_general("")

        columnas = self.app.tree_tags["columns"]
        fila = self.app.tree_tags.item("200_LT_101")["values"]
        self.assertEqual(len(fila), len(columnas), "cada fila necesita tantas celdas como columnas")
        self.assertEqual(fila[0], "200_LT_101")
        self.assertEqual(fila[1], "Planificado")
        self.assertEqual(fila[2], "10.118 / 10.119", "FABRICA tiene dos controladores en el inventario")
        self.assertEqual(fila[3], "Analógico")
        self.assertEqual(fila[4], "Entrada")
        self.assertEqual(fila[5], "Vino")
        self.assertEqual(fila[7], "Prueba", "la última columna no puede quedar vacía")

        self.assertEqual(self.app.tree_tags.item("200_LT_102")["values"][2], "—", "sin PLC de origen: raya")
        self.assertEqual(self.app.tree_tags.item("200_LT_103")["values"][2], "PLC_RARO_SIN",
                         "sin IP verificable se muestra el nombre corto del PLC")

    def test_refrescar_paso5_conserva_la_alineacion(self):
        self._crear_tag_con_plc("200_LT_104", "DESTILERIA")
        self.app.refrescar_paso5()
        fila = self.app.tree_tags.item("200_LT_104")["values"]
        self.assertEqual(len(fila), len(self.app.tree_tags["columns"]))
        self.assertEqual(fila[2], "10.128")
        self.assertEqual(fila[7], "Prueba")

    def test_plc_para_tabla_resuelve_y_cae_a_nombre_corto(self):
        self.assertEqual(plc_para_tabla("Calderas_8_9_10_Desaireador"), "10.195 / 10.196")
        self.assertEqual(plc_para_tabla("DESTILERIA"), "10.128")
        self.assertEqual(plc_para_tabla("DIBACCO"), "10.170")
        self.assertEqual(plc_para_tabla(""), "—")
        self.assertEqual(plc_para_tabla(None), "—")
        self.assertEqual(plc_para_tabla("PLC_INEXISTENTE_LARGO"), "PLC_INEXISTE")

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
