# Resumen Ejecutivo de Avance
## Proyecto de Estandarización de Instrumentación y Control — Ingenio La Florida

**Fecha:** 06 de agosto de 2026
**Informe anterior:** `Resumen_Ejecutivo_Avance_310726` (31/07/2026)

---

## 1. Resumen de la jornada

Jornada larga, con seis frentes de trabajo que amplían el alcance del proyecto en dos direcciones nuevas: (a) validar la auditoría estática de los `.L5X` contra la realidad viva de la planta, y (b) sentar las bases de un futuro repositorio centralizado de fuentes de PLC. Se completaron:

1. Carga masiva de funciones ISA-5.1 en el catálogo de Tags App.
2. Auditoría y depuración de un nuevo relevamiento de 12 archivos (`NUEVO RELEVAMIENTO`): detección de versiones obsoletas, incorporación de versiones más completas y de un PLC nuevo (`jw2013`).
3. Cruce automático entre la auditoría `.L5X` y los inventarios de variables vivas relevados por Yanco directamente de los PLCs físicos (15 Excel en dos tandas).
4. Escaneo profundo de lógica de programa para distinguir tags "vivos en memoria" de tags realmente referenciados por algún rung o bloque FBD — detección de tags **Zombi**.
5. Corrección topológica del complejo Destilería (reasignación de IPs tras revisión con el ingeniero de planta).
6. Desarrollo y compilación de una herramienta standalone (`.exe`) para centralizar los `.ACD`/`.L5X` dispersos en las 5 PCs de ingeniería de la planta.

---

## 2. Carga masiva de funciones ISA-5.1 (Tags App)

Se actualizó `_cargar_funciones_isa_estandar()` en `database.py` (llamada en cada `init_db()`, con `INSERT OR IGNORE` sobre la columna `letra` que es `UNIQUE`) para precargar 15 funciones del estándar ANSI/ISA-5.1-2024: las 12 pedidas explícitamente (`SV`, `E`, `Y`, `C`, `Q`, `A`, `AH`, `AL`, `Z`, `ZT`, `ZSC`, `ZSO`) más 3 adicionales justificadas directamente en la Tabla 1 de la norma (`G` — Visor local, `K` — Estación de control, `U` — Multifunción).

Se ejecutó contra la base de datos viva de Tags App. Las 4 letras que ya existían (`E`, `AH`, `AL`, `C`) se verificaron intactas — no se sobrescribió ni duplicó nada. El desplegable **Función del instrumento** de Tags App pasó de 17 a **28 opciones**, verificado end-to-end instanciando la aplicación.

---

## 3. Auditoría del nuevo relevamiento (`NUEVO RELEVAMIENTO`)

Se recibió una carpeta con re-exports frescos (Studio 5000) de los mismos controladores, generados desde archivos `.ACD`, más 2 archivos de librería genérica de Rockwell y un PLC nuevo (`jw2013`).

### 3.1 Filtro de librerías/AOI endurecido

Se detectaron 2 `.L5X` (`raC_Opr_NetModbusTCPClient/Server_Rung`) que no eran PLCs sino fragmentos de biblioteca Modbus de Rockwell (`TargetType="Rung"`, `Owner="Rockwell Automation Inc"`, de 2022). Se archivaron en `data_historica/librerias_rockwell_no_proyecto/` y se endureció `procesar_todos_l5x.py` para filtrar por el atributo `TargetType` del XML (no solo por nombre de archivo) — cubre cualquier fragmento similar a futuro, tenga o no "AOI" en el nombre.

### 3.2 Detección de versiones obsoletas (comparación tag-a-tag)

Se comparó el set de tags de cada re-export contra el canónico activo. **5 PLCs resultaron subconjunto estricto** del canónico ya vigente (0 tags exclusivos del lado nuevo) — versiones más viejas, confirmadas y archivadas en `data_historica/nuevo_relevamiento_obsoletos_060826/`: `DIBACCO`, `CALD_LA_FLORIDA`, `Calderas_8_9_10_Desaireador`, `cenizas2020`, `TRAPICHE2022`.

### 3.3 Reemplazo de canónicos por versiones más completas

**3 PLCs resultaron ser el caso inverso** — el re-export era *superset* del canónico vigente:

| PLC | Tags canónico viejo | Tags nuevo canónico |
|---|---|---|
| CENTRIFUGA_DE_PRIMERA | 849 | 1.806 |
| vinaza | 611 | 613 |
| DESTILERIA_RECUPERADO | 1.608 | 1.628 |

Los 3 viejos se archivaron en `data_historica/backup_canonicos_viejos/` y, por directiva expresa, se procesaron igual con el motor individual (`auditar_l5x.py`) para no perder su resultado de auditoría — separado del reporte global. Se corrigió además el diccionario `AREA_DEFECTO_POR_PLC` (la clave vieja no matcheaba el nuevo nombre de archivo de Centrífuga).

