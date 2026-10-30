# Búsqueda en los programas de Calderas: RPM, corrientes de VTI/VTF y RTD

**Fecha:** 20/10/2026 · **Fuente:** `L5X_Produccion/Calderas_8_9_10_Desaireador.L5X` (3,9 MB, controlador 1756-L72 rev 33)
**Complemento:** `cenizas2020.L5X` y `CALD_LA_FLORIDA.L5X` revisados con los mismos criterios.

## Método

Se recorrieron los seis programas del controlador (`C8`, `C9`, `C10`, `DES`, `DES_2`, `MainProgram` y `AI_Planta`) resolviendo la hoja FBD: cada bloque de escalado (`SCL`) se siguió por sus cables hasta el canal de entrada y hasta el tag de salida, con sus rangos de ingeniería. Resultado: 89 tags de velocidad, corriente y temperatura trazados, volcados a `exports/calderas_rpm_corriente_rtd_201026.csv`.

Cada caldera tiene dos rutinas de escalado: `Cx_S3_ESCALADO_AI` (señales 4–20 mA) y `Cx_S5_ESCALADO_RTD` (canales RTD).

## 1. Velocidad (RPM) de VTI y VTF

Sí existen. Son 4–20 mA escalados a RPM, no lectura directa del variador.

| Caldera | Tag | Canal | Escala |
|---|---|---|---|
| C8 | `C8_ST_VTF` | `BP_ANALOGICA:4:I.Ch[3]` | 4–20 mA → 0..1485 |
| C8 | `C8_ST_VTI_NORTE` | `BP_ANALOGICA:4:I.Ch[4]` | 4–20 mA → 0..985 |
| C8 | `C8_ST_VTI_SUR` | `BP_ANALOGICA:4:I.Ch[5]` | 4–20 mA → 0..900 |
| C9 | `C9_ST_VTI` | `BP_ANALOGICA:4:I.Ch[7]` | 4–20 mA → 0..990 |
| C9 | `C9_ST_VTF` | sin cablear | 4–20 mA → 0..100 declarado |
| C10 | `C10_ST_VTF` | `BP_ANALOGICA:5:I.Ch[3]` | 4–20 mA → 0..1000 |
| C10 | `C10_ST_VTI_ESTE` | `BP_ANALOGICA:5:I.Ch[6]` | 4–20 mA → 0..800 |
| C10 | `C10_ST_VTI_OESTE` | `BP_ANALOGICA:5:I.Ch[7]` | 4–20 mA → 0..800 |

Otras velocidades del área: `Cx_ST_VENTILADOR_AUXILIAR` (bloque sin entrada en las tres calderas), `Cx_ST_DOSIFICADOR_n` y `Cx_ST_AIRE_ESPARCIDOR` (estos sí leen `:I.OutputRPM` del PowerFlex 525/755), las bombas del desaireador (`DES_ST_BBA_8/9`, 0..1470 y 0..2985) y `ST_DES_ARRANQUE_BBA_TK_1000_BACKUP` (0..1500).

## 2. Corriente de los motores de VTI y VTF

También existen, en amperes.

| Caldera | Tag | Canal | Escala |
|---|---|---|---|
| C8 | `C8_IT_VTI_NORTE` | `BP_ANALOGICA:4:I.Ch[0]` | 4–20 mA → 0..143 A |
| C8 | `C8_IT_VTI_SUR` | sin cablear | 4–20 mA → 0..209 A |
| C8 | `C8_IT_VTF` | sin cablear | 4–20 mA → 0..116 A |
| C9 | `C9_IT_VTI` | `BP_ANALOGICA:4:I.Ch[6]` | 4–20 mA → 0..603 A |
| C9 | `C9_IT_VTF` | `BP_ANALOGICA:5:I.Ch[0]` | 4–20 mA → 0..100 A |
| C10 | `C10_IT_VTI_OESTE` | `BP_ANALOGICA:5:I.Ch[5]` | 4–20 mA → 0..750 A |
| C10 | `C10_IT_VTF` | `BP_ANALOGICA:5:I.Ch[2]` | 4–20 mA → 0..100 A |
| C10 | `C10_IT_VTI_ESTE` | calculado por `MUL_15` | sin rango propio |

Además, en `MainProgram` hay corrientes porcentuales de la caldera 11: `IT_PORCEN_CAL11_VTI_NORTE` y `IT_PORCEN_CAL11_VTI_SUR` (0..100 %).

## 3. RTD en Calderas

Sí hay una parte de RTD, y es propia del chasis analógico: **tres placas 1756-IR12** en `BP_ANALOGICA` slots **7, 8 y 9** (36 canales). Se usan 22, y alimentan las temperaturas de caldera, no solo las de VTI/VTF.

