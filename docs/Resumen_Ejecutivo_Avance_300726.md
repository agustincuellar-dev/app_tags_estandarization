# Resumen Ejecutivo de Avance
## Proyecto de Estandarización de Instrumentación y Control — Ingenio La Florida

**Fecha:** 30 de julio de 2026
**Período cubierto:** desde el armado de la base de datos definitiva hasta la puesta en marcha de la aplicación **Tags App**
**Informe anterior:** `Resumen_Ejecutivo_Avance_240726`

---

## 1. Resumen de la etapa

Con el motor de auditoría ya congelado en la etapa anterior (56,81% de efectividad ISA sobre 12 PLCs), esta etapa se concentró en **llevar los resultados a producción**: cargar los tags validados en la base de datos operativa, ordenar el espacio de trabajo como un proyecto de software mantenible, y dar identidad propia a la aplicación de gestión.

Se completaron tres frentes:

1. **Carga de la base de datos definitiva** de la aplicación.
2. **Reorganización integral del workspace** con actualización de rutas.
3. **Identidad de la aplicación**: nombre, logo e ícono.

---

## 2. Base de datos definitiva

### 2.1 Resultado de la carga

Se procesaron las 12 planillas de mapeo exitoso generadas por el orquestador y se cargaron en la base operativa de la aplicación.

| Concepto | Cantidad |
|---|---|
| **Instrumentos ISA cargados en la base** | **787** |
| Registros de auditoría generados | 787 |
| Controladores representados | 11 |

**Distribución por área:**

| Área | Tags | | Área | Tags |
|---|---|---|---|---|
| 200 — Destilería | 354 | | 100 — Molienda | 146 |
| 300 — Calderas | 204 | | 900 — Fuerza Motriz | 51 |
| 800 — Secado y Envase | 12 | | 700 — Centrifugado | 8 |
| 000 — Recepción de Caña | 6 | | 400 — Clarificación | 5 |
| 500 — Evaporación | 1 | | | |

### 2.2 Hallazgo crítico: los tags no son únicos a nivel planta

De los 1.923 tags con formato ISA disponibles, **solo 787 pudieron cargarse. 1.136 fueron rechazados por duplicación.**

La causa no es un defecto del sistema, sino un **problema real de la planta que el proceso dejó al descubierto**: cada PLC numeró sus lazos de forma independiente, por lo que el mismo tag existe simultáneamente en varios controladores. El caso más representativo es `300_LT_001`, que aparece en **siete controladores distintos** (CALD_LA_FLORIDA, Calderas 8/9/10 ×2, Destilería ×3 y cenizas2020), identificando siete instrumentos físicos diferentes.

La restricción de unicidad de la base de datos rechazó estos casos **correctamente**: bajo ANSI/ISA-5.1 un tag debe identificar un único instrumento en toda la planta.

**Acción tomada:** se cargó la primera ocurrencia de cada tag y se generó la planilla `auto_agustin/resultados/conflictos_tags_duplicados.csv` con los **1.136 casos en conflicto**, indicando para cada uno el tag afectado, el PLC rechazado, el PLC que ocupa el tag y el nombre heredado original. Adicionalmente se incorporó el campo `plc_origen` en la base, de modo que cada tag conserva la trazabilidad de su controlador de procedencia.

> **Requiere decisión de Ingeniería:** la renumeración de estos 1.136 casos es un criterio de planta, no una decisión automatizable. Es el principal bloqueante para completar la carga.

### 2.3 Alcance del modelo de datos

El modelo actual representa un tag como la combinación (área, variable, función, número), por lo que solo admite instrumentos ISA puros. Quedaron fuera de la carga, por no ser instrumentos:

| Tipo | Cantidad |
|---|---|
| Miembros de UDT (`.Raw`, `.Tot`, `.Sts_Running`, …) | 436 |
| Lógica de estado y equipos | 6.501 |
| Canales de E/S de reserva | 153 |

---

## 3. Reorganización del espacio de trabajo

Se reemplazó la estructura plana anterior (una carpeta `files/` con todo mezclado) por una organización de proyecto de software:

```
AUTOMATISMO_AGUSTIN/
├── src/               Motores de análisis (3 archivos)
├── app_etiquetas/     Aplicación Tags App + base de datos operativa
├── auto_agustin/      Respaldos .L5X + resultados por PLC (55 archivos)
├── docs/              Normas, manuales e informes (13 archivos)
├── data_historica/    Inventarios, exportaciones y pruebas previas (37 archivos)
└── resultados/        Salidas de corridas individuales
```

