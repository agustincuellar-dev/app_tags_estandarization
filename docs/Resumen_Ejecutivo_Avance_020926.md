# Resumen Ejecutivo de Avance
## Proyecto de Estandarización de Instrumentación y Control — Ingenio La Florida

**Fecha:** 2 de septiembre de 2026
**Informe anterior:** `Resumen_Ejecutivo_Avance_010926` (01/09/2026)

---

## 1. Resumen del período

Jornada orientada a **dejar el proyecto distribuible y respaldado**: mejoras de usabilidad y de compatibilidad con el PLC, una **nueva app utilitaria de subida a GitHub**, el cambio de **logo de la aplicación**, y el **empaquetado de la Tags App en un `.exe`** con su base de datos persistente.

Cinco frentes:

1. **Cinco mejoras de UI/producto** en `app_tags.py` y `database.py` (ventana maximizada, sugerencia del primer número de lazo libre, compatibilidad Studio 5000 con `generar_tag_plc`).
2. **Nueva app "GitHub Pusher"** (`github_pusher.py`) con repo parcial y `.gitignore` automático.
3. **Logo de la app** apuntando a `logo_app_tags.ico` (ventana + encabezado).
4. **Empaquetado a `.exe`** con PyInstaller (`TagsApp.exe`), previa localización de Python.
5. **Base de datos persistente** junto al ejecutable.

---

## 2. Cinco mejoras de UI y producto

### 2.1 Ventana maximizada al inicio

`__init__` ahora ejecuta `self.state("zoomed")` tras crear `Tk()`, de modo que la app abre en pantalla completa. Además se subió el tamaño mínimo a `1200×768` para que los 5 pasos queden visibles sin scroll.

### 2.2 Sugerencia inteligente del número de lazo

`proponer_siguiente_tag()` en `database.py` dejó de usar `MAX+1` y ahora **rellena huecos**: extrae todos los `numero_loop` de la combinación Área+Variable+Función y propone el **primer número libre** a partir de `001`.

```
Si existen FV_001, FV_002 y FV_050  ->  se sugiere FV_003  (no FV_051)
```

El campo editable "Editar" del Paso 1 admite ajuste manual sin validaciones restrictivas.

### 2.3 Compatibilidad Studio 5000 (Allen-Bradley)

Nueva función `generar_tag_plc(tag_oficial)`:

- Si el tag empieza con número → antepone `_` (ej. `200_PIT_004` → `_200_PIT_004`).
- Si ya empieza con `_` → lo devuelve sin cambios.

Se integró en la exportación a Excel (Paso 5): se agrega la columna **`Tag_Studio5000`** junto a la columna del tag (`tag_completo`), aplicando `generar_tag_plc()` a cada fila exportada.

---

## 3. Nueva app: GitHub Pusher

### 3.1 `github_pusher.py`

App independiente con Tkinter (entry de mensaje de commit + botón "Push a GitHub") que ejecuta vía `subprocess.run`:

```
git add <selectivo>  ->  git commit -m "<mensaje>"  ->  git push origin main
```

Muestra el progreso en un label de estado y maneja errores: sin repositorio git, sin cambios para commitear, fallos en `add`/`commit`/`push`.

### 3.2 Repositorio parcial con `.gitignore`

Se configuró para que **solo se versionen** `app_etiquetas/`, `src/` y `docs/` (más el `.gitignore`), quedando fuera `exports/`, `build/`, `dist/`, `__pycache__/`, `*.pyc`, `.env`, `github_pusher.py`, `probar_lazo.py`, `*.log`, etc.

- **Inicialización inteligente:** si no hay `.git` → `git init` + `git remote add origin`; si ya existe, se usa y se re-apunta el remote si difiere.
- **`.gitignore` automático:** se genera/actualiza en la raíz del repo en cada apertura.
- **`git add` selectivo:** `git add app_etiquetas/ src/ docs/ .gitignore`.
- **Selector de carpeta:** `filedialog.askdirectory()` con la ruta mostrada en un label y validación de que contenga `app_etiquetas/`, `src/` o `docs/`.

