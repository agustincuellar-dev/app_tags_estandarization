# Informe de avance — 29 de octubre de 2026

| Proyecto | Catálogo ISA-5.1 — Ingenio La Florida |
|---|---|
| Período | Desde el informe del 20/10/2026 |
| Ejes del período | Búsqueda en los programas de Calderas, monitor de VTI/VTF, alta de las RTD en el catálogo |
| Base de trabajo | `app_etiquetas/tags_ingenio.db` — **395 tags**, 195 lazos |

## 1. Resumen del período

| Entregable | Estado |
|---|---|
| Búsqueda de RPM, corrientes y RTD en los L5X de Calderas | Terminada, con trazado de canal a tag |
| Monitor de VTI/VTF con registro cada 30 s y export CSV/XLSX | Terminado, en marcha y guardando |
| Alta de 14 RTD en el catálogo (381 a 395) | Terminada y auditada |
| Diagnóstico del estado real de los sensores RTD | Terminado: la mayoría no está midiendo |

## 2. Búsqueda en los programas de Calderas

Se trabajó sobre `Calderas_8_9_10_Desaireador.L5X` (4,1 MB, controlador 1756-L72 rev 33, seis programas y 74 rutinas), con `cenizas2020.L5X` y `CALD_LA_FLORIDA.L5X` revisados con el mismo criterio. El método fue recorrer las hojas FBD resolviendo cada bloque de escalado por sus cables: canal de entrada, rango de ingeniería y tag de salida. De los 324 bloques del programa quedaron trazados 89 tags de velocidad, corriente y temperatura, volcados a `exports/calderas_rpm_corriente_rtd_201026.csv`.

**Velocidad (RPM).** Existe y es 4 a 20 mA escalado, no lectura del variador: `C8_ST_VTF` (0..1485), `C8_ST_VTI_NORTE` (0..985), `C8_ST_VTI_SUR` (0..900), `C9_ST_VTI` (0..990), `C10_ST_VTF` (0..1000), `C10_ST_VTI_ESTE` y `OESTE` (0..800). `C9_ST_VTF` existe pero su bloque no tiene entrada cableada.

**Corriente.** También existe, en amperes: `C8_IT_VTI_NORTE` (0..143 A), `C8_IT_VTI_SUR` (0..209 A), `C8_IT_VTF` (0..116 A), `C9_IT_VTI` (0..603 A), `C9_IT_VTF` (0..100 A), `C10_IT_VTI_OESTE` (0..750 A), `C10_IT_VTF` (0..100 A) y `C10_IT_VTI_ESTE`, que no viene de un canal sino de un bloque multiplicador.

**RTD.** Hay una sección propia: tres placas 1756-IR12 en el chasis `BP_ANALOGICA`, slots 7, 8 y 9, con 36 canales y 22 en uso. Cada caldera tiene su rutina de escalado RTD (`C8_S5_ESCALADA_RTD`, `C9_S5_ESCALADO_RTD`, `C10_S5_ESCALADO_RTD`) y alimenta las temperaturas de hogar, economizador, vapor de alta, caja de aire, salida de caldera y chimeneas, además de los dos rodamientos del VTI de la caldera 9.

**Tres anomalías de programación** que quedaron documentadas y que condicionan lo que se puede medir:

1. Nueve bloques de escalado no tienen la entrada cableada: `C8_IT_VTF`, `C8_IT_VTI_SUR`, `C8_ST_VENTILADOR_AUXILIAR`, `C9_ST_VTF`, `C9_ST_VENTILADOR_AUXILIAR`, `C9_IT_VENTILADOR_AUXILIAR`, `C10_ST_VENTILADOR_AUXILIAR`, `C10_IT_VENTILADOR_AUXILIAR` y `C8_IT_VENTILADOR_AUXILIAR`. El tag existe y se ve en la HMI, pero no mide.
2. Tres canales RTD están escalados a dos tags distintos, a veces de calderas diferentes: `8:Ch[3]` alimenta `C8_TT_VAPOR_DE_ALTA` y `C9_TT_HOGAR`; `8:Ch[7]` alimenta `C9_TT_SALIDA_CALDERA` y `C10_TT_SALIDA_CALDERA`; `8:Ch[4]` repite entre C9 y C10 (`C9_TT_BAJO_GRILLA` y `C10_TT_BAJO_GRILLA`). Con un solo cable por canal, uno de los dos tags no puede ser cierto.
3. Los tags `C8_TT_VAPOR_DE_ALTA_1`, `C9_TT_VAPOR_DE_ALTA_1` y `C10_TT_VAPOR_DE_ALTA_1` son copias del mismo canal que el tag sin sufijo.