**Actualización de rutas (punto crítico):** al mover los motores a `src/`, todas las rutas relativas fueron reescritas para resolver desde la raíz del proyecto. Se verificó mediante ejecución real:

- `procesar_todos_l5x.py` — corrida completa sobre los 12 PLCs con **resultado idéntico** al previo a la mudanza (56,81%, 7.104 éxitos), confirmando que no hubo regresión.
- `auditar_l5x.py` y `auditar_masivo.py` — ejecutados y verificados.
- **Tags App** — arranca correctamente con sus 787 tags y catálogos intactos.

También se eliminaron duplicados de código (`app_gui.py` y `database.py` que existían por partida doble, verificados como idénticos antes de borrarlos) y se consolidaron los proyectos fuente de Studio 5000 (`.ACD`, 88 MB) en `data_historica/proyectos_studio5000/`.

---

## 4. Identidad de la aplicación: Tags App

La aplicación de gestión pasó a llamarse **Tags App** y recibió identidad visual propia.

| Cambio | Detalle |
|---|---|
| Archivo principal | `app_gui.py` → **`app_tags.py`** |
| Título de ventana | **Tags App — Ingenio La Florida** |
| Ícono | Barra de título y barra de tareas |
| Cabecera | Logo institucional + nombre + subtítulo |
| Paleta corporativa | Azul `#002157` y ámbar `#FFBB02`, extraídos del propio logo |

**Tratamiento del logo:** el archivo original incluía el texto "Tags App" bajo la parte gráfica. Se aisló únicamente el elemento gráfico (la red de nodos hexagonales) mediante detección automática de la banda de separación entre gráfico y texto, evitando un recorte aproximado. Se aplicó además fondo transparente preservando los detalles blancos interiores del diseño.

Activos generados:

| Archivo | Uso |
|---|---|
| `logo_app_tags.png` | Logo maestro (1433×675, transparente) |
| `logo_header.png` | Versión optimizada para la cabecera |
| `app_tags.ico` | Ícono multi-resolución (16 a 256 px) |

La aplicación se ejecuta con `python app_tags.py`. El logo y el ícono son opcionales por diseño: si los archivos faltaran, la aplicación arranca igual sin interrumpir la operación.

---

## 5. Hallazgo adicional: inventario completo de tags

Durante la reorganización se identificó el archivo `inventario_plcs_20260722_093248.xlsx - Tags.csv`, que contiene el **volcado tag por tag de toda la planta: 23.461 variables**, y que no había sido detectado antes.

Se procesó como prueba, obteniendo **24,7% de cobertura** (5.804 tags estandarizados) — sensiblemente por debajo del 56,81% alcanzado con los respaldos `.L5X`. La diferencia confirma lo previsto: una tabla plana carece de la topología de bloques de función y de la estructura de rutinas que el motor utiliza para inferir áreas por vecindad.

**Conclusión operativa:** la vía correcta sigue siendo procesar cada PLC desde su respaldo `.L5X`. El inventario resulta valioso, en cambio, como **control de cobertura**: permite identificar qué controladores de la planta aún no tienen respaldo incorporado al análisis.

---

## 6. Estado actual y próximos pasos

**Situación:**

- Motor de auditoría congelado y validado (56,81% de efectividad ISA sobre 12 PLCs).
- Base de datos operativa cargada con 787 instrumentos y trazabilidad por controlador.
- Aplicación **Tags App** operativa, con identidad propia.
- Proyecto reorganizado y con rutas verificadas.

**Prioridades sugeridas:**

1. **Resolver los 1.136 conflictos de numeración** — es el bloqueante principal; requiere criterio de Ingeniería sobre cómo renumerar lazos duplicados entre controladores.
2. **Revisión de campo de las variables pendientes** de los 12 PLCs procesados.
3. **Incorporar los respaldos `.L5X` faltantes**, cruzando contra el inventario de 23.461 tags para determinar qué controladores restan.
4. **Extraer el dialecto de DIBACCO** (27,6%), el controlador que quedó por debajo del promedio.
5. **Evaluar la extensión del modelo de datos** de la aplicación para admitir miembros de UDT y equipos, hoy fuera del alcance de la carga.

---

## 7. Nota metodológica

Los indicadores de este informe miden **cobertura de propuesta automática**: qué proporción de las variables pudo ser ubicada por área y recibir un nombre normalizado. **No equivalen a variables listas para cargar en los controladores**: toda propuesta requiere validación de Ingeniería antes de su aplicación en planta, especialmente en los casos señalados con observaciones en las planillas de resultados.
