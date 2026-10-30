# Informe de avance — 30 de octubre de 2026

| Proyecto | Monitor de VTI/VTF — Calderas (catálogo ISA-5.1, Ingenio La Florida) |
|---|---|
| Período | Desde el informe del 29/10/2026 |
| Ejes del período | El monitor como ejecutable, logo propio, arranque automático, identidad de la aplicación |
| Estado | Corriendo y registrando: 905 barridos. 16.290 filas |

## 1. Resumen del período

| Entregable | Estado |
|---|---|
| Monitor empaquetado como ejecutable único, con icono propio | Terminado y en uso |
| Logo nuevo del monitor aplicado en todos los lugares | Terminado |
| Corrección del icono duplicado en la barra de tareas | Resuelto |
| Arranque automático al iniciar sesión | Configurado |
| Prueba de corte de energía sin pérdida de datos | Verificada |
| Trazabilidad de corridas y huecos de monitoreo | Implementada |

## 2. El monitor como ejecutable

Se empaquetó con PyInstaller como un único archivo de 37,2 MB, sin ventana de consola. Queda en la raíz del proyecto, al lado de la carpeta `datos`, para que siga escribiendo sobre la misma base y no se pierda la continuidad de lo ya registrado.

| Dato | Valor |
|---|---|
| Archivo | `Monitor VTI-VTF.exe` |
| Tamaño | 37.190.310 bytes |
| SHA-256 | `a91d5b80611fc2291d7a5b3a8e95ab3a1e3283b0783fff709bbee073f1879f07` |
| Modo | archivo único, sin consola, con icono propio |

En el mismo trabajo se agregaron cuatro comportamientos que el programa necesitaba para funcionar como herramienta de escritorio y no como script:

1. **Arranca el barrido solo** al abrirse. Antes había que apretar Iniciar en cada arranque, y si nadie lo apretaba no se registraba nada.
2. **Instancia única.** Si ya hay una ventana abierta, la segunda avisa y se cierra en lugar de duplicar cada barrido en la misma base.
3. **Modo minimizado** (`--minimizado`): abre la ventana, empieza a guardar y se guarda en la barra de tareas, sin quedar en medio de la pantalla.
4. **Registro de diagnóstico.** Cada arranque deja una línea en `datos/monitor_arranque.log` con la identidad de la aplicación, y si el programa falla al iniciar, el error queda escrito en `datos/monitor_error.log` en lugar de desaparecer sin dejar rastro.

## 3. Qué pasa si se corta la luz o se apaga la PC

Se probó con un corte seco del proceso, sin cierre ordenado: se lo mató a la fuerza mientras escribía y después se abrió la base.

| Momento | Filas | Barridos | Integridad |
|---|---|---|---|
| Proceso en marcha | 144 | 4 | ok |
| Después del corte seco | 144 | 4 | ok |
| Después de relanzarlo | 198 | — | ok |

No se perdió ningún barrido. Cada barrido se confirma en disco al terminar de escribirse y la base trabaja en modo WAL, así que lo único que puede perderse es el barrido que se estaba escribiendo en ese instante: segundos, nunca el acumulado. Al relanzar, el programa sigue escribiendo sobre el mismo archivo.

## 4. Trazabilidad de las corridas

Cada lectura guarda ahora a qué corrida pertenece, y al arrancar se cierran las corridas que quedaron abiertas por un apagón, con la hora del último barrido que alcanzaron a guardar.

| Corrida | Inicio | Fin | Barridos |
|---|---|---|---|
| 1, 3 y 4 | pruebas de puesta en marcha | — | 1, 1 y 2 |
| 2 | 29/10 10:25:29 | 29/10 14:34:28 | 499 |
| 5 | 30/10 08:18:52 | 30/10 08:29:22 | 22 |
| 6 | 30/10 08:30:24 | 30/10 09:40:54 | 142 |
| 7 | 30/10 09:42:45 | 30/10 11:26:45 | 209 |
| 8 y 9 | 30/10 11:28 y 11:30 | mismas horas | 3 y 3 |
| 10 | 30/10 11:32:58 | en curso | 22 |

