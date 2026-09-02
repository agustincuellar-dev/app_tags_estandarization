# Resumen Ejecutivo de Avance
## Proyecto de Estandarización de Instrumentación y Control — Ingenio La Florida

**Fecha:** 18 de agosto de 2026
**Informe anterior:** `Resumen_Ejecutivo_Avance_070826` (07/08/2026)

---

## 1. Resumen del período

Período de casi dos semanas centrado en cerrar el ciclo completo del código "fresco" identificado el 07/08: filtrarlo, esperar su exportación manual a `.L5X`, integrarlo como canónico validado, atacar el dialecto luso-español que mantenía a DIBACCO con la efectividad más baja de la planta, y finalmente consolidar todo en un dashboard único de estado real. Cinco frentes:

1. Filtro estratégico de código fresco (Jul/Ago 2026) vs. cuarentena histórica.
2. Integración de 6 canónicos reemplazados por versiones más completas, validadas tag-a-tag.
3. Confirmación de que `FABRICA` y `DESFIBRADOR_LA_FLORIDA` siguen bloqueados (versión de Studio 5000).
4. Incorporación del dialecto luso-español al motor ISA — salto de efectividad en DIBACCO.
5. Dashboard final de planta: métricas consolidadas y carpeta de producción.

---

## 2. Filtro de código fresco vs. cuarentena

Nuevo módulo **`src/filtrar_acd_para_convertir.py`**, a pedido explícito del Ingenio tras revisar `ANALISIS_mas_recientes.csv` y notar que varias familias tenían su archivo "más reciente" fechado en 2023-2025 — código que no debía taguearse bajo ISA sin verificar primero contra la planta viva.

Regla aplicada: se copia a `ACD_Para_Convertir/` **solo** el archivo individual (no la familia completa) cuya fecha caiga entre el 01/07/2026 y hoy; las familias sin ningún archivo en esa ventana quedan en cuarentena, listadas en `REQUIEREN_VALIDACION_YANCO.csv` sin copiarse.

**Resultado:** 168 archivos frescos copiados (17 familias), 31 familias en cuarentena documentadas con su antigüedad aproximada y ruta de origen — entre ellas, notablemente, `CENTRIFUGA_1RA_DISCRETO`/`ETHERNET` y `CALD11_PLC` (mayo 2026, quedaron fuera de la ventana por semanas, no años).

---

## 3. Integración de canónicos — 6 reemplazos validados

El usuario exportó manualmente a `.L5X` la mayoría de los `.ACD` filtrados (carpeta `ACD_Para_Convertir - hechos`), incluyendo varios de la lista de cuarentena.

**Hallazgo clave:** se analizó cada `.L5X` entregado por su `Controller Name` real (no por el nombre de carpeta/archivo, que puede ser engañoso). Ningún archivo de cuarentena resultó ser código genuinamente ajeno — los 5 que se lograron exportar (`CALD11_PLC`, `CALD_11`, `CALD_8_9_10_DES_PLC`, `CENTRIFUGA_1RA_DISCRETO`, `CENTRIFUGA_1RA_ETHERNET`) eran, todos, exports alternativos de PLCs ya canónicos. El más significativo: `CENTRIFUGA_1RA_ETHERNET.ACD` resultó ser internamente `CENTRIFUGA_DE_PRIMERA`, con 21 tags más que la versión vigente.

Se reemplazaron 6 canónicos, cada uno **verificado tag-a-tag** (no solo por fecha) antes de aceptarlo como superset real:

<table>
<colgroup><col style="width:26%"><col style="width:14%"><col style="width:14%"><col style="width:46%"></colgroup>
<thead><tr><th>PLC</th><th>Tags antes</th><th>Tags ahora</th><th>Tags perdidos en el cambio</th></tr></thead>
<tbody>
<tr><td>DIBACCO</td><td>563</td><td>577</td><td>0</td></tr>
<tr><td>CALD_LA_FLORIDA</td><td>1.673</td><td>1.736</td><td>0</td></tr>
<tr><td>Calderas_8_9_10_Desaireador</td><td>1.165</td><td>1.254</td><td>1 (<code>C9_DAMPER_VTI</code> — ya confirmado obsoleto por Yanco el 07/08; doble validación)</td></tr>
<tr><td>TRAPICHE2022</td><td>1.973</td><td>2.147</td><td>0</td></tr>
<tr><td>USINA_LA_FLORIDA</td><td>917</td><td>923</td><td>0</td></tr>
<tr><td>CENTRIFUGA_DE_PRIMERA</td><td>1.806</td><td>1.827</td><td>0</td></tr>
</tbody>
</table>

Los 6 canónicos anteriores quedaron archivados en `data_historica/backup_canonicos_reemplazados_130826/`, con `LEEME` explicando cada caso. Se re-corrió el pipeline completo (auditoría ISA + cruce Yanco + escaneo de lógica) sobre los 10 canónicos.

---

## 4. Pendiente sin resolver: FABRICA y DESFIBRADOR_LA_FLORIDA

`FABRICA` (nunca tuvo un `.L5X` en toda su historia relevada) y las 3 variantes de `DESFIBRADOR_LA_FLORIDA` siguen bloqueadas — el usuario las aisló a propósito en una subcarpeta `version mas nueva` porque su exportación requiere una versión de Studio 5000 más nueva que la disponible. Siguen en `.ACD` exclusivamente; no se pudieron auditar en este período.

