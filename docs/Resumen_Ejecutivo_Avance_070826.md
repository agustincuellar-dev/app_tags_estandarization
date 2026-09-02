# Resumen Ejecutivo de Avance
## Proyecto de Estandarización de Instrumentación y Control — Ingenio La Florida

**Fecha:** 07 de agosto de 2026
**Informe anterior:** `Resumen_Ejecutivo_Avance_060826` (06/08/2026)

---

## 1. Resumen de la jornada

Jornada corta y focalizada, con un solo frente: analizar el primer resultado real de la herramienta de recolección entregada ayer (`RecolectorFuentesPLC.exe`). El usuario ya la corrió en 4 PCs de ingeniería distintas y fusionó los resultados en una carpeta `dist`. Se hizo el primer filtrado a versiones más recientes pedido explícitamente, se encontraron y corrigieron 2 bugs reales en la herramienta a partir de esa corrida, y se identificaron 4 controladores en edición activa que todavía no tenemos forma de auditar.

---

## 2. La herramienta de recolección ya está en uso real

El log de errores (`errores_extraccion.log`, que sí es acumulativo) confirma **8 corridas** de `RecolectorFuentesPLC.exe` entre el 06 y el 07/08/2026, sobre las unidades `C:\`, `D:\`, `E:\` y `F:\` de al menos 4 PCs distintas (`PC BACK AUTOMATISMO`, `PC-STDIO500v33`, `Administrador`, entre otras). El resultado fusionado en `archivos ACD y L5X auditados\dist\auditoria l5x y ACD\` contiene **2.590 archivos `.ACD`/`.L5X`** repartidos en 921 subcarpetas.

### 2.1 Dos bugs reales detectados y corregidos en `recolector_fuentes_plc.py`

1. **El CSV de trazabilidad se pisaba en cada corrida.** Se abría en modo `"w"` (sobrescribir) en vez de `"a"` (agregar). Resultado: de 2.590 archivos copiados en 8 corridas, el CSV final solo tenía registrado el origen de **55** (la última corrida nada más). La fecha de cada archivo no se perdió — vive en el propio archivo porque `shutil.copy2` la preserva — pero el "de qué PC y de qué ruta original salió" sí, para 7 de las 8 corridas. Se corrigió a modo *append*, con una columna nueva `Corrida` para poder distinguir de qué pasada vino cada fila cuando se fusionan varios destinos a mano.

2. **La biblioteca de ejemplos de Studio 5000 se coló en el barrido.** De los 2.590 archivos encontrados, **1.781 (69%) resultaron ser samples y AOIs de demostración de Rockwell** (`ADD_ON_INSTRUCTIONS_SAMPLES`, `AOG_SampleCode`, `ABSOLUTE_POSITION_DRIVELOGIX`, etc.) — no son PLCs de la planta. Se agregaron `Samples`, `Rockwell Software`, `Studio 5000`, `RSLogix 5000`, `FactoryTalk` y `Add-on Instructions` a la lista de carpetas ignoradas, para que corridas futuras no arrastren este ruido.

---

## 3. Nuevo módulo: filtrado a versiones más recientes

Se desarrolló **`src/analizar_dist_recolectado.py`**, que resuelve el pedido explícito de "primero filtremos a los más recientes":

- Agrupa las 921 subcarpetas en **familias de equipo real** (colapsa sufijos `_DUP<n>` y colas `.BAK<n>`/`.DESKTOP-`/`.WIN_` que quedaron de fusionar corridas distintas).
- Filtra contra una lista curada de vocabulario real de la planta — separa **48 familias reales** de los **420 grupos de ruido** (samples de Rockwell).
- Para cada familia real, identifica el archivo más reciente (cualquier extensión) y el `.L5X` más reciente específicamente — el único formato que nuestro motor puede auditar.
- Compara contra el canónico vigente en `auto_agustin/` y sugiere una acción, con una advertencia explícita: la comparación es **solo por fecha**, no por contenido — ya nos pasó que un `.L5X` con fecha de export más nueva resultó ser un subconjunto de tags de una versión más vieja sin tocar. Cualquier "candidato" debe confirmarse con diff de tags antes de reemplazar un canónico.

Salida: `ANALISIS_mas_recientes.csv`, generado dentro de la propia carpeta `dist`.

---

## 4. Resultado del filtrado

### 4.1 Ya resuelto, sin acción nueva

5 de las familias marcadas como "más recientes por fecha" (`DIBACCO`, `CALD_LA_FLORIDA`, `CALDERAS_8_9_10_DESAIREADOR`, `CENIZAS2020`, `TRAPICHE2022`) resultaron ser **exactamente los mismos archivos** ya comparados tag-a-tag el 06/08 y confirmados como subconjuntos obsoletos (re-exports frescos de `.ACD` sin tocar hace meses). No requieren ninguna acción adicional.

### 4.2 Controladores en edición activa — sin `.L5X` disponible todavía

| PLC | Última actividad detectada en disco | Comparación con nuestro canónico |
|---|---|---|
| **DIBACCO** | `.ACD` de **hoy 07/08 08:24** | 2 semanas más nuevo — hay alguien con el proyecto abierto ahora mismo |
| **CALD_LA_FLORIDA** | `.ACD` (`BAK041`) del 06/08 14:43 | posterior al lote ya archivado como obsoleto |
| **FABRICA** | `.ACD` (`BAK093`) del 06/08 17:23 | **nunca tuvo un `.L5X` exportado** en toda la historia relevada |
| **USINA_LA_FLORIDA** | `.ACD` del 29/07 | 5 días más nuevo que el canónico del 24/07 |

Los 4 son `.ACD` exclusivamente — nuestro motor de auditoría es `.L5X`-only por regla del proyecto, así que ninguno se puede taguear ni cruzar con los datos de Yanco hasta que Ingeniería los exporte desde Studio 5000.

### 4.3 Equipos nunca antes relevados

- **`DESFIBRADOR_LA_FLORIDA`** (desfibradora de caña) — 3 variantes, la más reciente del 16/07/2026. Equipo real de planta, nunca auditado hasta ahora.
- **`CENTRIFUGA_1RA_DISCRETO`** / **`CENTRIFUGA_1RA_ETHERNET`** — mayo/junio 2026, posibles variantes de I/O (discreta vs. Ethernet) de una primera línea de centrífugas, distinta de `CENTRIFUGA_DE_PRIMERA` (que ya es canónica).

El resto del "ruido real" identificado son copias históricas de desarrollo entre 2023 y 2025 (`FABRICA22`, `FABRICA231`, `TRAPICHE2024`, variantes `_PRUEBA`/`_BACKUP`/`_EDICION` de Centrífuga) — sin urgencia, quedan documentadas en el CSV para referencia futura.

---

## 5. Estado actual y próximos pasos

**Situación:** herramienta de recolección validada en uso real sobre 4 PCs; primer filtrado a versiones más recientes completado; 2 bugs de la herramienta corregidos a partir de datos reales.

**Prioridades sugeridas:**

1. Pedir a Ingeniería el export fresco a `.L5X` de, en este orden: `DIBACCO` (en edición hoy mismo), `CALD_LA_FLORIDA`, `FABRICA` (jamás exportado), `USINA_LA_FLORIDA`, `DESFIBRADOR_LA_FLORIDA`, `CENTRIFUGA_1RA_DISCRETO`/`ETHERNET`.
2. En cuanto lleguen esos `.L5X`, correr auditoría ISA-5.1 + cruce con Yanco sobre cada uno (mismo flujo ya validado para los 10 canónicos actuales).
3. Sigue pendiente desde el informe anterior: Excel de Yanco de `.131`/`.132` (Fermentación) para descongelar `DESTILERIA_RECUPERADO`/`vinaza`; resolver los 1.136 conflictos de numeración; extraer el dialecto de `jw2013`.

---

## 6. Nota metodológica

El análisis de esta sección se basa **únicamente en fechas de modificación de archivo** (preservadas por `shutil.copy2` desde el disco original), no en contenido. Es un triage de primer nivel para decidir *dónde* mirar primero — no reemplaza la comparación tag-a-tag que ya demostró ser necesaria antes de dar por obsoleta o vigente cualquier versión.
