# Registro de decisiones de usuario — áreas ISA-5.1

## 23/09/2026 — Mieles

> Mieles (TK_MIEL*, *MIEL_CENT*, *MIEL_RICA*, canales FLEX5000_MIELES) = área 700, decisión de usuario 23/09

La asignación es decisión explícita del usuario. Se registra como criterio de área por identidad/prefijo y no como autorización de numeración, alta o escritura en SQLite. Los lazos o casos cuya evidencia de entrada, salida o pertenencia al proceso siga incompleta permanecen pendientes; esta decisión no resuelve por sí sola `CONTROL_CAUDAL_JUGO_DEST` ni los otros casos expresamente puestos en espera.

Implementación: el override queda limitado a `FABRICA` en `src/auditar_l5x.py` (`MIEL`/`MIELES` → 700) y la regla por identidad explícita en `src/generar_propuesta_masiva.py` cubre `TK_MIEL*`, `*MIEL_CENT*`, `*MIEL_RICA*` y `FLEX5000_MIELES`. No se aplica a otros PLC. `SULFO_ENCALADO`, `COC_LC_MELADO_T`, `CONTROL_PRESION_BIO` y `CONTROL_CAUDAL_JUGO_DEST` tienen bloqueo explícito: sin área y sin número hasta nueva evidencia/decisión.