| Caldera | Tag | Canal RTD | Rango |
|---|---|---|---|
| C8 | `C8_TT_VAPOR_DE_ALTA` | `BP_ANALOGICA:8:I.Ch[3]` | −200..650 °C |
| C8 | `C8_TT_BAJO_GRILLA` | `BP_ANALOGICA:7:I.Ch[0]` | −200..650 °C |
| C8 | `C8_TT_SALIDA_CAJA_DE_AIRE` | `BP_ANALOGICA:9:I.Ch[4]` | −200..650 °C |
| C8 | `C8_TT_SALIDA_CALDERA` | `BP_ANALOGICA:9:I.Ch[5]` | −200..650 °C |
| C9 | `C9_TT_SALIDA_ECONOMIZADOR` | `BP_ANALOGICA:8:I.Ch[0]` | −200..650 °C |
| C9 | `C9_TT_CCM` | `BP_ANALOGICA:8:I.Ch[1]` | −200..650 °C |
| C9 | `C9_TT_VAPOR_DE_ALTA` | `BP_ANALOGICA:8:I.Ch[2]` | −200..650 °C |
| C9 | `C9_TT_SALIDA_CALDERA` | `BP_ANALOGICA:8:I.Ch[7]` | −200..650 °C |
| C9 | `C9_TT_ENTRADA_ECONOMIZADOR` | `BP_ANALOGICA:9:I.Ch[6]` | −200..650 °C |
| C9 | `C9_TT_SALIDA_CAJA_DE_AIRE` | `BP_ANALOGICA:9:I.Ch[7]` | −200..650 °C |
| C9 | `C9_TT_ROD_DEL_VTI` | `BP_ANALOGICA:7:I.Ch[8]` | lectura directa, sin escalado |
| C9 | `C9_TT_ROD_TRA_VTI` | `BP_ANALOGICA:7:I.Ch[9]` | lectura directa, sin escalado |
| C10 | `C10_TT_BAJO_GRILLA` | `BP_ANALOGICA:8:I.Ch[4]` | −200..650 °C |
| C10 | `C10_TT_ENTRADA_ECONOMIZADOR` | `BP_ANALOGICA:8:I.Ch[5]` | −200..650 °C |
| C10 | `C10_TT_SALIDA_CAJA_DE_AIRE` | `BP_ANALOGICA:8:I.Ch[6]` | −200..650 °C |
| C10 | `C10_TT_SALIDA_CALDERA` | `BP_ANALOGICA:8:I.Ch[7]` | −200..650 °C |
| C10 | `C10_TT_SALIDA_ECONOMIZADOR` | `BP_ANALOGICA:8:I.Ch[8]` | −200..650 °C |
| C10 | `C10_TT_VAPOR_DE_ALTA` | `BP_ANALOGICA:8:I.Ch[9]` | −200..650 °C |

También salen de las RTD, en la misma rutina, `TT_CHIMENEA_CAL_8`, `TT_CHIMENEA_CAL_10_ESTE`, `TT_CHIMENEA_CAL_10_OESTE` y `TT_CABINA_CAL8910`.

El rango −200..650 °C es el típico de un canal RTD configurado en grados Celsius: es la evidencia de que esos canales son RTD y no 4–20 mA.

## 4. Observaciones a revisar

1. **Nueve bloques de escalado no tienen la entrada cableada**: `C8_IT_VTF`, `C8_IT_VTI_SUR`, `C8_ST_VENTILADOR_AUXILIAR`, `C9_ST_VTF`, `C9_ST_VENTILADOR_AUXILIAR`, `C9_IT_VENTILADOR_AUXILIAR`, `C10_ST_VENTILADOR_AUXILIAR`, `C10_IT_VENTILADOR_AUXILIAR` y `C8_IT_VENTILADOR_AUXILIAR`. En el FBD el pin `In` no recibe ningún cable y el bloque no aparece en ninguna rutina de texto: el tag existe y se muestra en la HMI, pero no está midiendo nada.
2. **Canales RTD compartidos entre dos tags**, señal de copia entre calderas:
   - `BP_ANALOGICA:8:I.Ch[3]` → `C8_TT_VAPOR_DE_ALTA` y también `C9_TT_HOGAR`.
   - `BP_ANALOGICA:8:I.Ch[7]` → `C9_TT_SALIDA_CALDERA` y también `C10_TT_SALIDA_CALDERA`.
   - `BP_ANALOGICA:8:I.Ch[2]` → `C9_TT_VAPOR_DE_ALTA` y su duplicado `C9_TT_VAPOR_DE_ALTA_1`.
   - `BP_ANALOGICA:8:I.Ch[9]` → `C10_TT_VAPOR_DE_ALTA` y su duplicado `C10_TT_VAPOR_DE_ALTA_1`.

   Con un solo cable físico por canal, solo uno de los dos tags puede ser el correcto.
3. **`C10_IT_VTI_ESTE`** no viene de un canal analógico: lo calcula un bloque `MUL_15`. Conviene confirmar qué multiplica antes de usarlo como corriente.
4. **`C10_TT_HOGAR`** no es RTD: sale de `BP_ANALOGICA:3:I.Ch[6]` (4–20 mA escalado 0..1370 °C).
5. En `CALD_LA_FLORIDA` (caldera 11) hay dos corrientes porcentuales de VTI, pero **no** tiene placas RTD: sus temperaturas llegan por 4–20 mA.
6. **Catálogo ISA:** de estas señales, las de RPM y corriente no están en los 381 tags (se excluyeron en la depuración de variables electromecánicas); de las temperaturas, solo una referencia de `C9_TT` aparece en los comentarios del catálogo. Si se quiere que el taller consulte las RPM y las corrientes de VTI/VTF desde la aplicación, hay que decidir su incorporación como tags de máquina.