## 3. Monitor de VTI/VTF

Se construyó una herramienta que lee 18 señales del PLC cada 30 segundos, las guarda en SQLite y permite exportarlas.

| Componente | Archivo |
|---|---|
| Núcleo (lectura CIP, base, export) | `src/monitor_calderas.py` |
| Interfaz | `src/monitor_calderas_gui.py` |
| Arranque manual | `src/Monitor_Calderas.bat` |
| Arranque con barrido automático | `src/Iniciar_Monitor.bat` |
| Pruebas | `tests/test_monitor_calderas.py` (9 pruebas) |

- **Qué lee:** 8 velocidades de VTI y VTF, 8 corrientes y las 2 RTD de rodamientos del VTI de la caldera 9.
- **Cómo guarda:** una fila por señal y por barrido en `datos/monitor_calderas.db`, con fecha, valor, unidad, calidad y error.
- **Cómo exporta:** CSV con separador punto y coma y BOM (abre directo en Excel) y XLSX con hoja *Lecturas* y hoja *Resumen* por señal (mínimo, máximo, promedio y última lectura).

**Verificación:** lectura real contra el controlador con 18 de 18 señales OK, y las 9 pruebas unitarias en verde, incluyendo el caso de pérdida de comunicación (queda registrado como `SIN_COMUNICACION` en lugar de inventar un valor).

**En marcha desde el 29/10 a las 10:25.** Al cierre de este informe lleva **31 barridos y 558 filas**, con un barrido cada 30 segundos exactos. Corre como proceso independiente, así que sigue guardando aunque se cierre la sesión de trabajo.

Para las tres señales cuyo bloque no tiene entrada cableada, el monitor las marca `SIN_CABLEAR` en lugar de mostrar el cero como si fuera una medición.

## 4. Catálogo: de 381 a 395 tags

Se dieron de alta 14 RTD, en dos tandas autorizadas, con el mismo procedimiento en ambas: copia de seguridad previa, una sola transacción, candado de los 11 tags manuales campo a campo, verificación de conteo e integridad dentro de la transacción, y una fila de auditoría por alta.

| Alta | Tags | Lazos |
|---|---|---|
| Rodamientos del VTI, caldera 9 | `300_TT_038A`, `300_TT_038B` | 38 (con sufijos A y B) |
| Calderas 8, 9 y 10 | `300_TT_039`, `040`, `048` a `057` | 39, 40 y 48 a 57 |

El área 300 pasó de 87 a 101 tags y el catálogo de 381 a 395. Cada tag nuevo lleva el canal del PLC en `alias_for`, el rango `-200..650`, unidad en grados Celsius y, en `comentarios`, el tag del programa y la lectura del momento del alta.

Los canales quedaron en el campo `alias_for` de cada tag y el detalle de la búsqueda está en `docs/Busqueda_Calderas_RPM_VTI_VTF_RTD_201026.md`.

## 5. Las lecturas anómalas

Antes de escribir cada tag se leyó el valor real en el PLC. El resultado es el hallazgo más importante del período, y se ve mejor en una sola tabla con qué mide cada instrumento y qué entrega hoy:

| Tag ISA | Caldera | Medición | Lectura al alta | Estado |
|---|---|---|---|---|
| `300_TT_039` | 8 | Bajo grilla | 650,0 °C | saturada |
| `300_TT_040` | 8 | Caja de aire (salida) | 359,5 °C | mide |
| `300_TT_048` | 8 | Gases salida caldera | -200,0 °C | saturada |
| `300_TT_049` | 9 | Agua salida economizador | 650,0 °C | saturada |
| `300_TT_050` | 9 | CCM | 650,0 °C | saturada |
| `300_TT_051` | 9 | Vapor de alta | 308,2 °C | mide |
| `300_TT_052` | 9 | Agua entrada economizador | 110,9 °C | mide |
| `300_TT_053` | 9 | Caja de aire (salida) | 650,0 °C | saturada |
| `300_TT_054` | 10 | Agua entrada economizador | 650,0 °C | saturada |
| `300_TT_055` | 10 | Gases salida caja aire | 650,0 °C | saturada |
| `300_TT_056` | 10 | Agua salida economizador | 650,0 °C | saturada |
| `300_TT_057` | 10 | Vapor de alta | 305,7 °C | mide |
| `300_TT_038A` | 9 | Rodamiento delantero VTI | 0,00 °C | sin señal |
| `300_TT_038B` | 9 | Rodamiento trasero VTI | 0,00 °C | sin señal |