### 3.3 Remote fijo

`REMOTE_URL = https://github.com/agustincuellar-dev/app_tags_estandarization.git`. Si el remote `origin` no existe se agrega; si existe pero es otro, se actualiza con `set-url`. El push usa la rama `main`.

---

## 4. Logo de la aplicación

Se apunta al archivo existente `logo_app_tags.ico` (sin generar iconos nuevos):

- **Icono de ventana:** `self.iconbitmap(logo_app_tags.ico)` (con fallback a `app_tags.ico`).
- **Logo del encabezado:** se carga con `PIL.ImageTk` (`logo_app_tags.ico` redimensionado a `80×80`) en el `header_frame`, guardando la referencia en `self.logo_img` para evitar que el garbage collector lo elimine.
- **Rutas relativas correctas** con `os.path.join(os.path.dirname(__file__), ...)` y manejo de errores si el archivo falta.

Imports agregados: `from PIL import Image, ImageTk` (con import guardado si PIL no está).

---

## 5. Empaquetado a `.exe` con PyInstaller

### 5.1 Localización de Python

Como `python`/`pip` no están en el PATH de Windows, se creó `encontrar_python.py` para localizar instalaciones en las rutas habituales:

```
3.13.7  ->  C:\Users\Administrador\AppData\Local\Programs\Python\Python313\python.exe
3.11.16 ->  C:\Users\Administrador\AppData\Roaming\uv\python\cpython-3.11...\python.exe
```

También funciona el launcher `py` (`py -0p`).

### 5.2 Instalación y build

PyInstaller `6.21.0` ya estaba disponible en el Python 3.13. Se empaquetó la Tags App con ruta absoluta:

```
python.exe -m PyInstaller --noconfirm --onefile --windowed --name TagsApp \
  --icon logo_app_tags.ico \
  --add-data logo_app_tags.ico;. --add-data logo_header.png;. --add-data logo_balcanes.png;. \
  --add-data schema.sql;. --add-data tags_ingenio.db;. \
  app_tags.py
```

**Resultado:** `app_etiquetas\dist\TagsApp.exe` (~59,6 MB, ventana sin consola, ícono propio), con las dependencias incluidas (Tkinter, PIL, networkx, matplotlib, openpyxl, pandas).

---

## 6. Base de datos persistente junto al `.exe`

Como en modo compilado `database.py` vive en una carpeta temporal (PyInstaller), se agregó `_resolver_db_path()` en `database.py`:

- **Compilado (`.exe`):** usa/crea `tags_ingenio.db` **junto al ejecutable**; en el primer arranque copia la base incluida ahí, de modo que los tags cargados **persisten** entre ejecuciones.
- **Código fuente:** sigue usando la base de `app_etiquetas/`.

`SCHEMA_PATH` conserva la ruta a la copia empaquetada (solo lectura, para `init_db()`).

---

## 7. Archivos modificados hoy

| Archivo | Cambio |
|---|---|
| `app_etiquetas/app_tags.py` | Ventana maximizada (`state('zoomed')`) + `minsize(1200,768)`, `generar_tag_plc()` + columna `Tag_Studio5000` en exportación Excel, logo `logo_app_tags.ico` (ventana + header con PIL) |
| `app_etiquetas/database.py` | `proponer_siguiente_tag()` con primer número libre; `_resolver_db_path()` para base persistente junto al `.exe` |
| `github_pusher.py` | **Nuevo** — app GitHub Pusher con repo parcial, `.gitignore` automático y `add` selectivo; remote fijo `agustincuellar-dev/app_tags_estandarization` |
| `encontrar_python.py` | **Nuevo** — localiza instalaciones de Python en Windows |
| `app_etiquetas/logo_app_tags.ico` | Logo de la app usado en ventana y encabezado |
| `TagsApp.spec` / `app_etiquetas/build/` | Generados por PyInstaller |
| `app_etiquetas/dist/TagsApp.exe` | **Nuevo** — ejecutable de la Tags App (~59,6 MB), base persistente junto al exe |