Se sumó `jw2013` como **décimo PLC canónico**, nunca antes relevado.

### 3.4 Reporte Estadístico Global actualizado

| Métrica | 31/07/2026 | 06/08/2026 |
|---|---|---|
| PLCs procesados | 9 | **10** |
| Tags totales | — | 13.471 |
| Universo ISA/proceso | — | 10.670 |
| **Efectividad ISA global** | 56,81% | **55,02%** (5.871/10.670) |

La leve baja no es un retroceso: es la incorporación de `jw2013` (25,7% de efectividad — el más bajo de todo el relevamiento) y la sustitución de PLCs por versiones más grandes y con más tags sin clasificar todavía.

---

## 4. Cruce con variables vivas de Yanco (planta real)

Nuevo módulo **`src/cruzar_planta_viva.py`**. Regla de oro: el Excel de Yanco (inventario de tags leído directamente del PLC físico) **nunca** se usa para proponer o generar tags — es solo tabla de validación cruzada. Los CSV originales de `resultados/` no se tocan; el cruce se escribe en `resultados_cruzados/` con dos columnas nuevas: `Estado_Planta` (`En Uso` / `Obsoleto/Desconectado` / `Sin_Relevamiento_Vivo`) e `IP_Fisica`.

Puntos de diseño resueltos:
- **Tercer estado explícito** `Sin_Relevamiento_Vivo` para PLCs sin Excel todavía — evitar el error grave de marcarlos "obsoletos" sin datos para verificar.
- **Matching de tags** con el fallback de calificación Rockwell (`PROGRAM:<programa>.<tag>` → raíz sin prefijo): validado al 100% (568/568) contra DIBACCO.
- **Pares redundantes**: `Calderas_8_9_10_Desaireador` (.195/.196) y `CALD_LA_FLORIDA` (.251/.252) tienen controlador primario/secundario (módulo `1756-RM2`) — se fusiona (unión) el set de tags vivos de ambos nodos.

Se corrió en dos tandas (7 Excel → 15 Excel):

| PLC | Estado |
|---|---|
| CALD_LA_FLORIDA, DIBACCO, TRAPICHE2022, USINA_LA_FLORIDA | En Uso 100% |
| CENTRIFUGA_DE_PRIMERA | En Uso 100% |
| Calderas_8_9_10_Desaireador | En Uso 99,6% (5 obsoletos) |
| cenizas2020 | En Uso 99,2% (6 obsoletos) |
| jw2013 | En Uso 56,5% (**755 obsoletos** — el más sucio) |
| DESTILERIA_RECUPERADO, vinaza | `Sin_Relevamiento_Vivo` (congelados, ver sección 6) |

**Hallazgos bonus** (Excel de PLCs vivos sin `.L5X` todavía, sin CSV generado): `FABRICA` (.118, 3.442 tags), `LA_FLORIDA` (.160, 676 tags — turbogenerador de Usina distinto de `USINA_LA_FLORIDA`), `Painel_Ctr_Turb_Moenda` (.174, 254 tags).

---

## 5. Escaneo profundo de lógica — detección de tags Zombi

Nuevo módulo **`src/escanear_referencias_logica.py`**. Motivación: `Estado_Planta='En Uso'` solo prueba que el tag sigue declarado en la tabla de memoria del PLC, no que algún rung o diagrama FBD lo referencie realmente. Reutiliza `extraer_tags_referenciados()` del motor principal (ya validado, usado para herencia de área por Scope) para recorrer **todas** las `Routine` de **todos** los `Program` de cada `.L5X`: texto RLL de rungs y operandos FBD (`IRef`/`ORef`/`Block`).

Cuidado UDT resuelto: un operando FBD compuesto (`Bomba_Agua.Cmd_Run`, `Tag[3].Member`) se descompone también por su raíz antes del primer `.`/`[`, para no marcar como falso negativo a un tag que solo se referencia vía uno de sus miembros.

Columna `Referenciado_En_Logica` ('Si'/'No') agregada directamente sobre los CSV de `resultados_cruzados/`.

**Resultado (tras la corrección de topología de la sección 6): 2.695 tags Zombi** — el 26,1% de los 10.326 tags marcados "En Uso" está vivo en memoria pero **ningún rung ni bloque FBD lo usa**. Es basura histórica real y cuantificada, candidata directa a limpieza. Peor caso: `CENTRIFUGA_DE_PRIMERA` con 46,8% de sus tags "En Uso" sin referencia en lógica.

---

## 6. Corrección topológica del complejo Destilería

