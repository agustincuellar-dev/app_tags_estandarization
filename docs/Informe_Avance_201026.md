# Informe de avance — 20 de octubre de 2026

| Proyecto | Catálogo ISA-5.1 — Ingenio La Florida |
|---|---|
| Alcance | Empaquetado del ejecutable para el taller, identidad visual nueva y documentación de traspaso |
| Base de trabajo | `app_etiquetas/tags_ingenio.db` — 381 tags, 182 lazos |
| Responsable | Hermes (asistente técnico) |

## 1. Resumen del día

El trabajo de hoy cerró el tramo de puesta a punto de la herramienta: dejarla ejecutable en una PC sin Python, con la identidad visual nueva y con documentación suficiente para que otro pueda retomarla.

| Entregable | Estado |
|---|---|
| Ejecutable portable `App Tags.exe` con la base externa | Terminado y probado |
| Logo nuevo en el ejecutable, la ventana y el encabezado | Terminado y verificado |
| Documento de contexto completo del proyecto | Terminado |
| Verificación funcional: 21 pruebas y 3 escenarios del ejecutable | Todo en verde |

## 2. Empaquetado del ejecutable

Existía un `Catalogo_LaFlorida.exe` del 1 de octubre, compilado antes de los cambios de interfaz del 7 de octubre (botón SIGUIENTE destacado y selector de PLC). Ese binario no representaba el código actual, así que se recompiló desde cero con PyInstaller 6.21 sobre Python 3.13.

### 2.1 Decisiones de empaquetado

| Decisión | Motivo |
|---|---|
| `--onefile` y `--noconsole` | Un solo archivo, sin ventana negra de consola |
| `--collect-data ttkbootstrap` | Sin la fuente `bootstrap.ttf` la aplicación muere al arrancar |
| `--add-data` con punto como destino | En el ejecutable, `__file__` apunta a la carpeta temporal: los recursos tienen que quedar en su raíz |
| Runtime hook que fija la ruta de la base | La base no se empaqueta: se resuelve desde la carpeta del ejecutable |
| `--icon app_tags.ico` | Icono multi-tamaño, generado desde el logo nuevo |

El hook busca `tags_ingenio.db` en dos disposiciones válidas: la carpeta `app_etiquetas` junto al ejecutable, o el archivo suelto al lado del `.exe`. Si no la encuentra, muestra un aviso y termina. La decisión deliberada es no crear una base vacía: un catálogo fantasma en el taller sería peor que un error visible.

### 2.2 Verificación del binario

| Escenario | Resultado |
|---|---|
| Ejecutable junto a una copia de `app_etiquetas` | Abre la interfaz y lee los 381 tags |
| Base ausente | Avisa qué rutas buscó y no crea ninguna base |
| Ejecutable en el Escritorio | Usa la base real del proyecto y no genera copias |
| Contenido del paquete | La base SQLite no está incrustada en el `.exe` |

Tamaño final: 72.379.526 bytes (69,0 MiB), coherente con un empaquetado que incluye Tk, ttkbootstrap, pandas, openpyxl y Pillow.

## 3. Nombre y ubicación

A pedido, el ejecutable pasó de llamarse `Catalogo_LaFlorida` a `App Tags.exe` y quedó en el Escritorio.

El punto delicado fue la persistencia. Copiar la base al Escritorio habría creado un segundo catálogo que se desincroniza del que se mantiene en el proyecto, justo lo contrario de lo que se buscó durante toda la estandarización. La solución fue dejar en el Escritorio el binario real y una unión de directorios `app_etiquetas` (`mklink /J`) que apunta a la carpeta del proyecto. Verificado: la base que ve el ejecutable del Escritorio es el mismo archivo que la del proyecto, con igual inodo y igual hash, y al abrirlo no aparece ninguna base nueva en el Escritorio.

Para el taller hay que copiar el ejecutable junto con la carpeta `app_etiquetas` real, porque la unión no viaja. Al no estar firmado, Windows puede mostrar SmartScreen la primera vez.

## 4. Logo nuevo

El master recibido, `logoo nuevo.png`, es un render de 1264 × 1264 con fondo claro y sombra proyectada. Para usarlo como icono había que quitarle ese fondo: el primer intento dejó un halo gris visible sobre fondos oscuros.

### 4.1 Procedimiento aplicado

1. Detección del cuerpo del badge por color (azul profundo): 991 px de lado.
2. Medición del radio de las esquinas sobre el original: 213 px, un 21,5 % del lado.
3. Máscara de cuadrado redondeado con ese radio, dibujada a 4× y reducida para suavizar el borde.
4. Exportación de los tres recursos que usa la aplicación.

