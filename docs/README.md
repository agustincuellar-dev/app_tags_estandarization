# Sistema de Gestión de Tags — Ingenio La Florida

Aplicación local (sin internet ni nube) para asignar tags de instrumentación
según la lógica de ANSI/ISA-5.1, sin que el usuario necesite conocer la norma.

## Requisitos

- Python 3.9 o superior (ya trae `sqlite3`).
- Módulo `tkinter`. En la mayoría de instalaciones de Windows y macOS viene
  incluido. En Linux (Ubuntu/Debian) instalar con:
  ```
  sudo apt-get install python3-tk
  ```

No requiere `pip install` de nada más: solo librería estándar.

## Cómo correrlo

```bash
cd tag_governance
python3 app_gui.py
```

La primera vez que se ejecuta, se crea automáticamente el archivo
`tags_ingenio.db` (SQLite) en la misma carpeta, con las áreas, variables
y funciones precargadas. **Ese archivo `.db` es toda la base de datos** —
para respaldarlo basta con copiarlo; para "resetear" el sistema, basta
con borrarlo (se regenerará vacío en el próximo arranque).

## Flujo de uso

1. Elegir **Área** (ej. Generación de Vapor / Calderas).
2. Elegir **Variable** (ej. Presión).
3. Elegir **Función** (ej. Transmisor).
4. Click en **"Consultar tags existentes y proponer siguiente"** → aparece
   la lista de tags ya usados en esa categoría y el sistema propone el
   siguiente correlativo libre (ej. `PT-201`).
5. Completar descripción, ubicación, fabricante, etc.
6. Click en **"Confirmar y Guardar Tag"**. El sistema pide confirmación y
   guarda. La restricción `UNIQUE` en la base de datos hace **imposible**
   guardar un tag duplicado, incluso por error humano.

## Estructura de archivos

```
tag_governance/
├── schema.sql      # Definición de tablas (áreas, variables, funciones, tags, auditoría)
├── database.py     # Toda la lógica: conexión, catálogos, generación de tags, alta
├── app_gui.py       # Interfaz gráfica (Tkinter) que consume database.py
└── README.md
```

La lógica de negocio está **separada de la interfaz a propósito**: si en el
futuro quieren una versión web (Flask) o multiusuario en red, `database.py`
se reutiliza casi sin cambios; solo se reemplaza `app_gui.py`.

## Cómo generar el tag (regla implementada)

```
TAG = [Letra de Variable][Letra de Función] - [Número de lazo, 3 dígitos]
```

El número de lazo se calcula como:
- Si ya existe algún tag con esa misma combinación Área+Variable+Función,
  se toma el número más alto existente **+ 1**.
- Si no existe ninguno, se toma el número de **inicio del rango del área**.
- Si el siguiente número supera el **fin del rango del área**, el sistema
  avisa que el rango se agotó (en vez de inventar un número fuera de bloque).

## Personalizar áreas / variables / funciones

Los catálogos se precargan solo si las tablas están vacías (ver
`_seed_if_empty` en `database.py`). Para agregar/editar áreas, variables o
funciones ya con la base de datos creada, la forma más simple por ahora es
con el CLI de SQLite:

```bash
sqlite3 tags_ingenio.db
sqlite> INSERT INTO areas (codigo, nombre, rango_inicio, rango_fin)
        VALUES ('DES', 'Destilería', 1000, 1099);
```

(En una fase 2 se puede agregar una pantalla de administración de catálogos
dentro de la misma app para no depender del CLI.)

## Evolución arquitectónica ("Tags App inteligente")

Diseño (no implementado todavía) de tres mecanismos para reemplazar las
excepciones y reglas hoy hardcodeadas en Python por tablas consultables y
editables sin tocar código: ver
[`Roadmap_Arquitectura_Inteligente.md`](Roadmap_Arquitectura_Inteligente.md).

## Próximos pasos sugeridos (Fase 2)

- Pantalla de **administración de catálogos** (agregar áreas/variables/
  funciones desde la interfaz, sin tocar SQL).
- Pantalla de **búsqueda/edición** de tags ya creados (hoy `buscar_tags()`
  ya existe en `database.py`, falta la pantalla).
- **Exportar a Excel/CSV** para entregar el listado maestro al equipo de
  instrumentación.
- **Importar** el inventario actual de tags de zafra (para que en verano,
  cuando se migren los tags físicos, la base ya tenga el "mapa" completo
  de tag viejo → tag nuevo).
- Empaquetar con `PyInstaller` (`pyinstaller --onefile app_gui.py`) para
  distribuir un único `.exe`/binario sin que el usuario necesite Python
  instalado.
- Si más de una persona va a cargar tags a la vez desde distintas PCs,
  mover la `.db` a una carpeta compartida en red (SQLite soporta varios
  lectores, pero solo un escritor a la vez; si el volumen de altas
  concurrentes crece, ahí sí conviene migrar a un motor cliente-servidor
  como PostgreSQL).