Revisión de red con el ingeniero de planta reveló que "Destilería" no es un solo controlador sino un **complejo de varios equipos físicos separados**: JW (.128), Fermentación Analógica (.131, Excel pendiente), Fermentación Digital (.132, Excel pendiente) y Evaporación/Vinaza (Excel pendiente). El Excel que se había asociado a `DESTILERIA_RECUPERADO` por nombre en realidad correspondía al equipo JW.

Se implementó en `cruzar_planta_viva.py`:
- `MANUAL_IP_OVERRIDES`: la IP `.128` se reasigna exclusivamente a `jw2013`, con prioridad absoluta sobre el matching por nombre.
- `PROYECTOS_CONGELADOS`: `DESTILERIA_RECUPERADO` y `vinaza` se fuerzan a `Sin_Relevamiento_Vivo` — no se cruzan con ningún Excel hasta contar con los relevamientos correctos de `.131`/`.132`.

Se recalculó el cruce completo y el escaneo Zombi con el nuevo mapa (números ya reflejados en las secciones 4 y 5).

---

## 7. Herramienta de recolección para las 5 PCs de ingeniería

Nuevo módulo standalone **`src/recolector_fuentes_plc.py`** (solo librería estándar de Python, sin dependencias) — primer paso hacia un control de versiones centralizado tipo FactoryTalk AssetCentre. Reglas aplicadas:

- Deep scan recursivo desde un directorio que el usuario ingresa, ignorando carpetas de sistema operativo (`Windows`, `Program Files`, etc.).
- **No destructivo**: copia con `shutil.copy2` (preserva la fecha de modificación original — métrica de verdad para decidir a futuro cuál versión es la más nueva).
- Clasificación inteligente: limpia sufijos basura del nombre (backups de Studio 5000, fechas, duplicados de Windows, palabras como `v2`/`final`/`viejo`/`copia`) para agrupar todas las copias del mismo equipo en una subcarpeta.
- Trazabilidad completa: `trazabilidad_extraccion.csv` con archivo destino, equipo clasificado, fecha original y ruta absoluta de origen. Manejo de errores robusto (carpetas sin permiso, archivos bloqueados) sin frenar el barrido, con log aparte.

Se compiló con PyInstaller (`--onefile --console`) a **`RecolectorFuentesPLC.exe`** (7,0 MB, standalone), se probó de punta a punta en un banco de pruebas aislado (clasificación, deduplicación, preservación bit-a-bit de la fecha de modificación, cierre controlado con pausa final) y se entregó al usuario para llevarlo en pendrive a las 5 PCs de la planta.

---

## 8. Estado actual y próximos pasos

**Situación:**
- Tags App con catálogo de 28 funciones ISA-5.1.
- 10 PLCs canónicos auditados, 55,02% de efectividad ISA global.
- Cruce planta-viva operativo sobre 8 de los 10 PLCs (2 congelados a propósito por la reestructuración de Destilería).
- Detección de tags Zombi operativa: 2.695 tags identificados como basura histórica real.
- Herramienta de recolección lista para desplegar en las 5 PCs de ingeniería.

**Prioridades sugeridas:**

1. Conseguir los Excel de Yanco de `.131` (Fermentación Analógica) y `.132` (Fermentación Digital) para descongelar `DESTILERIA_RECUPERADO` y `vinaza`.
2. Correr `RecolectorFuentesPLC.exe` en las 5 PCs de ingeniería y cruzar los `trazabilidad_extraccion.csv` resultantes para identificar, por equipo, la copia más nueva según fecha real.
3. Exportar a `.L5X` los 3 PLCs vivos detectados sin auditoría todavía: `FABRICA` (.118), `LA_FLORIDA` (.160), `Painel_Ctr_Turb_Moenda` (.174).
4. Resolver los 1.136 conflictos de numeración entre PLCs (`conflictos_tags_duplicados.csv`), pendiente desde el informe anterior.
5. Extraer el dialecto de `jw2013` (56,5% en uso pero 755 tags obsoletos, y solo 25,7% de efectividad ISA) — candidato a revisión prioritaria junto con DIBACCO.

---

## 9. Nota metodológica

Los indicadores de este informe combinan tres fuentes con roles distintos, que no deben confundirse: (a) el escaneo masivo automático sobre `.L5X` (motor ISA-5.1, fuente única para nombrar/clasificar tags), (b) los inventarios de Yanco relevados en vivo desde los PLCs físicos (solo validación cruzada, nunca generan tags), y (c) el escaneo de lógica de programa (solo determina si un tag ya existente está referenciado, no cambia su clasificación ISA). La base operativa de Tags App (789 tags) es independiente de estos tres y combina la carga masiva inicial con las altas/ediciones manuales del equipo.