De las doce RTD de las calderas, ocho quedaron en los extremos del rango: siete en 650,0 °C y una en -200,0 °C. Ese patrón no es una temperatura alta o baja real, es la firma de un canal RTD **abierto o sin sensor conectado**: cuando el elemento no está, el módulo se va al límite de escala. Las dos de rodamientos, que se leen directo sin escalado, marcan 0,00 °C, otro modo de falla distinto.

En resumen: de las 24 temperaturas RTD individuales del programa, **19 ya tienen tag en el catálogo**, pero **sólo 4 están midiendo de verdad**. El resto de las señales están rotas o sin instrumento, no mal tageadas.

Esto refuerza la utilidad del monitor: hoy guarda el cero y la saturación tal como los entrega el PLC, así que cuando se repare un sensor va a quedar registrado el momento exacto del cambio.

## 6. Cobertura del catálogo sobre las RTD

| Concepto | Cantidad |
|---|---|
| Temperaturas escritas en las rutinas RTD del PLC | 27 |
| Menos copias del mismo canal (sufijo `_1`) | 3 |
| RTD individuales reales | 24 |
| Con tag en el catálogo | 19 |
| Pendientes de tagear | 5 |

Los 5 pendientes son `C8_TT_VAPOR_DE_ALTA`, `C9_TT_SALIDA_CALDERA`, `C10_TT_BAJO_GRILLA`, `C10_TT_SALIDA_CALDERA` y `TT_CABINA_CAL8910`. No se tagearon porque los cuatro primeros comparten canal físico con otra caldera y el último no tiene canal identificado: antes de crear el tag hay que verificar en el tablero a qué caldera pertenece cada canal. Crearlos a ciegas habría dejado dos instrumentos para un mismo sensor.

## 7. Estado del sistema

| Indicador | Valor |
|---|---|
| Tags en el catálogo | 395 |
| Lazos distintos | 195 |
| Tags del área 300 | 101 |
| Filas de auditoría | 4.069 |
| Integridad SQLite | ok, sin errores de clave foránea |
| SHA-256 de la base | `3cf81076fe941631a72d8c6b36205c0bdd74ff1d48b30042d0f612dd7f1e4eaa` |
| Barridos del monitor | 31 (558 filas) |

Copias de seguridad creadas en el período: `tags_ingenio_381tags_pre_rtd_vti_291026.db` y `tags_ingenio_383tags_pre_rtd_calderas_291026.db`.

## 8. Pendientes

| # | Pendiente |
|---|---|
| 1 | Verificar en campo los 5 canales RTD compartidos y tagear los que correspondan |
| 2 | Revisar los 9 bloques de escalado sin entrada cableada (leen cero permanente) |
| 3 | Revisar los sensores RTD saturados o en cero: 8 saturadas y 2 sin señal |
| 4 | Decidir si se tagean también las RPM y corrientes del VTI (hoy fuera del alcance de proceso) |
| 5 | Commitear el período: base, monitor, pruebas, documento de búsqueda y este informe |
| 6 | Opcional: dejar el monitor con arranque automático al iniciar sesión |

## 9. En síntesis

El catálogo quedó en 395 tags, con toda la sección de temperaturas RTD de Calderas identificada y trazada a su canal físico. El monitor está registrando cada 30 segundos y ya acumula el histórico que va a servir de línea base.

Lo que queda no es trabajo de catálogo sino de campo: los sensores RTD, en su mayoría, no están entregando una medición válida. Los tags ya están puestos, así que el día que se conecte o repare cada uno, el registro va a mostrar el cambio solo.
