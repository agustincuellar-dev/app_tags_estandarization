# GUÍA — 8 canales a revisar con los compañeros de planta

**Fecha:** 29/09/2026 · **Base de tags:** `app_etiquetas/tags_ingenio.db`, 478 tags (SHA-256 `601519b9c76d1d789b50d77df613fe642c92531f1cbf7c9259c618fb61c6f92b`)
**Proyectos en esta carpeta:** `1_TRAPICHE2022.ACD`, `2_DESTILERIA.ACD`, `3_Calderas_8_9_10_Desaireador.ACD`

Cómo usarla: abrí el `.ACD` del PLC indicado en Studio 5000, andá al programa/rutina y a la hoja FBD que dice cada fila, y mirá el bloque que consume el canal. Para cada canal hay **dos identidades contradictorias sobre el mismo canal físico** (el alias declarado en el controlador y lo que realmente procesa/escribe el bloque del programa). Con la respuesta se define la identidad real y el canal pasa a ser un tag nuevo.

---

## Tabla de los 8 canales

| # | PLC (Área) | Programa / Rutina FBD | Hoja / Bloque | Canal físico (bornera) | Identidad A (alias declarado en el controlador) | Identidad B (lo que procesa / escribe el bloque del programa) | Pregunta concreta para la planta |
|---|---|---|---|---|---|---|---|
| 1 | TRAPICHE2022 (100) | `ESCALADOS` / `CORRIENTE` | Hoja 1 · `SCL_41` (ID 430) | `Local:2:I.Ch5Data` | `Slot_ST_TURBINA_2DO_MOL` (tacómetro turbina 2º molino) | Escribe `IT_BBA_AGUA_INMIBICION_OESTE` con escala 0–1500 | ¿En el slot 2 canal 5 está cableado el **transformador de corriente de la bomba de imbibición Oeste** (`100_IT`) o el **tacómetro de la turbina del 2º molino** (`100_ST`)? |
| 2 | TRAPICHE2022 (100) | `ESCALADOS` / `CAUDAL` | Hoja 1 · `B_FT_VAPOR_DESFIBRADOR` (ID 90, bloque cuadrático) | `Local:3:I.Ch2Data` | `Slot_IT_BBA_MACERACION_3ER` (corriente bomba maceración 3º molino) | Escribe `FT_VAPOR_DESFIBRADOR` (raíz cuadrada ⇒ caudal) | La rutina **CAUDAL** lo usa como **caudalímetro de vapor del desfibrador** (`100_FT`) pero el alias dice **corriente** (`100_IT`): ¿cuál vale? |
| 3 | TRAPICHE2022 (100) | `ESCALADOS` / `CAUDAL` | Hoja 1 · `SCL_14` (ID 81) | `Local:3:I.Ch4Data` | `Slot_IT_BBA_MACERACION_4TO` (corriente bomba maceración 4º molino) | Escribe `FT_AGUA_LAVADO_TAMIS` | Igual que el anterior: ¿**caudalímetro de agua de lavado de tamiz** (`100_FT`) o **corriente** de la bomba de maceración del 4º molino (`100_IT`)? |
| 4 | TRAPICHE2022 (100) | `ESCALADOS` / `TEMPERATURA` | Hoja 1 · `B_TT_MOTOR_ROLO_NORTE_1_MOL` (ID 25) | `Local:9:I.Ch[1].Data` | `Slot_TT_BOBINA_MOTOR_ROLO_NORTE_1_MOL` | Escribe `TT_BOBINA_MOTOR_ROLO_1_MOL` (mismo Pt100, sin la palabra NORTE en el destino) | Son el mismo sensor Pt100, pero **queda fuera del catálogo de proceso**: es temperatura de la bobina del motor (regla del 01/10/2026: BOBINA/MOTOR no son variables de proceso). |
| 5 | DESTILERIA (200) | `JW` / `ESCLADOS_PT_FT_LT_TT` | Hoja 4 · `ALM_TT_ENTRADA_ENF_ALCOHOL` (ID 193, lee el canal crudo, sin escalado) | `jw_fermerntacion_2022:2:I.Ch2Data` | `Slot_ST_CENTRIFUGA_3` (y en `FERMENTACION/ESCALADOS_PT_FT_LT_TT` el bloque `B_ST_CENTRIFUGA_3` escribe `ST_CENTRIFUGA_3`, velocidad) | El bloque que lo lee en `JW` se llama *temperatura de entrada al enfriador de alcohol* | ¿Ese canal mide las **RPM de la Centrífuga 3 de levadura** (`200_ST`) o la **temperatura de entrada al enfriador de alcohol** (`200_TT`)? |
| 6 | DESTILERIA (200) | `JW` / `ESCLADOS_PT_FT_LT_TT` | Hoja 4 · `ALM_TT_ENTRADA_CAL_VINO` (ID 192, lee el canal crudo) | `jw_fermerntacion_2022:2:I.Ch4Data` | `Slot_ST_CENTRIFUGA_5` (y `B_ST_CENTRIFUGA_5` → `ST_CENTRIFUGA_5`) | El bloque que lo lee se llama *temperatura del calentador de vino* | Igual que el 5: ¿**RPM de la Centrífuga 5** (`200_ST`) o **temperatura del calentador de vino** (`200_TT`)? |
| 7 | Calderas_8_9_10_Desaireador (300) | `DES` / `DES_S2_ESCALADO_AI` **y** `DES` / `DES_S3_ESCALADO_AI` | Hoja 1 · `SCL_19` (ID 26) → `TEMP_CCM_DES` escala 0–150 °C **y** Hoja 1 · `SCL_15` (ID 30) → `ST_DES_ARRANQUE_BBA_TK_1000_BACKUP` escala 0–1500 RPM | `Desaireador:3:I.Ch[5].Data` (slot 3 del adaptador Desaireador) | `DES_S3_IT_BBA_4` (corriente) | **Dos bloques vivos a la vez**: uno lo publica como velocidad y otro como temperatura del CCM | ¿Qué instrumento está conectado en `Desaireador:3:I.Ch[5]`: la **corriente de la bomba** (`300_IT`), la **velocidad** (`300_ST`) o la **temperatura del CCM** (`300_TT`)? |
| 8 | Calderas_8_9_10_Desaireador (300) | `DES` (ningún bloque lo lee en todo el programa) | — | `Desaireador:3:I.Ch[1].Data` | `DES_S3_ST_BBA_10` (velocidad bomba 10) | Ninguno: el alias está declarado pero no hay bloque cableado | **Fuera del catálogo de proceso**: es una velocidad de bomba (`_ST_`, variable S). Sólo queda por decidir si la bomba 10 existe: si no existe, hay que borrar el alias del PLC. |