---

## 5. Dialecto luso-español de DIBACCO — nuevas reglas en el motor

DIBACCO tenía la efectividad ISA más baja de toda la planta (28,1%) por un dialecto de nomenclatura de su integrador (mezcla portugués/español, ya documentado en informes previos). Se extrajeron 15 ejemplos reales de tags pendientes con su UDT (tipo de dato) para analizar el patrón, y se incorporaron 4 reglas nuevas al motor (`auditar_l5x.py`, nuevo "Criterio 2c" en `clasificar()`, activo solo cuando el nombre del tag no aportó ya una función ISA más específica):

| UDT (datatype) | Regla aplicada | Justificación |
|---|---|---|
| `EA_VARIAVEIS`, `IN_ANALOGICO` | → Entrada Analógica (`AI`) | Dialecto PT: "Entrada Analógica" |
| `PID`, `PIDs`, `UD_PIDS` | → Controlador (`C`), familia unificada | 3 variantes del mismo rol, distinto nombre según versión del programa |
| `VALVULA_SENSOR` | → Válvula de Control (`V`) | Actuador con loop ISA propio |
| `MOTOR`, `motores` | → `INTERNA` (convención corporativa) | Un motor es equipo, no un instrumento con lazo ISA — consistente con la UDT `Motor_AC` que el motor ya usa en otra parte del sistema |

**Resultado en DIBACCO:**

| Métrica | Antes | Ahora |
|---|---|---|
| Pendientes | 407 | 280 (−127) |
| Éxito ISA | 159 | 286 |
| **Efectividad ISA** | **28,1%** | **50,53%** |

Casi se duplicó la efectividad de DIBACCO en una sola intervención. Quedan 280 pendientes, el grupo más grande ahora es `datatype=SCP` (46 tags), fuera del alcance de esta tanda.

---

## 6. Dashboard final de planta

Nuevo módulo **`src/generar_dashboard_planta.py`**, que consolida en una sola tabla — por primera vez — tres cosas que hasta ahora vivían en archivos separados: tags declarados en el `.L5X`, cuántos siguen vivos según Yanco, y de esos vivos, cuántos ya están estandarizados bajo ISA-5.1 (excluyendo higiene de sistema del ratio, mismo criterio que la métrica global).

Genera además `L5X_Auditados_Finales/` — copia de producción de los `.L5X` canónicos activamente cruzados contra Yanco (8 de los 10; quedan afuera `DESTILERIA_RECUPERADO` y `vinaza`, congelados desde el 06/08 a la espera de los Excel de Fermentación `.131`/`.132`).

<pre class="tabla-mono">
PLC                             Tags totales   Match de vida   % Match vida   % Efectividad ISA
------------------------------  ------------   -------------   ------------   ------------------
CALD_LA_FLORIDA                        1.736           1.736         100,0%               48,7%
CENTRIFUGA_DE_PRIMERA                  1.827           1.827         100,0%               72,5%
Calderas_8_9_10_Desaireador            1.439           1.435          99,7%               50,4%
DIBACCO                                  582             582         100,0%               50,5%
TRAPICHE2022                           2.492           2.492         100,0%               52,8%
USINA_LA_FLORIDA                         925             925         100,0%               79,0%
cenizas2020                              793             787          99,2%               86,5%
jw2013                                 1.735             980          56,5%               42,9%
------------------------------  ------------   -------------   ------------   ------------------
TOTAL PLANTA (ponderado)              11.529          10.764          93,4%               59,7%
</pre>

El total es un **agregado ponderado** (suma de tags, no promedio simple de los 8 porcentajes) — un PLC de 2.492 tags no puede pesar lo mismo que uno de 582 en el número que representa a toda la planta.

---

## 7. Estado actual y próximos pasos

**Situación:** 10 PLCs canónicos, 6 de ellos recién actualizados a su versión más completa y validada; DIBACCO con su dialecto resuelto; dashboard consolidado operativo; 93,4% de los tags auditados confirmados vivos en la planta real.

**Prioridades sugeridas:**

1. Resolver la actualización de Studio 5000 para poder exportar `FABRICA` y `DESFIBRADOR_LA_FLORIDA` — siguen siendo los huecos más grandes sin auditar.
2. Conseguir los Excel de Yanco de `.131`/`.132` (Fermentación) para descongelar `DESTILERIA_RECUPERADO` y `vinaza`.
3. Atacar el siguiente grupo de pendientes en DIBACCO (`datatype=SCP`, 46 tags).
4. Sigue pendiente desde informes anteriores: resolver los 1.136 conflictos de numeración entre PLCs.
5. Extraer el dialecto de `jw2013` (56,5% de match de vida, pero solo 42,9% de efectividad ISA sobre lo vivo — segundo peor de la planta).

---

## 8. Nota metodológica

Las tres métricas del dashboard final miden cosas distintas y no deben promediarse entre sí sin cuidado: "Tags totales" viene exclusivamente del `.L5X` (fuente única para nombrar/clasificar); "% Match Vida" viene exclusivamente de los Excel de Yanco relevados en vivo (nunca generan tags, solo validan); "% Efectividad Normativa" combina ambas fuentes pero excluye deliberadamente la higiene de sistema, que está fuera del alcance de la norma ISA por diseño del motor.