| Archivo | Formato | Uso |
|---|---|---|
| `logo_app_tags.png` | 512 × 512 transparente, 73.383 B | Master del encabezado; la app lo reduce a 60 × 60 |
| `logo_app_tags.ico` | 16 a 256 px, siete tamaños, 64.196 B | Icono de la ventana y de la barra de tareas |
| `app_tags.ico` | Los mismos siete tamaños, 64.196 B | Icono del ejecutable |

Los siete tamaños del `.ico` se revisaron uno por uno: todos muestran el badge nuevo y las esquinas transparentes.

### 4.2 Dónde quedó aplicado

En el ejecutable, que se recompiló y se reemplazó en el Escritorio. En la ventana, como icono de la barra de título y de la barra de tareas. Y en el encabezado de la aplicación, donde el badge reemplazó a las dos variantes anteriores: el icono chico que precedía al logo corporativo y el esquema ISA que acompañaba al texto, que eran la misma identidad repetida. Queda un solo conjunto: logo corporativo de Los Balcanes, separador, badge nuevo y el nombre de la aplicación con su bajada. El logo corporativo no se modificó.

Después de recompilar, el Escritorio seguía mostrando el icono anterior. No era el binario sino la caché de iconos de Windows, que indexa por ruta de archivo; se refrescó con `ie4uinit -show` y apareció el icono nuevo.

## 5. Documento de contexto del proyecto

Se escribió `docs/CONTEXTO_PROYECTO.md`: 534 líneas, 4.654 palabras, 19 secciones y 16 tablas, pensado como traspaso para alguien que retome el trabajo sin acceso a las sesiones anteriores. Cubre qué hace la aplicación y cómo se guarda un tag, el modelo de datos completo con la semántica de cada columna, el estado del catálogo por área, variable y PLC, la historia de 196 a 478 y de ahí a 381 tags, las reglas de numeración ISA, los ocho canales de revisión, el procedimiento de empaquetado con el hook completo, doce trampas conocidas del entorno y los pendientes. Las 46 rutas citadas se verificaron contra el disco: todas existen.

## 6. Verificación

| Conjunto de pruebas | Pruebas | Resultado |
|---|---|---|
| Interfaz completa (`test_app_tags_ui.py`) | 11 | OK |
| Selector de PLC y botón SIGUIENTE (`test_plc_selector_paso2.py`) | 5 | OK |
| Navegación entre vistas | 3 | OK |
| Limpieza del formulario | 2 | OK |
| Total | 21 | OK |

| Indicador de la base | Valor |
|---|---|
| Tags | 381 |
| Lazos distintos | 182 |
| Filas de auditoría | 4.055 |
| Registros con `plc_origen` vacío | 0 |
| Integridad SQLite | ok |

## 7. Observaciones técnicas

El hash de la base cambia al abrir la aplicación, aunque los datos no cambien: el arranque vuelve a ejecutar los `INSERT OR IGNORE` del catálogo ISA, lo que avanza el contador `sqlite_sequence` y reescribe páginas del archivo. Comparando tabla por tabla, el contenido queda idéntico; conviene no usar el hash como prueba de integridad sin comparar contenido.

El export a Excel dentro del ejecutable arma la carpeta `exports` a partir de `__file__`, que en el `.exe` es la carpeta temporal, así que el archivo puede perderse al cerrar. Si el taller va a exportar, hay que redirigir esa ruta a la carpeta del ejecutable o a Documentos.

El título de la ventana dice "Tags App - Gestión de Tags ISA-5.1". Si se quiere que diga "App Tags", es un cambio de una línea más recompilación. El archivo `logo_header.png`, con el esquema ISA anterior, quedó en disco pero ya no se usa.

## 8. Pendientes

| # | Pendiente |
|---|---|
| 1 | Commitear los cambios de hoy: código, iconos, logo nuevo, documento de contexto y capturas |
| 2 | Decidir si se incorpora `tests` al repositorio: hoy está fuera de git |
| 3 | Definir los cuatro canales de PLC que siguen sin confirmar: canales 1, 5, 6 y 7 de la guía |
| 4 | Confirmar si `CALD_LA_FLORIDA` y `Calderas_8_9_10_Desaireador` son el mismo controlador |
| 5 | Resolver el acceso directo viejo del Escritorio, que todavía apunta al archivo `.py` |

## 9. Artefactos generados

| Archivo | Contenido |
|---|---|
| `Desktop\App Tags.exe` | Ejecutable portable, 69,0 MiB |
| `app_etiquetas\logo_app_tags.png` | Logo master de 512 px, transparente |
| `app_etiquetas\logo_app_tags.ico` | Icono de ventana, siete tamaños |
| `app_etiquetas\app_tags.ico` | Icono del ejecutable, siete tamaños |
| `docs\CONTEXTO_PROYECTO.md` | Documento de contexto completo del proyecto |
| `docs\capturas\` | Cinco capturas: encabezado, Paso 1 en ambos estados, Paso 2 y Escritorio |
