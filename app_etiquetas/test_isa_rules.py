import unittest

from isa_rules import (
    funcion_sugerida_por_asistente,
    funciones_permitidas_para_variable,
    validar_funcion_isa,
)


class ReglasAsistenteISATest(unittest.TestCase):
    def test_transmisor_con_display_local_se_convierte_en_indicador_transmisor(self):
        self.assertEqual(funcion_sugerida_por_asistente("T", tiene_display_local=True), "IT")
        self.assertEqual(funcion_sugerida_por_asistente("T", tiene_display_local=False), "T")

    def test_indicador_local_autonomo_con_visor_usa_g(self):
        self.assertEqual(funcion_sugerida_por_asistente("I", es_visor_directo=True), "G")
        self.assertEqual(funcion_sugerida_por_asistente("I", es_visor_directo=False), "I")

    def test_se_rechaza_orden_isa_invalido_de_funcion_pasiva_despues_de_activa(self):
        valido, mensaje = validar_funcion_isa("TI")
        self.assertFalse(valido)
        self.assertIn("antes", mensaje)

    def test_se_acepta_indicacion_antes_de_transmision(self):
        self.assertEqual(validar_funcion_isa("IT"), (True, ""))

    def test_densidad_no_ofrece_control_ni_valvula(self):
        permitidas = funciones_permitidas_para_variable("D", {"T", "IT", "I", "C", "V", "A", "G"})
        self.assertEqual(permitidas, ("A", "G", "I", "IT", "T"))


if __name__ == "__main__":
    unittest.main()