La corrida 2 terminó a las **14:34:28 del 29/10**: ahí se apagó la PC. Entre esa hora y las 08:16 del 30/10 no hay datos, y eso no es una falla del programa sino tiempo que no se monitoreó porque el equipo estaba apagado. El registro ahora lo muestra en vez de disimularlo.

## 5. Logo nuevo

El monitor tiene identidad propia: sobre el cuadrado azul marino lleva un anillo verde con traza de pulso, para distinguirse del logo de App Tags (que lleva el chevrón ámbar).

Se aplicó en los cuatro lugares donde aparece:

| Lugar | Cómo |
|---|---|
| Ejecutable | Icono embebido con siete tamaños, de 16 a 256 px |
| Ventana | Icono de la barra de título e imagen del encabezado |
| Barra de tareas | El icono de la ventana abierta |
| Accesos directos | Escritorio, Menú Inicio y carpeta de Inicio |

## 6. El icono duplicado en la barra de tareas

Al abrir el programa aparecían dos iconos iguales: uno por la ventana abierta y otro por el acceso anclado.

**Causa.** El ejecutable de archivo único no corre desde su ruta original: se descomprime en una carpeta temporal y se ejecuta desde ahí. Windows identifica cada ventana por su ruta, así que veía dos programas distintos. A eso se sumaba que el anclaje se había hecho copiando el acceso directo a la carpeta de anclados, un método que guarda la identidad por ruta y no se fusiona nunca con la ventana.

**Solución.** Se le dio al programa una identidad fija de aplicación (`LaFlorida.MonitorVTI.Calderas`), verificada en el registro de arranque, y la misma identidad a los tres accesos directos, verificada leyendo la propiedad de cada uno. Se eliminó el anclaje duplicado y el programa pasó a arrancar con Windows minimizado, de modo que su icono está en la barra desde que se inicia la sesión.

**Resultado:** un solo icono, con el logo nuevo. Al hacer clic se abre la ventana; si se cierra, el monitoreo se detiene hasta el próximo inicio de sesión.

Queda un detalle para tener en cuenta: si en el futuro se ancla el programa a mano, desde el menú del icono, ahora sí va a fusionarse correctamente y no va a volver a duplicarse. Lo que no funciona es el anclaje por copia de archivo.

## 7. Arranque automático

El programa se inicia con la sesión desde la carpeta de Inicio de Windows, con la opción de arrancar minimizado. Se intentó primero por el Programador de tareas, que es más robusto, pero el registro exige permisos de administrador y el sistema los denegó.

Para desactivarlo alcanza con borrar el acceso directo de `Inicio` del menú de programas.

## 8. Estado del monitoreo

| Indicador | Valor |
|---|---|
| Señales leídas por barrido | 18 (8 de RPM, 8 de corriente, 2 RTD) |
| Intervalo | 30 segundos |
| Barridos registrados | 905 |
| Filas en la base | 16.290 |
| Desde | 29/10/2026 10:02:26 |
| Hasta | 30/10/2026 11:43:58 |
| Pruebas del módulo | 9 de 9 en verde |

Las tres señales cuyo bloque de escalado no tiene entrada cableada siguen marcadas como `SIN_CABLEAR`, y las dos RTD de rodamientos siguen entregando 0,00 °C. Son las mismas anomalías documentadas en el informe anterior: el problema es de campo, no del programa.

## 9. Pendientes

| # | Pendiente |
|---|---|
| 1 | Verificar en campo los 5 canales RTD compartidos y tagear los que correspondan |
| 2 | Revisar los 9 bloques de escalado sin entrada cableada |
| 3 | Revisar los sensores RTD saturados o en cero |
| 4 | Decidir si se tagean las RPM y corrientes del VTI, hoy fuera del alcance de proceso |
| 5 | Si se quiere el arranque por el Programador de tareas en lugar de la carpeta de Inicio, hace falta una sesión con permisos de administrador |