---

## Bonus — 2 salidas ya numeradas, con alias viejo cruzado (verificar en campo)

| Tag | Lazo / PLC | Canal de salida | Alias viejo en el canal | Qué verificar |
|---|---|---|---|---|
| `700_PV_002` | `B_PID_VAL_20_10_AUX_1` · FABRICA (`FAB_CCV/CCV_PC_ALTA_ESCAPE`) | `ISLA_FAB_AI:13:O.Ch[6].Data` | `EVAP_S13_LCD_MELADO_5TO_EFE` | El PID controla **presión 20–10 bar**, pero el alias del canal dice *melado de 5º efecto*. Confirmar qué válvula está cableada en ese canal. |
| `400_PV_004` | `B_PID_VAL_20_10_AUX_2` · FABRICA (`FAB_CCV/CCV_PC_ALTA_ESCAPE`) | `SULFO_ENCALADO:8:O.Ch7Data` | `Slot3_PV_VAL_CTROL_LT_J_ENCALADO` | El PID controla **presión 20–10 bar**, pero el alias apunta a una válvula de **nivel** de jugo encalado. Confirmar el dispositivo real. |

---

## Qué pasa con cada respuesta

- Canales 1, 2, 3, 5, 6, 7 → con la identidad confirmada se crea **1 tag por canal** (el número libre ya está reservado en el plan `exports/plan_maestro_consolidado_v5_homologado_290926.csv`).
- Canal 4 → si confirmás que es el mismo Pt100, se crea **1 solo tag** (`100_TT_nnn`, área 100).
- Canal 8 → si la bomba 10 existe, se reserva un tag `300_ST_nnn` (variable S, área 300; próximo número libre hoy: `300_ST_038`); si no existe, se borra el alias del PLC.

## Origen de los 3 .ACD copiados

| Copia en esta carpeta | Archivo original (ruta relativa al proyecto) | Fecha | Tamaño |
|---|---|---|---|
| `1_TRAPICHE2022.ACD` | `ACD_Para_Convertir/ACD_Para_Convertir ¨- hechos/TRAPICHE2022/TRAPICHE2022.DESKTOP-1LCQM96.PC-STDIO500v33.BAK031.acd` | 2026-07-30 05:40 | 5,10 MB |
| `2_DESTILERIA.ACD` | `ACD_Para_Convertir/ACD_Para_Convertir ¨- hechos/DESTILERIA/DESTILERIA_RECUPERADO.ACD` | 2026-08-05 16:27 | 8,58 MB |
| `3_Calderas_8_9_10_Desaireador.ACD` | `data_historica/proyectos_studio5000/Calderas_8_9_10_Desaireador.ACD` | 2026-07-15 07:41 | 4,81 MB |

Copias verificadas byte a byte (SHA-256 copia == SHA-256 original). Los archivos originales no se movieron: siguen en su ubicación.

Regla de selección: el `.ACD`/`.BAK` más reciente de cada PLC, sin marca de duplicado (`__dup…`) y con tamaño de proyecto completo (≥ 2 MB). Si el equipo prefiere otra versión, las alternativas de cada PLC (con fecha y ruta) están en `archivo_ordenado/inventario_acd_y_exports_290926.json`. Casos a mirar:
- **TRAPICHE2022**: el elegido es el `.BAK031` del 30/07 (5,10 MB) porque es más nuevo que el `TRAPICHE2022.ACD` del 15/07 (`data_historica/proyectos_studio5000/`).
- **DESTILERIA**: el elegido es `DESTILERIA_RECUPERADO.ACD` del 05/08. Alternativa “limpia”: `DESTILERIA.ACD` del 22/07 (9,46 MB, está en `ACD_Para_Convertir/DESTILERIA/`).
- **Calderas**: el L5X de producción es del 18/08, más nuevo que todos los `.ACD` disponibles (el más nuevo es del 15/07).
