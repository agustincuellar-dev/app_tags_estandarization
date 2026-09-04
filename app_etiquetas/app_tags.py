"""
app_tags.py
-----------
Tags App - Sistema de Gestión de Tags del Ingenio La Florida.
Flujo: Área -> Variable -> Función (autocompleta existentes y propuesta)
       -> completar datos -> Confirmar y Guardar.

Separación de responsabilidades: la consulta (actualizar_propuesta) es de
SOLO LECTURA; la única funcion que escribe en la base de datos es
on_guardar (Paso 4).

Ejecutar con:  python app_tags.py
"""

import os
import time
import tkinter as tk
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from tkinter import ttk, messagebox, simpledialog
import database as db
from validador_isa import auditar_tag_recien_guardado

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except Exception:
    _PIL_OK = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_HEADER = os.path.join(BASE_DIR, "logo_header.png")
LOGO_BALCANES = os.path.join(BASE_DIR, "logo_balcanes.png")
LOGO_APP_ICO = os.path.join(BASE_DIR, "logo_app_tags.ico")
ICONO_APP = os.path.join(BASE_DIR, "app_tags.ico")

# Paleta corporativa tomada del logo de la aplicación
AZUL = "#002157"
AMBAR = "#FFBB02"
GRIS = "#555555"
VERDE_CONFIRMA = "#1B8A3B"       # CTA de guardado: verde de confirmacion
VERDE_CONFIRMA_HOVER = "#166E2F"  # tono activo/click, un poco mas oscuro
ROJO_PELIGRO = "#B00020"          # accion destructiva (eliminar)
ROJO_PELIGRO_HOVER = "#7D0016"

# Diccionarios de mapeo para la lectura humana del tag (Paso 2).
MAPEO_AREAS = {
    "000": "Recepción y Preparación de Caña",
    "100": "Molienda",
    "200": "Destilería",
    "300": "Calderas",
    "950": "Tratamiento de Agua y Servicios",
}
MAPEO_VARIABLES = {
    "L": "Nivel", "P": "Presión", "T": "Temperatura", "F": "Caudal",
    "A": "Análisis", "I": "Corriente", "D": "Densidad", "W": "Peso",
    "S": "Velocidad", "V": "Vibración", "G": "Gases",
}
MAPEO_FUNCIONES = {
    "T": "Transmisor", "C": "Controlador", "IC": "Controlador Indicador",
    "V": "Válvula", "I": "Indicador", "R": "Registrador", "G": "Mirilla/Visor",
    "S": "Switch", "H": "Alta", "L": "Baja",
}
DICCIONARIOS = {
    "areas": MAPEO_AREAS,
    "variables": MAPEO_VARIABLES,
    "funciones": MAPEO_FUNCIONES,
}


def traducir_tag_humano(tag_completo, diccionarios):
    """Traduce un tag ISA-5.1 a lectura humana (área, variable, función)."""
    try:
        area_code, funcion, numero = tag_completo.split('_')
    except ValueError:
        return "Formato de tag no estándar"
    if not funcion:
        return "Formato de tag no estándar"
    variable_letra, detalle_letras = funcion[0], funcion[1:]
    nombre_area = diccionarios["areas"].get(area_code, area_code)
    variable = diccionarios["variables"].get(variable_letra, variable_letra)
    funcion_detalle = diccionarios["funciones"].get(
        detalle_letras, detalle_letras or variable_letra
    )
    return f"{funcion_detalle} de {variable}, lazo {numero}, área {area_code} ({nombre_area})"


def generar_tag_plc(tag_oficial):
    """Devuelve el tag compatible con Studio 5000 (Allen-Bradley).

    Un tag que empieza con número (ej. '200_PIT_004') no es válido como
    nombre en Studio 5000, así que se antepone '_' ('_200_PIT_004'). Si ya
    empieza con '_' (o no empieza con número), se devuelve sin cambios.
    """
    if tag_oficial and tag_oficial[0].isdigit():
        return "_" + tag_oficial
    return tag_oficial


class TagGovernanceApp(tb.Window):
    def __init__(self):
        super().__init__(
            title="Tags App - Gestión de Tags ISA-5.1",
            themename="darkly",
            size=(1200, 800),
        )
        self.state("zoomed")
        self.resizable(True, True)
        self.minsize(1200, 768)
        self._aplicar_identidad()

        db.init_db()

        # Caches de catálogos: {texto_visible: objeto_fila}
        self.areas = {f"{a['codigo']} - {a['nombre']}": a for a in db.listar_areas()}
        self.variables = {f"{v['letra']} - {v['nombre']}": v for v in db.listar_variables()}
        self.funciones = {f"{f['letra']} - {f['nombre']}": f for f in db.listar_funciones()}
        self.usuarios = [u["nombre"] for u in db.listar_usuarios()]

        self.tag_propuesto = None
        self.numero_propuesto = None
        # El número pertenece al lazo completo (Área + Variable), no a la
        # función individual. El operador decide si abre un lazo nuevo o
        # incorpora otro instrumento a uno ya existente.
        self.modo_lazo = tk.StringVar(value="nuevo")
        self.lazos_disponibles = {}
        # Si tiene valor, la app esta en MODO EDICION sobre ese tag (en
        # vez de proponiendo uno nuevo). Lo controla _entrar/_salir_modo_edicion.
        self.tag_en_edicion = None

        # Layout (31/08/2026): header FIJO arriba + contenido scrolleable.
        # El header (logos + título) vive en un frame propio fuera del
        # canvas, así NUNCA se desplaza; solo el contenido (Paso 1-5)
        # queda dentro del contenedor desplazable con scroll vertical.
        self.header_frame = tk.Frame(self, bg="white")
        self.header_frame.pack(side="top", fill="x")

        self._canvas = tk.Canvas(self, bg=self["bg"], highlightthickness=0)
        self.canvas = self._canvas
        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="top", fill="both", expand=True)

        self.contenedor = tk.Frame(self.canvas, bg=self["bg"])
        self._ventana_canvas = self.canvas.create_window(
            (0, 0), window=self.contenedor, anchor="nw"
        )
        self.contenedor.bind("<Configure>", self._on_contenedor_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)

        self._build_ui()

        # El alto se ajusta al contenido real (la cabecera con el logo
        # desplaza el formulario), en vez de a un valor fijo estimado,
        # pero NUNCA por encima de lo que entra en pantalla: si el
        # contenido supera el alto del monitor, la ventana abre a la
        # altura máxima visible y el scroll vertical cubre el resto.
        self.update_idletasks()
        alto = max(self.winfo_reqheight(), 640)
        alto = min(alto, self.winfo_screenheight() - 100)
        self.geometry(f"900x{alto}")
        self.refrescar_paso5()

    # ------------------------------------------------------------
    def _aplicar_identidad(self):
        """Asigna el icono de la ventana (nuevo logo 'T'). Si el .ico no
        está disponible (o el sistema no lo soporta), la app arranca igual
        sin icono."""
        try:
            if os.path.isfile(LOGO_APP_ICO):
                self.iconbitmap(LOGO_APP_ICO)
            elif os.path.isfile(ICONO_APP):
                self.iconbitmap(ICONO_APP)
        except tk.TclError:
            pass  # entorno sin soporte de iconbitmap: no es un error fatal

    # ------------------------------------------------------------
    # Scroll de página (patrón Canvas + Scrollbar): el formulario
    # completo (Paso 1 a Paso 5) es desplazable cuando la ventana es
    # más baja que el contenido (notebooks / pantallas chicas).
    # ------------------------------------------------------------
    def _build_scrollable(self):
        """Arma el contenedor desplazable: un Canvas con Scrollbar
        vertical que envuelve el frame `self.contenedor`, donde se
        empaqueta TODO el contenido de la app."""
        self._canvas = tk.Canvas(self, bg=self["bg"], highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self.contenedor = tk.Frame(self._canvas, bg=self["bg"])
        self._ventana_canvas = self._canvas.create_window(
            (0, 0), window=self.contenedor, anchor="nw"
        )

        self.contenedor.bind("<Configure>", self._on_contenedor_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_rueda)
        self.contenedor.bind("<MouseWheel>", self._on_rueda)

    def _on_contenedor_configure(self, event=None):
        """Recalcula el área desplazable: abarca todo el contenido, así
        que si un paso crece o decrece el scroll se adapta solo."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event=None):
        """El contenido ocupa siempre el ancho del canvas (scroll solo
        vertical, nada queda cortado a la derecha) y, si el canvas es
        más alto que el contenido, éste se estira para que la grilla
        del Paso 5 siga aprovechando la ventana agrandada."""
        if event.width > 1:
            self._canvas.itemconfigure(self._ventana_canvas, width=event.width)
        alto_contenido = self.contenedor.winfo_reqheight()
        alto_visible = self._canvas.winfo_height()
        if alto_visible > 1:
            self._canvas.itemconfigure(
                self._ventana_canvas, height=max(alto_contenido, alto_visible)
            )

    def _vincular_rueda(self, widget=None):
        """Hace que la rueda del ratón desplace la página sobre cualquier
        widget que NO tenga scroll propio. Treeview, Listbox, Combobox y
        Scrollbar se excluyen: manejan su rueda internamente (si no, el
        scroll sería doble)."""
        if widget is None:
            widget = self.contenedor
        for hijo in widget.winfo_children():
            if isinstance(hijo, (ttk.Treeview, tk.Listbox, ttk.Combobox, ttk.Scrollbar)):
                continue
            hijo.bind("<MouseWheel>", self._on_rueda)
            self._vincular_rueda(hijo)

    def _on_mousewheel(self, event):
        """Desplaza el Canvas principal con la rueda del mouse."""
        if hasattr(self, "canvas"):
            if getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
                direction = 1
            else:
                direction = -1
            self.canvas.yview_scroll(direction, "units")

    def _redirigir_scroll_combobox(self, combobox):
        """Evita que un Combobox cambie su valor con la rueda y desplaza la página."""
        combobox.bind("<MouseWheel>", self._on_mousewheel_combobox)
        combobox.bind("<Button-4>", self._on_mousewheel_combobox)
        combobox.bind("<Button-5>", self._on_mousewheel_combobox)

    def _on_mousewheel_combobox(self, event):
        self._on_mousewheel(event)
        return "break"

    def _on_rueda(self, event):
        """Compatibilidad con los bindings existentes del scroll de página."""
        self._on_mousewheel(event)

    def _agregar_logo_header(self, parent):
        """Carga el logo (logo_app_tags.ico) en el encabezado usando PIL.
        Se guarda la referencia en self.logo_img para evitar que el garbage
        collector lo elimine. Si PIL o el archivo faltan, se omite."""
        if not _PIL_OK or not os.path.isfile(LOGO_APP_ICO):
            return
        try:
            pil = Image.open(LOGO_APP_ICO).resize(
                (80, 80), Image.Resampling.LANCZOS
            )
            self.logo_img = ImageTk.PhotoImage(pil)
            tk.Label(parent, image=self.logo_img, bg="white").pack(
                side="left", padx=(0, 14)
            )
        except Exception:
            self.logo_img = None

    def _construir_cabecera(self):
        """Banda superior, todo agrupado a la izquierda y en un solo
        renglón consecutivo: logo corporativo (Los Balcanes S.A., más
        grande porque tiene texto propio que tiene que leerse) primero,
        después el logo + nombre de la app."""
        cabecera = tk.Frame(self.header_frame, bg="white")
        cabecera.pack(fill="x", side="top")

        interior = tk.Frame(cabecera, bg="white")
        interior.pack(fill="x", pady=(10, 8), padx=16)

        self._agregar_logo_header(interior)

        bloque_izq = tk.Frame(interior, bg="white")
        bloque_izq.pack(side="left")

        # --- Logo corporativo (Los Balcanes S.A. / Cía. Azucarera) ---
        self.img_logo_balcanes = None
        try:
            self.img_logo_balcanes = tk.PhotoImage(file=LOGO_BALCANES)
        except tk.TclError:
            pass

        if self.img_logo_balcanes is not None:
            tk.Label(bloque_izq, image=self.img_logo_balcanes, bg="white").pack(side="left", padx=(0, 14))
            # Filete vertical fino que separa "la empresa dueña" de "la app"
            tk.Frame(bloque_izq, bg="#DDDDDD", width=1).pack(side="left", fill="y", padx=(0, 14), pady=4)

        # --- Logo + nombre de la app (ambos opcionales; si falta el
        # PNG, se muestra solo el texto) ---
        self.img_logo = None
        try:
            self.img_logo = tk.PhotoImage(file=LOGO_HEADER)
        except tk.TclError:
            pass

        if self.img_logo is not None:
            tk.Label(bloque_izq, image=self.img_logo, bg="white").pack(side="left", padx=(0, 12))

        textos = tk.Frame(bloque_izq, bg="white")
        textos.pack(side="left")
        tk.Label(textos, text="Tags App", bg="white", fg=AZUL,
                 font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(textos, text="Ingenio La Florida — Gestión de Tags ISA-5.1",
                 bg="white", fg=GRIS, font=("Segoe UI", 9)).pack(anchor="w")

        # Filete ámbar de separación, en el color secundario del logo
        tk.Frame(cabecera, bg=AMBAR, height=3).pack(fill="x", side="bottom")

    def _build_ui(self):
        """Fase 3: tres vistas persistentes; solo una se muestra a la vez.

        Pantalla A reúne propuesta y recientes, Pantalla B captura los
        datos del instrumento y Pantalla C concentra la búsqueda completa.
        Los widgets se crean una vez para conservar el estado al navegar.
        """
        self._construir_navegacion_fase3()
        return

        pad = {"padx": 10, "pady": 6}

        self._construir_cabecera()

        titulo = ttk.Label(
            self.contenedor, text="Registro de Nuevo Instrumento",
            font=("Segoe UI", 14, "bold"), foreground=AZUL
        )
        titulo.pack(pady=(12, 4))

        subtitulo = ttk.Label(
            self.contenedor,
            text="Seleccione las opciones. El sistema arma el tag y evita duplicados automáticamente.",
            foreground=GRIS
        )
        subtitulo.pack(pady=(0, 10))

        # ---------------- Paso 1: selección ----------------
        frame_sel = ttk.LabelFrame(self.contenedor, text="Paso 1 - Ubicación y tipo de instrumento")
        frame_sel.pack(fill="x", **pad)

        ttk.Label(frame_sel, text="Área de la planta:").grid(row=0, column=0, sticky="w", **pad)
        self.cb_area = ttk.Combobox(frame_sel, values=list(self.areas.keys()), state="readonly", width=45)
        self.cb_area.grid(row=0, column=1, **pad)
        self._redirigir_scroll_combobox(self.cb_area)

        # "Variable del Proceso" (y no "Variable a medir") para evitar que
        # el operador la confunda con los actuadores.
        ttk.Label(frame_sel, text="Variable del Proceso:").grid(row=1, column=0, sticky="w", **pad)
        self.cb_variable = ttk.Combobox(frame_sel, values=list(self.variables.keys()), state="readonly", width=45)
        self.cb_variable.grid(row=1, column=1, **pad)
        self._redirigir_scroll_combobox(self.cb_variable)

        ttk.Label(frame_sel, text="Función del instrumento:").grid(row=2, column=0, sticky="w", **pad)
        self.cb_funcion = ttk.Combobox(frame_sel, values=list(self.funciones.keys()), state="readonly", width=45)
        self.cb_funcion.grid(row=2, column=1, **pad)
        self._redirigir_scroll_combobox(self.cb_funcion)

        # Autocompletado: en cuanto las 3 selecciones esten completas, se
        # consulta (solo lectura) y se propone el tag automaticamente, sin
        # necesidad de un boton adicional.
        self.cb_area.bind("<<ComboboxSelected>>", self.verificar_y_consultar)
        self.cb_variable.bind("<<ComboboxSelected>>", self.verificar_y_consultar)
        self.cb_funcion.bind("<<ComboboxSelected>>", self.verificar_y_consultar)

        ttk.Label(frame_sel, text="Asignación de lazo:").grid(row=3, column=0, sticky="w", **pad)
        frame_lazo = ttk.Frame(frame_sel)
        frame_lazo.grid(row=3, column=1, sticky="w", **pad)
        ttk.Radiobutton(
            frame_lazo, text="Nuevo lazo", variable=self.modo_lazo,
            value="nuevo", command=self._on_modo_lazo_cambio,
        ).pack(side="left")
        ttk.Radiobutton(
            frame_lazo, text="Lazo existente", variable=self.modo_lazo,
            value="existente", command=self._on_modo_lazo_cambio,
        ).pack(side="left", padx=(14, 0))

        ttk.Label(frame_sel, text="Lazo existente:").grid(row=4, column=0, sticky="w", **pad)
        self.cb_lazo = ttk.Combobox(frame_sel, state="disabled", width=45)
        self.cb_lazo.grid(row=4, column=1, **pad)
        self._redirigir_scroll_combobox(self.cb_lazo)
        self.cb_lazo.bind("<<ComboboxSelected>>", self.actualizar_propuesta)

        hint = ttk.Label(
            frame_sel,
            text="Nuevo lazo propone el próximo número libre; un lazo existente reutiliza su número ISA.",
            style="info.TLabel", font=("Segoe UI", 8, "italic")
        )
        hint.grid(row=5, column=0, columnspan=2, pady=(0, 6))

        # ---------------- Paso 2: resultado ----------------
        frame_result = ttk.LabelFrame(self.contenedor, text="Paso 2 - Tags existentes en esta categoría")
        frame_result.pack(fill="both", expand=False, **pad)

        self.lista_existentes = tk.Listbox(frame_result, height=6)
        self.lista_existentes.pack(fill="x", padx=10, pady=(8, 4))
        # Click en un tag existente -> autocompleta el Paso 3 y entra en
        # modo edición (Tarea de edición de tags).
        self.lista_existentes.bind("<<ListboxSelect>>", self.on_seleccionar_existente)

        # Contenedor para el Tag Propuesto y el botón de Copiar.
        frame_propuesta = ttk.Frame(frame_result)
        frame_propuesta.pack(pady=(4, 12))

        self.lbl_propuesta = ttk.Label(
            frame_propuesta,
            text="Tag propuesto: —",
            font=("Segoe UI", 18, "bold"),
            style="warning.TLabel",
            padding=(22, 10),
        )
        self.lbl_propuesta.pack(side="left", padx=(0, 10))

        self.btn_copiar = ttk.Button(
            frame_propuesta,
            text="📋 Copiar",
            command=self.on_copiar_propuesta,
            style="primary.TButton",
            padding=(16, 10),
        )
        self.btn_copiar.pack(side="left")

        ttk.Label(frame_propuesta, text="Editar:", style="secondary.TLabel",
                  font=("Segoe UI", 9)).pack(side="left", padx=(10, 4))
        self.entry_tag = ttk.Entry(frame_propuesta, width=22, font=("Segoe UI", 11))
        self.entry_tag.pack(side="left")

        # Botón para eliminar el tag seleccionado de la lista.
        btn_eliminar = ttk.Button(
            frame_propuesta,
            text="Eliminar tag seleccionado",
            command=self.on_eliminar,
            style="danger.Outline.TButton",
            width=28,
        )
        btn_eliminar.pack(side="right", padx=(10, 0))
        self.entry_tag.bind("<KeyRelease>", self._on_entry_tag_cambio)

        # Lectura humana del tag propuesto (Paso 2, debajo de "Tag propuesto").
        self.lbl_traduccion = ttk.Label(
            frame_result, text="",
            style="warning.TLabel",
            font=("Arial", 14, "bold"),
            padding=(20, 15),
            anchor="center",
        )
        self.lbl_traduccion.pack(anchor="center", fill="x", padx=16, pady=(4, 8))

        # ---------------- Paso 3: datos del instrumento ----------------
        frame_datos = ttk.LabelFrame(self.contenedor, text="Paso 3 - Datos del instrumento")
        frame_datos.pack(fill="x", **pad)

        # Alineación uniforme del formulario: las dos columnas de entrada
        # (1 y 3) se reparten el ancho disponible en partes iguales y TODOS
        # los campos usan sticky="ew" -- antes varios Combobox tenían un
        # width menor y sticky="w", así que sus bordes derechos no
        # coincidían con el resto de la fila.
        frame_datos.columnconfigure(1, weight=1)
        frame_datos.columnconfigure(3, weight=1)

        self.entries = {}
        campos = [
            ("descripcion", "Descripción del instrumento (OBLIGATORIO)"),
            ("ubicacion", "Ubicación física"),
            ("fabricante", "Fabricante"),
            ("modelo", "Modelo"),
            ("rango_medicion", "Rango de medición"),
            ("unidad", "Unidad de ingeniería"),
        ]
        for i, (key, label) in enumerate(campos):
            r, c = divmod(i, 2)
            ttk.Label(frame_datos, text=label + ":").grid(row=r, column=c * 2, sticky="w", padx=(10, 4), pady=4)
            entry = ttk.Entry(frame_datos, width=28)
            entry.grid(row=r, column=c * 2 + 1, sticky="ew", padx=(0, 10), pady=4)
            self.entries[key] = entry
            if key == "descripcion":
                self.entry_descripcion = entry

        # "Registrado por" = catálogo de usuarios (seleccionable + agregable),
        # en vez de un texto libre, para mantener consistencia de nombres.
        ttk.Label(frame_datos, text="Registrado por (usuario):").grid(row=3, column=0, sticky="w", padx=(10, 4), pady=4)
        self.cb_usuario = ttk.Combobox(frame_datos, state="readonly", width=25, values=self.usuarios)
        self.cb_usuario.grid(row=3, column=1, sticky="ew", padx=(0, 4), pady=4)
        self._redirigir_scroll_combobox(self.cb_usuario)
        self.btn_add_usuario = ttk.Button(frame_datos, text="➕", width=3, command=self.on_agregar_usuario)
        self.btn_add_usuario.grid(row=3, column=2, sticky="w", padx=(0, 10), pady=4)

        ttk.Label(frame_datos, text="Estado:").grid(row=4, column=0, sticky="w", padx=(10, 4), pady=4)
        self.cb_estado = ttk.Combobox(
            frame_datos, state="readonly", width=25,
            # "Retirado" agregado (28/08/2026): es el estado correcto para
            # dar de baja un tag conservando su numero y trazabilidad, en
            # vez de eliminarlo -- antes no se podia elegir desde la UI.
            values=["Planificado", "Instalado", "Fuera de Servicio", "Retirado"]
        )
        self.cb_estado.set("Planificado")
        self.cb_estado.grid(row=4, column=1, sticky="ew", padx=(0, 10), pady=4)
        self._redirigir_scroll_combobox(self.cb_estado)

        # Datatype real del PLC (opcional) -- meramente informativo: de ahí
        # ANTES se infería el Tipo de Señal, hoy es un control manual.
        ttk.Label(frame_datos, text="Datatype (PLC):").grid(row=4, column=2, sticky="w", padx=(10, 4), pady=4)
        self.cb_datatype = ttk.Combobox(
            frame_datos, width=20,
            values=["BOOL", "REAL", "INT", "DINT", "STRING"]
        )
        self.cb_datatype.grid(row=4, column=3, sticky="ew", padx=(0, 10), pady=4)
        self._redirigir_scroll_combobox(self.cb_datatype)

        # Tipo de Señal y Entrada/Salida (28/08/2026): antes se inferían
        # del datatype/alias del PLC al vuelo; ahora son CONTROLES
        # EXPLÍCITOS que el operador elige a mano y se guardan en columnas
        # propias de la tabla (tipo_senal / entrada_salida).
        ttk.Label(frame_datos, text="Tipo de Señal:").grid(row=5, column=0, sticky="w", padx=(10, 4), pady=4)
        self.cb_tipo_senal = ttk.Combobox(
            frame_datos, state="readonly", width=20,
            values=["Analógico", "Digital", "Desconocido"]
        )
        self.cb_tipo_senal.set("Desconocido")
        self.cb_tipo_senal.grid(row=5, column=1, sticky="ew", padx=(0, 10), pady=4)
        self._redirigir_scroll_combobox(self.cb_tipo_senal)

        ttk.Label(frame_datos, text="Entrada/Salida:").grid(row=5, column=2, sticky="w", padx=(10, 4), pady=4)
        self.cb_io = ttk.Combobox(
            frame_datos, state="readonly", width=20,
            values=["Entrada", "Salida", "Memoria / Red", "N/D"]
        )
        self.cb_io.set("N/D")
        self.cb_io.grid(row=5, column=3, sticky="ew", padx=(0, 10), pady=4)
        self._redirigir_scroll_combobox(self.cb_io)

        # Fluido/Producto (opcional, 28/08/2026): PURAMENTE INFORMATIVO --
        # nunca entra en tag_completo (el Manual de Estandarización
        # prohíbe nombres de material de proceso en el nombre del tag).
        # Editable (no readonly): la lista cubre los fluidos mas comunes
        # del Ingenio, pero no puede ser exhaustiva.
        ttk.Label(frame_datos, text="Fluido / Producto (informativo):").grid(row=6, column=0, sticky="w", padx=(10, 4), pady=4)
        self.cb_fluido = ttk.Combobox(
            frame_datos, width=28,
            values=["Alcohol 90°", "Alcohol 96°", "Alcohol 99°", "Agua pura",
                    "Agua común", "Flegmasa", "Vino", "CO2", "Vapor"]
        )
        self.cb_fluido.grid(row=6, column=1, sticky="ew", padx=(0, 10), pady=4)
        self._redirigir_scroll_combobox(self.cb_fluido)

        # ---------------- Paso 4: confirmar / actualizar ----------------
        self.btn_accion = ttk.Button(
            self.contenedor,
            text="✔  Confirmar y Guardar Tag",
            command=self.on_guardar,
            style="success.TButton",
            padding=(28, 10),
        )
        self.btn_accion.pack(pady=16)

        self.status = ttk.Label(self.contenedor, text="", style="success.TLabel")
        self.status.pack()

        self._build_grilla_general()

        # Después de construir TODO, la rueda del ratón desplaza la
        # página sobre cada widget que no tenga scroll propio (los que
        # sí lo tienen, Treeview/Listbox/Combobox, se excluyen).
        self._vincular_rueda()

    # ============================================================
    # Fase 3 — Arquitectura de navegación
    # ============================================================
    def _construir_navegacion_fase3(self):
        self._construir_cabecera()
        self._scrollbar.pack_forget()
        self.vistas = {}
        for nombre in ("inicio", "datos", "busqueda"):
            vista = ttk.Frame(self.contenedor, padding=16)
            self.vistas[nombre] = vista
        self.vista_inicio = self.vistas["inicio"]
        self.vista_datos = self.vistas["datos"]
        self.vista_busqueda = self.vistas["busqueda"]
        self._construir_pantalla_inicio()
        self._construir_pantalla_datos()
        self._construir_pantalla_busqueda()
        self.status = ttk.Label(self.contenedor, text="", style="success.TLabel")
        self.status.pack(side="bottom", fill="x", padx=16, pady=(0, 8))
        self.mostrar_vista("inicio")
        self.refrescar_tags_recientes()
        self.refrescar_paso5()

    def mostrar_vista(self, nombre):
        """Oculta la vista actual y muestra una sola pantalla persistente."""
        for vista in self.vistas.values():
            vista.pack_forget()
        self.vistas[nombre].pack(fill="both", expand=True)
        if nombre == "inicio":
            self.refrescar_tags_recientes()
        elif nombre == "busqueda":
            self.refrescar_paso5()

    def _construir_pantalla_inicio(self):
        vista = self.vista_inicio
        vista.columnconfigure(0, weight=3)
        vista.columnconfigure(1, weight=2)
        vista.rowconfigure(1, weight=1)
        encabezado = ttk.Frame(vista, padding=(8, 4, 8, 16))
        encabezado.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(encabezado, text="Registro de Nuevo Instrumento", font=("Segoe UI", 20, "bold")).pack(anchor="center")
        ttk.Label(encabezado, text="Ingenio La Florida - Gestión de Tags ISA-5.1", style="secondary.TLabel", font=("Segoe UI", 10)).pack(anchor="center", pady=(3, 0))
        izquierda = ttk.Labelframe(vista, text="Crear Nuevo Tag", padding=14)
        derecha = ttk.Labelframe(vista, text="Búsqueda Rápida", padding=14)
        izquierda.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        derecha.grid(row=1, column=1, sticky="nsew")
        izquierda.columnconfigure(1, weight=1)

        ttk.Label(izquierda, text="Área de la planta:").grid(row=0, column=0, sticky="w", pady=5)
        self.cb_area = ttk.Combobox(izquierda, values=list(self.areas), state="readonly")
        self.cb_area.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        ttk.Label(izquierda, text="Variable del Proceso:").grid(row=1, column=0, sticky="w", pady=5)
        self.cb_variable = ttk.Combobox(izquierda, values=list(self.variables), state="readonly")
        self.cb_variable.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=5)
        ttk.Label(izquierda, text="Función del instrumento:").grid(row=2, column=0, sticky="w", pady=5)
        self.cb_funcion = ttk.Combobox(izquierda, values=list(self.funciones), state="readonly")
        self.cb_funcion.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=5)
        for cb in (self.cb_area, self.cb_variable, self.cb_funcion):
            self._redirigir_scroll_combobox(cb)
            cb.bind("<<ComboboxSelected>>", self.verificar_y_consultar)

        ttk.Label(izquierda, text="Asignación de lazo:").grid(row=3, column=0, sticky="w", pady=5)
        modo = ttk.Frame(izquierda)
        modo.grid(row=3, column=1, sticky="w", padx=(10, 0), pady=5)
        ttk.Radiobutton(modo, text="Nuevo lazo", variable=self.modo_lazo, value="nuevo", command=self._on_modo_lazo_cambio).pack(side="left")
        ttk.Radiobutton(modo, text="Lazo existente", variable=self.modo_lazo, value="existente", command=self._on_modo_lazo_cambio).pack(side="left", padx=12)
        ttk.Label(izquierda, text="Lazo existente:").grid(row=4, column=0, sticky="w", pady=5)
        self.cb_lazo = ttk.Combobox(izquierda, state="disabled")
        self.cb_lazo.grid(row=4, column=1, sticky="ew", padx=(10, 0), pady=5)
        self.cb_lazo.bind("<<ComboboxSelected>>", self.actualizar_propuesta)
        self._redirigir_scroll_combobox(self.cb_lazo)

        ttk.Label(izquierda, text="Paso 2 — Tags existentes", style="info.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 4))
        self.lista_existentes = tk.Listbox(izquierda, height=7)
        self.lista_existentes.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.lista_existentes.bind("<<ListboxSelect>>", self.on_seleccionar_existente)
        propuesta = ttk.Frame(izquierda)
        propuesta.grid(row=7, column=0, columnspan=2, sticky="ew", pady=12)
        self.lbl_propuesta = ttk.Label(propuesta, text="Tag propuesto: —", style="warning.TLabel", font=("Segoe UI", 16, "bold"), padding=10)
        self.lbl_propuesta.pack(side="left", fill="x", expand=True)
        self.btn_copiar = ttk.Button(propuesta, text="📋 Copiar", command=self.on_copiar_propuesta, style="primary.TButton")
        self.btn_copiar.pack(side="left", padx=(8, 0))
        self.entry_tag = ttk.Entry(izquierda)
        self.entry_tag.grid(row=8, column=0, columnspan=2, sticky="ew")
        self.entry_tag.bind("<KeyRelease>", self._on_entry_tag_cambio)
        self.lbl_traduccion = ttk.Label(izquierda, text="", style="secondary.TLabel", wraplength=620)
        self.lbl_traduccion.grid(row=9, column=0, columnspan=2, sticky="ew", pady=8)
        acciones = ttk.Frame(izquierda)
        acciones.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(acciones, text="Eliminar tag seleccionado", command=self.on_eliminar, style="danger.Outline.TButton").pack(side="left")
        self.btn_siguiente = ttk.Button(acciones, text="SIGUIENTE →", command=self.ir_a_datos, style="success.TButton", state="disabled")
        self.btn_siguiente.pack(side="right")

        # Panel derecho: lista superior (40%) y detalle integrado inferior (60%).
        derecha.columnconfigure(0, weight=1)
        derecha.rowconfigure(2, weight=2)
        derecha.rowconfigure(4, weight=3)
        ttk.Label(derecha, text="Tags recientes", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        barra = ttk.Frame(derecha)
        barra.grid(row=1, column=0, sticky="ew", pady=8)
        self.entry_busqueda_rapida = ttk.Entry(barra)
        self.entry_busqueda_rapida.pack(side="left", fill="x", expand=True)
        self.entry_busqueda_rapida.bind("<Return>", lambda _e: self.abrir_busqueda_rapida())
        ttk.Button(barra, text="Buscar", command=self.abrir_busqueda_rapida, style="primary.TButton").pack(side="left", padx=(6, 0))
        self.tree_recientes = ttk.Treeview(derecha, columns=("tag", "estado", "fecha"), show="headings", height=8)
        for col, title, width in (("tag", "Tag", 230), ("estado", "Estado", 115), ("fecha", "Creado", 145)):
            self.tree_recientes.heading(col, text=title); self.tree_recientes.column(col, width=width, anchor="w")
        self.tree_recientes.grid(row=2, column=0, sticky="nsew")
        self.tree_recientes.bind("<<TreeviewSelect>>", self._detalle_reciente)
        ttk.Separator(derecha, orient="horizontal").grid(row=3, column=0, sticky="ew", pady=14)
        detalle = ttk.Frame(derecha)
        detalle.grid(row=4, column=0, sticky="nsew")
        detalle.columnconfigure(1, weight=1)
        ttk.Label(detalle, text="Detalle del tag seleccionado", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.detalle_placeholder = ttk.Label(detalle, text="Seleccione un tag de la lista para ver su detalle", style="secondary.TLabel", wraplength=450)
        self.detalle_placeholder.grid(row=1, column=0, columnspan=2, sticky="w", pady=8)
        self.detalle_vars = {clave: tk.StringVar(value="—") for clave in ("tag_completo", "descripcion", "estado", "ubicacion", "fabricante", "modelo", "rango_medicion", "unidad", "tipo_senal", "entrada_salida", "fluido_proceso", "creado_por", "fecha_creacion")}
        etiquetas = (("tag_completo", "Tag"), ("descripcion", "Descripción"), ("estado", "Estado"), ("ubicacion", "Ubicación física"), ("fabricante", "Fabricante"), ("modelo", "Modelo"), ("rango_medicion", "Rango"), ("unidad", "Unidad"), ("tipo_senal", "Tipo de Señal"), ("entrada_salida", "Entrada/Salida"), ("fluido_proceso", "Fluido/Product"), ("creado_por", "Registrado por"), ("fecha_creacion", "Fecha de creación"))
        for fila, (clave, titulo) in enumerate(etiquetas, start=2):
            ttk.Label(detalle, text=f"{titulo}:", style="secondary.TLabel").grid(row=fila, column=0, sticky="nw", padx=(0, 8), pady=1)
            ttk.Label(detalle, textvariable=self.detalle_vars[clave], wraplength=360).grid(row=fila, column=1, sticky="nw", pady=1)
        self.btn_editar_detalle = ttk.Button(detalle, text="Editar", command=self.editar_tag_detallado, style="primary.TButton", state="disabled")
        self.btn_editar_detalle.grid(row=len(etiquetas) + 2, column=1, sticky="e", pady=(10, 0))
        ttk.Button(derecha, text="EXPANDIR BÚSQUEDA", command=lambda: self.mostrar_vista("busqueda"), style="info.TButton").grid(row=5, column=0, sticky="ew", pady=(12, 0))

    def _construir_pantalla_datos(self):
        vista = self.vista_datos
        vista.columnconfigure(1, weight=1); vista.columnconfigure(3, weight=1)
        ttk.Label(vista, text="Datos del Instrumento", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=4, sticky="w")
        self.lbl_tag_datos = ttk.Label(vista, text="Tag: —", style="warning.TLabel", font=("Segoe UI", 18, "bold"), padding=12)
        self.lbl_tag_datos.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(10, 16))
        self.entries = {}
        campos = [("descripcion", "Descripción del instrumento *"), ("ubicacion", "Ubicación física"), ("fabricante", "Fabricante"), ("modelo", "Modelo"), ("rango_medicion", "Rango de medición"), ("unidad", "Unidad de ingeniería")]
        for i, (key, label) in enumerate(campos):
            r, c = divmod(i, 2); ttk.Label(vista, text=label).grid(row=2+r, column=c*2, sticky="w", pady=6)
            e = ttk.Entry(vista); e.grid(row=2+r, column=c*2+1, sticky="ew", padx=(8, 16), pady=6); self.entries[key] = e
        self.entry_descripcion = self.entries["descripcion"]
        ttk.Label(vista, text="Registrado por (usuario) *").grid(row=5, column=0, sticky="w", pady=6)
        self.cb_usuario = ttk.Combobox(vista, values=self.usuarios, state="readonly"); self.cb_usuario.grid(row=5, column=1, sticky="ew", padx=(8,16), pady=6)
        ttk.Button(vista, text="➕", command=self.on_agregar_usuario, width=3).grid(row=5, column=2, sticky="w")
        ttk.Label(vista, text="Estado").grid(row=6, column=0, sticky="w", pady=6)
        self.cb_estado = ttk.Combobox(vista, values=["Planificado", "Instalado", "Fuera de Servicio", "Retirado"], state="readonly"); self.cb_estado.set("Planificado"); self.cb_estado.grid(row=6, column=1, sticky="ew", padx=(8,16), pady=6)
        ttk.Label(vista, text="Tipo de Señal").grid(row=6, column=2, sticky="w", pady=6)
        self.cb_tipo_senal = ttk.Combobox(vista, values=["Analógico", "Digital", "Desconocido"], state="readonly"); self.cb_tipo_senal.set("Desconocido"); self.cb_tipo_senal.grid(row=6, column=3, sticky="ew", pady=6)
        ttk.Label(vista, text="Entrada/Salida").grid(row=7, column=0, sticky="w", pady=6)
        self.cb_io = ttk.Combobox(vista, values=["Entrada", "Salida", "Memoria / Red", "N/D"], state="readonly"); self.cb_io.set("N/D"); self.cb_io.grid(row=7, column=1, sticky="ew", padx=(8,16), pady=6)
        ttk.Label(vista, text="Fluido / Producto").grid(row=7, column=2, sticky="w", pady=6)
        self.cb_fluido = ttk.Combobox(vista, values=["Alcohol 90°", "Alcohol 96°", "Agua pura", "Vapor"]); self.cb_fluido.grid(row=7, column=3, sticky="ew", pady=6)
        self.cb_datatype = ttk.Combobox(vista, values=["BOOL", "REAL", "INT", "DINT", "STRING"])
        botones = ttk.Frame(vista); botones.grid(row=8, column=0, columnspan=4, sticky="ew", pady=24)
        ttk.Button(botones, text="← ATRÁS", command=lambda: self.mostrar_vista("inicio"), style="secondary.TButton").pack(side="left")
        self.btn_accion = ttk.Button(botones, text="GUARDAR TAG", command=self.on_guardar, style="success.TButton")
        self.btn_accion.pack(side="right")

    def _construir_pantalla_busqueda(self):
        vista = self.vista_busqueda; vista.rowconfigure(2, weight=1); vista.columnconfigure(0, weight=1)
        barra = ttk.Frame(vista); barra.grid(row=0, column=0, sticky="ew")
        ttk.Button(barra, text="← VOLVER", command=lambda: self.mostrar_vista("inicio"), style="secondary.TButton").pack(side="left")
        self.btn_exportar = ttk.Button(barra, text="Exportar a Excel", command=self.on_exportar_excel, style="success.TButton"); self.btn_exportar.pack(side="right")
        ttk.Label(vista, text="Búsqueda expandida", font=("Segoe UI", 18, "bold")).grid(row=1, column=0, sticky="w", pady=(16,6))
        buscar = ttk.Frame(vista); buscar.grid(row=2, column=0, sticky="nsew"); buscar.columnconfigure(0, weight=1); buscar.rowconfigure(1, weight=1)
        self.entry_buscar = ttk.Entry(buscar); self.entry_buscar.grid(row=0, column=0, sticky="ew", pady=(0,8)); self.entry_buscar.bind("<KeyRelease>", self._on_buscar_cambio)
        self.lbl_resultado_busqueda = ttk.Label(buscar, text="", style="secondary.TLabel"); self.lbl_resultado_busqueda.grid(row=0, column=1, padx=(10,0))
        columnas=("tag","estado","tipo_senal","io","fluido","fecha","descripcion")
        self.tree_tags=ttk.Treeview(buscar, columns=columnas, show="headings", selectmode="extended")
        for col,title,width in (("tag","Tag",150),("estado","Estado",110),("tipo_senal","Tipo de Señal",110),("io","Entrada/Salida",120),("fluido","Fluido/Product",130),("fecha","Fecha/Hora creación",150),("descripcion","Descripción/Alias",350)):
            self.tree_tags.heading(col,text=title); self.tree_tags.column(col,width=width,anchor="w")
        self.tree_tags.grid(row=1,column=0,columnspan=2,sticky="nsew"); self.tree_tags.bind("<Double-1>", self._on_grilla_doble_click); self.tree_tags.tag_configure("retirado", foreground=ROJO_PELIGRO)

    def ir_a_datos(self):
        if not self.tag_propuesto:
            return
        self.lbl_tag_datos.config(text=f"Tag propuesto: {self.tag_propuesto}")
        self.mostrar_vista("datos")

    def refrescar_tags_recientes(self):
        if not hasattr(self, "tree_recientes"): return
        self.tree_recientes.delete(*self.tree_recientes.get_children())
        for fila in db.buscar_tags("")[:10]:
            self.tree_recientes.insert("", tk.END, iid=fila["tag_completo"], values=(fila["tag_completo"], fila["estado"], fila["fecha_creacion"] or ""))

    def abrir_busqueda_rapida(self):
        texto = self.entry_busqueda_rapida.get().strip(); self.mostrar_vista("busqueda"); self.entry_buscar.delete(0,tk.END); self.entry_buscar.insert(0,text); self._refrescar_grilla_general(texto)

    def _detalle_reciente(self, _event=None):
        seleccion=self.tree_recientes.selection()
        if seleccion: self.mostrar_detalle_tag(seleccion[0])

    def mostrar_detalle_tag(self, tag_codigo):
        """Actualiza el detalle integrado del Inicio; nunca abre una ventana."""
        fila = db.obtener_tag_completo(tag_codigo)
        if fila is None:
            return
        self.tag_detallado = fila
        for clave, variable in self.detalle_vars.items():
            variable.set(fila[clave] or "—")
        self.detalle_placeholder.grid_remove()
        self.btn_editar_detalle.config(state="normal")

    def editar_tag_detallado(self):
        if getattr(self, "tag_detallado", None) is not None:
            self._abrir_edicion(self.tag_detallado)

    def _abrir_edicion(self, fila):
        self._entrar_modo_edicion(fila); self.lbl_tag_datos.config(text=f"Editando: {fila['tag_completo']}"); self.mostrar_vista("datos")

    def _build_grilla_general(self):
        """Paso 5 (28/08/2026, pedido de Ingeniería): buscador inteligente
        + grilla general de TODOS los tags de la base (no solo los de la
        categoría Área/Variable/Función seleccionada arriba, a diferencia
        del Listbox del Paso 2). Filtra en tiempo real por tag,
        descripción, alias o PLC de origen (db.buscar_tags)."""
        frame_grilla = ttk.LabelFrame(self.contenedor, text="Paso 5 - Buscar / consultar todos los tags")
        frame_grilla.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        # --- Barra de búsqueda, arriba de la grilla ---
        frame_buscar = ttk.Frame(frame_grilla)
        frame_buscar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(frame_buscar, text="🔎 Buscar (tag, descripción o alias):").pack(side="left")
        self.entry_buscar = ttk.Entry(frame_buscar, width=48)
        self.entry_buscar.pack(side="left", padx=(6, 0), fill="x", expand=True)
        # Filtro EN TIEMPO REAL: cada tecla vuelve a consultar. La base es
        # chica (cientos de tags), no miles -- no hace falta debounce.
        self.entry_buscar.bind("<KeyRelease>", self._on_buscar_cambio)

        self.lbl_resultado_busqueda = ttk.Label(frame_buscar, text="", style="secondary.TLabel")
        self.lbl_resultado_busqueda.pack(side="left", padx=(10, 0))

        self.btn_exportar = ttk.Button(
            frame_buscar,
            text="Exportar Excel",
            command=self.on_exportar_excel,
            style="success.TButton",
            padding=(14, 6),
        )
        self.btn_exportar.pack(side="right", padx=(10, 0))

        self.btn_recargar = ttk.Button(
            frame_buscar,
            text="🔄 Recargar",
            command=self._recargar_app,
            style="primary.TButton",
            padding=(12, 6),
        )
        self.btn_recargar.pack(side="right", padx=(10, 0))

        # --- Grilla (Treeview) ---
        columnas = ("tag", "estado", "tipo_senal", "io", "fluido", "fecha", "descripcion")
        frame_tree = ttk.Frame(frame_grilla)
        frame_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.tree_tags = ttk.Treeview(
            frame_tree, columns=columnas, show="headings", height=10,
            selectmode="extended",
        )
        self.tree_tags.bind("<Button-1>", lambda e: self.tree_tags.focus_set())
        self.tree_tags.bind("<Shift-Down>", lambda e: self._extender_seleccion("down"))
        self.tree_tags.bind("<Shift-Up>", lambda e: self._extender_seleccion("up"))
        encabezados = {
            "tag": ("Tag", 130), "estado": ("Estado", 110),
            "tipo_senal": ("Tipo de Señal", 100), "io": ("Entrada/Salida", 100),
            "fluido": ("Fluido/Producto", 110),
            "fecha": ("Fecha/Hora creación", 140),
            "descripcion": ("Descripción / Alias original", 340),
        }
        for col, (titulo, ancho) in encabezados.items():
            self.tree_tags.heading(col, text=titulo)
            self.tree_tags.column(col, width=ancho, anchor="w")

        scroll_y = ttk.Scrollbar(frame_tree, orient="vertical", command=self.tree_tags.yview)
        scroll_x = ttk.Scrollbar(frame_tree, orient="horizontal", command=self.tree_tags.xview)
        self.tree_tags.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.tree_tags.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        frame_tree.rowconfigure(0, weight=1)
        frame_tree.columnconfigure(0, weight=1)

        # Doble click en una fila -> reutiliza el flujo de edición ya
        # existente (mismo camino que hacer click en el Listbox del Paso 2).
        self.tree_tags.bind("<Double-1>", self._on_grilla_doble_click)

        # Fila en rojo para cualquier tag 'Retirado' -- pedido de
        # Ingeniería para que salte a la vista apenas la base entre en
        # uso cotidiano (hoy no hay ninguno vivo, pero el estilo ya
        # queda armado para cuando aparezca el primero).
        self.tree_tags.tag_configure("retirado", foreground=ROJO_PELIGRO)

        self._refrescar_grilla_general()

    def _recargar_grilla(self):
        self.tree_tags.delete(*self.tree_tags.get_children())
        self._refrescar_grilla_general(self.entry_buscar.get().strip())

    def refrescar_paso5(self):
        """Recarga por completo la grilla del Paso 5 desde la base."""
        self.tree_tags.delete(*self.tree_tags.get_children())
        filas = db.buscar_tags("")
        for f in filas:
            tipo_senal = f["tipo_senal"] or "Desconocido"
            entrada_salida = f["entrada_salida"] or "N/D"
            tags_fila = ("retirado",) if f["estado"] == "Retirado" else ()
            self.tree_tags.insert("", tk.END, iid=f["tag_completo"], values=(
                f["tag_completo"], f["estado"], tipo_senal, entrada_salida,
                f["fluido_proceso"] or "", f["fecha_creacion"] or "",
                f["descripcion"] or "",
            ), tags=tags_fila)
        self.lbl_resultado_busqueda.config(text=f"{len(filas)} tag(s) en total")

    def _recargar_app(self):
        db.init_db()
        self.areas = {f"{a['codigo']} - {a['nombre']}": a for a in db.listar_areas()}
        self.variables = {f"{v['letra']} - {v['nombre']}": v for v in db.listar_variables()}
        self.funciones = {f"{f['letra']} - {f['nombre']}": f for f in db.listar_funciones()}
        self.usuarios = [u["nombre"] for u in db.listar_usuarios()]
        self.cb_area["values"] = list(self.areas.keys())
        self.cb_variable["values"] = list(self.variables.keys())
        self.cb_funcion["values"] = list(self.funciones.keys())
        self.cb_usuario["values"] = self.usuarios
        self.cb_area.set("")
        self.cb_variable.set("")
        self.cb_funcion.set("")
        self.modo_lazo.set("nuevo")
        self.lazos_disponibles = {}
        self.cb_lazo.set("")
        self.cb_lazo["values"] = ()
        self.cb_lazo.config(state="disabled")
        self.cb_usuario.set("")
        self.cb_estado.set("Planificado")
        self.cb_datatype.set("")
        self.cb_tipo_senal.set("Desconocido")
        self.cb_io.set("N/D")
        self.cb_fluido.set("")
        for e in self.entries.values():
            e.delete(0, tk.END)
        self._set_entry_tag("")
        self.lbl_propuesta.config(text="Tag propuesto: —", style="warning.TLabel")
        self._actualizar_traduccion()
        self.lista_existentes.delete(0, tk.END)
        self.entry_buscar.delete(0, tk.END)
        self.refrescar_paso5()
        self.status.config(text="Aplicación recargada desde la base de datos.")

    def _on_buscar_cambio(self, event=None):
        self._refrescar_grilla_general(self.entry_buscar.get().strip())

    def _refrescar_grilla_general(self, texto=""):
        """SOLO LECTURA. Buscador multi-término inteligente: el texto se
        pasa a minúsculas y se separa en palabras; cada fila debe
        contener todas ellas (en cualquier orden y en cualquier
        columna) para quedar visible. La grilla se puebla desde la base
        solo la primera vez; los filtrados posteriores ocultan/muestran
        filas con detach()/reattach() sin re-consultar la base."""
        if not self.tree_tags.get_children():
            filas = db.buscar_tags("")
            for f in filas:
                tipo_senal = f["tipo_senal"] or "Desconocido"
                entrada_salida = f["entrada_salida"] or "N/D"
                tags_fila = ("retirado",) if f["estado"] == "Retirado" else ()
                self.tree_tags.insert("", tk.END, iid=f["tag_completo"], values=(
                    f["tag_completo"], f["estado"], tipo_senal, entrada_salida,
                    f["fluido_proceso"] or "",
                    f["fecha_creacion"] or "", f["descripcion"] or "",
                ), tags=tags_fila)

        terminos = texto.lower().split()
        for item in self.tree_tags.get_children():
            fila = " ".join(self.tree_tags.item(item, "values")).lower()
            if all(term in fila for term in terminos):
                self.tree_tags.reattach(item, "", "end")
            else:
                self.tree_tags.detach(item)
        total = len(self.tree_tags.get_children())
        self.lbl_resultado_busqueda.config(
            text=f"{total} tag(s)" if texto else f"{total} tag(s) en total"
        )

    def _on_grilla_doble_click(self, event=None):
        """Abre el detalle de un tag sin abandonar la búsqueda expandida."""
        seleccion = self.tree_tags.selection()
        if seleccion:
            self.mostrar_detalle_tag(seleccion[0])

    # ------------------------------------------------------------
    def verificar_y_consultar(self, event=None):
        """Disparado por <<ComboboxSelected>> de los 3 combobox. Si los tres
        campos ya tienen seleccion, dispara la consulta automaticamente."""
        # Cambiar la Area/Variable/Funcion cancela implicitamente cualquier
        # edicion en curso: se vuelve al flujo de alta de un tag nuevo.
        if self.tag_en_edicion:
            self._salir_modo_edicion()
        if self.cb_area.get() and self.cb_variable.get() and self.cb_funcion.get():
            self.actualizar_propuesta()

    def _set_entry_tag(self, texto):
        """Puebla el campo editable del tag (borra y reinserta)."""
        self.entry_tag.delete(0, tk.END)
        self.entry_tag.insert(0, texto)

    def _actualizar_traduccion(self):
        tag = self.entry_tag.get().strip() or (self.tag_propuesto or "")
        texto = traducir_tag_humano(tag, DICCIONARIOS) if tag else ""
        self.lbl_traduccion.config(text=texto.upper() if texto else "")

    def _on_entry_tag_cambio(self, event=None):
        self._actualizar_traduccion()

    def _on_modo_lazo_cambio(self):
        """Activa el selector de lazos existentes cuando corresponde."""
        estado = "readonly" if self.modo_lazo.get() == "existente" else "disabled"
        self.cb_lazo.config(state=estado)
        self.actualizar_propuesta()

    def _cargar_lazos_disponibles(self, area_id, variable_id):
        """Carga los lazos de Área + Variable para reutilizar su número."""
        filas = db.listar_lazos(area_id, variable_id)
        self.lazos_disponibles = {}
        for fila in filas:
            numero = fila["numero_loop"]
            etiqueta = f"{numero:03d} — {fila['instrumentos']}"
            self.lazos_disponibles[etiqueta] = numero
        self.cb_lazo["values"] = list(self.lazos_disponibles)
        if self.cb_lazo.get() not in self.lazos_disponibles:
            self.cb_lazo.set("")

    def _limpiar_propuesta_lazo(self, mensaje):
        self.tag_propuesto = None
        self.numero_propuesto = None
        self._set_entry_tag("")
        self.lbl_propuesta.config(text=mensaje, style="warning.TLabel")
        if hasattr(self, "btn_siguiente"):
            self.btn_siguiente.config(state="disabled")
        self._actualizar_traduccion()

    def actualizar_propuesta(self):
        """SOLO LECTURA: arma un tag para un lazo nuevo o seleccionado."""
        area_sel = self.cb_area.get()
        var_sel = self.cb_variable.get()
        fun_sel = self.cb_funcion.get()

        if not (area_sel and var_sel and fun_sel):
            return

        area = self.areas[area_sel]
        variable = self.variables[var_sel]
        funcion = self.funciones[fun_sel]
        self._cargar_lazos_disponibles(area["id"], variable["id"])

        try:
            if self.modo_lazo.get() == "existente":
                numero = self.lazos_disponibles.get(self.cb_lazo.get())
                if numero is None:
                    self._limpiar_propuesta_lazo("Tag propuesto: seleccione un lazo existente")
                    return
            else:
                numero = db.proponer_siguiente_numero_lazo(area["id"], variable["id"])
            tag_propuesto = db.construir_tag(
                area["id"], variable["id"], funcion["id"], numero
            )
        except ValueError as e:
            self._limpiar_propuesta_lazo("Tag propuesto: —")
            messagebox.showerror("Rango agotado", str(e))
            return

        self.tag_propuesto = tag_propuesto
        self.numero_propuesto = numero
        self._set_entry_tag(tag_propuesto)
        self.lbl_propuesta.config(text=f"Tag propuesto: {tag_propuesto}", style="warning.TLabel")
        if hasattr(self, "btn_siguiente"):
            self.btn_siguiente.config(state="normal")
        self.status.config(text=f"Tag propuesto: '{tag_propuesto}' (todavía no guardado).")
        self._actualizar_traduccion()

        if self.modo_lazo.get() == "existente":
            self._refrescar_lista_lazo(area["id"], variable["id"], numero)
        else:
            self._refrescar_lista_existentes(area["id"], variable["id"], funcion["id"])

    def _refrescar_lista_existentes(self, area_id, variable_id, funcion_id):
        """SOLO LECTURA: repuebla el Listbox con los tags ya existentes
        para la combinacion Area+Variable+Funcion dada."""
        existentes = db.obtener_tags_existentes(area_id, variable_id, funcion_id)
        self.lista_existentes.delete(0, tk.END)
        for t in existentes:
            self.lista_existentes.insert(
                tk.END, f"{t['tag_completo']}  —  {t['estado']}  —  {t['descripcion'] or ''}"
            )

    def _refrescar_lista_lazo(self, area_id, variable_id, numero_loop):
        """Muestra todos los instrumentos que ya integran el lazo elegido."""
        existentes = db.obtener_instrumentos_lazo(area_id, variable_id, numero_loop)
        self.lista_existentes.delete(0, tk.END)
        for t in existentes:
            self.lista_existentes.insert(
                tk.END, f"{t['tag_completo']}  —  {t['estado']}  —  {t['descripcion'] or ''}"
            )

    # ------------------------------------------------------------
    # Edición de tags existentes
    # ------------------------------------------------------------
    def on_seleccionar_existente(self, event=None):
        """Al hacer click en un tag de la lista (Paso 2), autocompleta el
        Paso 3 con sus datos actuales y activa el modo de edición."""
        seleccion = self.lista_existentes.curselection()
        if not seleccion:
            return
        texto_item = self.lista_existentes.get(seleccion[0])
        if texto_item.startswith("("):
            return  # mensaje de listado vacío, no un tag real

        tag_codigo = texto_item.split("  —  ")[0].strip()
        fila = db.obtener_tag_completo(tag_codigo)
        if fila is None:
            return

        self._entrar_modo_edicion(fila)
        self.lbl_tag_datos.config(text=f"Editando: {tag_codigo}")
        self.mostrar_vista("datos")
        self.refrescar_paso5()

    def _entrar_modo_edicion(self, fila):
        """Autocompleta el Paso 3 con los datos de `fila` (una fila de
        db.obtener_tag_completo) y convierte el botón principal en
        'Actualizar Tag Seleccionado'."""
        tag_completo = fila["tag_completo"]
        self.tag_en_edicion = tag_completo
        self.tag_propuesto = tag_completo
        self.numero_propuesto = fila["numero_loop"]

        self.entries["descripcion"].delete(0, tk.END)
        self.entries["descripcion"].insert(0, fila["descripcion"] or "")
        self.entries["ubicacion"].delete(0, tk.END)
        self.entries["ubicacion"].insert(0, fila["ubicacion"] or "")
        self.entries["fabricante"].delete(0, tk.END)
        self.entries["fabricante"].insert(0, fila["fabricante"] or "")
        self.entries["modelo"].delete(0, tk.END)
        self.entries["modelo"].insert(0, fila["modelo"] or "")
        self.entries["rango_medicion"].delete(0, tk.END)
        self.entries["rango_medicion"].insert(0, fila["rango_medicion"] or "")
        self.entries["unidad"].delete(0, tk.END)
        self.entries["unidad"].insert(0, fila["unidad"] or "")
        self.cb_usuario.set(fila["creado_por"] or "")
        self.cb_estado.set(fila["estado"] or "Planificado")
        try:
            self.cb_datatype.set(fila["datatype"] or "")
        except (IndexError, KeyError):
            self.cb_datatype.set("")  # filas viejas sin columna datatype
        try:
            self.cb_fluido.set(fila["fluido_proceso"] or "")
        except (IndexError, KeyError):
            self.cb_fluido.set("")  # filas viejas sin columna fluido_proceso
        try:
            self.cb_tipo_senal.set(fila["tipo_senal"] or "Desconocido")
        except (IndexError, KeyError):
            self.cb_tipo_senal.set("Desconocido")  # filas viejas sin columna tipo_senal
        try:
            self.cb_io.set(fila["entrada_salida"] or "N/D")
        except (IndexError, KeyError):
            self.cb_io.set("N/D")  # filas viejas sin columna entrada_salida

        # Bg distinto en modo edicion (celeste claro) para que se note a
        # simple vista que ya no esta proponiendo un tag nuevo.
        self.lbl_propuesta.config(text=f"Editando tag: {tag_completo}", style="info.TLabel")
        self.status.config(
            text=f"Editando '{tag_completo}'. Modifique los campos y presione 'Actualizar'."
        )

        self.btn_accion.config(
            text="✎  Actualizar Tag Seleccionado",
            command=self.on_actualizar,
            style="primary.TButton",
        )

    def _salir_modo_edicion(self):
        """Vuelve al flujo normal de alta de un tag nuevo."""
        self.tag_en_edicion = None
        self.btn_accion.config(
            text="✔  Confirmar y Guardar Tag",
            command=self.on_guardar,
            style="success.TButton",
        )
        # Restaura el look "propuesta" (ambar) del chip -- si el usuario
        # todavia no completo Area+Variable+Funcion, actualizar_propuesta()
        # no se va a disparar despues de esto, asi que hay que resetear
        # el chip aca tambien para no dejarlo con el celeste de edicion.
        self.lbl_propuesta.config(text="Tag propuesto: —", style="warning.TLabel")
        self._set_entry_tag("")
        self._actualizar_traduccion()

    def on_actualizar(self):
        """Actualiza los datos editables de un tag YA EXISTENTE. No crea
        un tag nuevo ni modifica su identidad ISA (tag, área, variable,
        función y número de lazo quedan intactos)."""
        if not self.tag_en_edicion:
            messagebox.showwarning(
                "Nada para actualizar",
                "Seleccione un tag de la lista (Paso 2) para editarlo."
            )
            return

        tag_completo = self.tag_en_edicion

        ubicacion = self.entries["ubicacion"].get().strip()
        fabricante = self.entries["fabricante"].get().strip()
        modelo = self.entries["modelo"].get().strip()
        rango_medicion = self.entries["rango_medicion"].get().strip()
        unidad = self.entries["unidad"].get().strip()
        creado_por = self.cb_usuario.get().strip()

        descripcion = self.entry_descripcion.get().strip()
        if not descripcion:
            messagebox.showerror(
                "Campo requerido",
                "La descripción del instrumento es obligatoria",
            )
            return

        confirmar = messagebox.askyesno(
            "Confirmar actualización",
            f"¿Confirma la actualización del tag '{tag_completo}'?\n\n"
            f"Descripción: {descripcion}\n"
            f"Estado: {self.cb_estado.get()}"
        )
        if not confirmar:
            return

        db.actualizar_tag(
            tag_completo=tag_completo,
            descripcion=descripcion,
            ubicacion=ubicacion,
            fabricante=fabricante,
            modelo=modelo,
            rango_medicion=rango_medicion,
            unidad=unidad,
            estado=self.cb_estado.get(),
            modificado_por=creado_por,
            datatype=self.cb_datatype.get().strip(),
            tipo_senal=self.cb_tipo_senal.get(),
            entrada_salida=self.cb_io.get(),
            fluido_proceso=self.cb_fluido.get().strip(),
        )

        self.status.config(text=f"Tag '{tag_completo}' actualizado correctamente.")
        messagebox.showinfo("Actualizado", f"El tag '{tag_completo}' fue actualizado exitosamente.")

        # Limpiar formulario, salir de modo edicion y proponer el
        # siguiente correlativo libre para la categoria actual (solo lectura).
        for e in self.entries.values():
            e.delete(0, tk.END)
        self.cb_estado.set("Planificado")
        self.cb_usuario.set("")
        self.cb_datatype.set("")
        self.cb_tipo_senal.set("Desconocido")
        self.cb_io.set("N/D")
        self.cb_fluido.set("")
        self._salir_modo_edicion()
        self.actualizar_propuesta()
        self.refrescar_paso5()

    def on_guardar(self):
        """UNICA funcion autorizada a escribir en la base de datos."""
        # Defensivo: on_guardar es siempre flujo de ALTA. Si por algun
        # motivo quedo un modo edicion activo, se descarta antes de crear.
        if self.tag_en_edicion:
            self._salir_modo_edicion()
        area_sel = self.cb_area.get()
        var_sel = self.cb_variable.get()
        fun_sel = self.cb_funcion.get()

        if not self.tag_propuesto:
            messagebox.showwarning(
                "Falta propuesta",
                "Seleccione Área, Variable y Función para que el sistema proponga un tag."
            )
            return

        if not (area_sel and var_sel and fun_sel):
            messagebox.showwarning("Faltan datos", "Seleccione Área, Variable y Función.")
            return

        area = self.areas[area_sel]
        variable = self.variables[var_sel]
        funcion = self.funciones[fun_sel]

        # --- Campos OPCIONALES del Paso 3 (para agilizar la carga en planta) ---
        # El operador puede dejarlos en blanco: NO se muestra advertencia y,
        # si quedan vacíos, se guardan como cadena vacía "" (la BD lo acepta
        # sin problema). Se aplica .strip() para no persistir espacios sueltos.
        ubicacion = self.entries["ubicacion"].get().strip()
        fabricante = self.entries["fabricante"].get().strip()
        modelo = self.entries["modelo"].get().strip()
        rango_medicion = self.entries["rango_medicion"].get().strip()
        unidad = self.entries["unidad"].get().strip()
        creado_por = self.cb_usuario.get().strip()
        if not creado_por:
            messagebox.showerror(
                "Usuario requerido",
                "Seleccione el usuario que registra el instrumento",
            )
            return

        descripcion = self.entry_descripcion.get().strip()
        if not descripcion:
            messagebox.showerror(
                "Campo requerido",
                "La descripción del instrumento es obligatoria",
            )
            return

        tag_a_guardar = self.entry_tag.get().strip() or self.tag_propuesto
        try:
            numero_a_guardar = int(tag_a_guardar.rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            numero_a_guardar = self.numero_propuesto

        confirmar = messagebox.askyesno(
            "Confirmar creación",
            f"¿Confirma la creación del tag '{tag_a_guardar}'?\n\n"
            f"Área: {area['nombre']}\n"
            f"Variable: {variable['nombre']}\n"
            f"Función: {funcion['nombre']}\n"
            f"Descripción: {descripcion}"
        )
        if not confirmar:
            return

        try:
            db.crear_tag(
                tag_completo=tag_a_guardar,
                area_id=area["id"],
                variable_id=variable["id"],
                funcion_id=funcion["id"],
                numero_loop=numero_a_guardar,
                descripcion=descripcion,
                ubicacion=ubicacion,
                fabricante=fabricante,
                modelo=modelo,
                rango_medicion=rango_medicion,
                unidad=unidad,
                estado=self.cb_estado.get(),
                creado_por=creado_por,
                datatype=self.cb_datatype.get().strip(),
                tipo_senal=self.cb_tipo_senal.get(),
                entrada_salida=self.cb_io.get(),
                fluido_proceso=self.cb_fluido.get().strip(),
            )
        except ValueError as e:
            messagebox.showerror("No se pudo guardar", str(e))
            return

        tag_guardado = tag_a_guardar
        self.status.config(text=f"Tag '{tag_guardado}' guardado correctamente.")
        messagebox.showinfo("Guardado", f"El tag '{tag_guardado}' fue registrado exitosamente.")

        # Limpiar formulario
        for e in self.entries.values():
            e.delete(0, tk.END)
        self.cb_estado.set("Planificado")
        self.cb_usuario.set("")
        self.cb_datatype.set("")
        self.cb_tipo_senal.set("Desconocido")
        self.cb_io.set("N/D")
        self.cb_fluido.set("")
        self.lbl_propuesta.config(text="Tag propuesto: —", style="warning.TLabel")

        # Refresca el Listbox, la búsqueda expandida y la lista de recientes.
        self.actualizar_propuesta()
        self.refrescar_paso5()
        self.refrescar_tags_recientes()
        self.mostrar_vista("inicio")

        faltantes, sugerencias = auditar_tag_recien_guardado(tag_guardado, db.buscar_tags(""))
        if faltantes:
            tag_sugerido = self._extraer_tag_faltante(faltantes[0])
            if tag_sugerido and messagebox.askyesno(
                "Asistente ISA-5.1",
                f"¿Desea precargar el siguiente componente obligatorio del lazo {tag_sugerido}?",
            ):
                self.precargar_tag_en_formulario(tag_sugerido)
        elif sugerencias:
            messagebox.showinfo(
                "Asistente ISA-5.1",
                "Recomendaciones:\n" + "\n".join(f"  • {s}" for s in sugerencias),
            )

    def _extraer_tag_faltante(self, texto):
        """Extrae el tag (entre paréntesis) de un faltante obligatorio."""
        ini = texto.rfind("(")
        if ini == -1:
            return None
        return texto[ini + 1:].rstrip(")").strip()

    def precargar_tag_en_formulario(self, tag_sugerido):
        """Carga un tag sugerido en el formulario para guardarlo."""
        partes = tag_sugerido.strip().split("_")
        if len(partes) != 3:
            return
        area_codigo, nucleo, lazo = partes
        variable_letra, funcion_letra = nucleo[0], nucleo[1:]

        area_key = next((k for k in self.areas if k.startswith(area_codigo + " - ")), None)
        var_key = next((k for k in self.variables if k.startswith(variable_letra + " - ")), None)
        fun_key = next((k for k in self.funciones if k.startswith(funcion_letra + " - ")), None)

        if area_key is not None:
            self.cb_area.set(area_key)
        if var_key is not None:
            self.cb_variable.set(var_key)
        if fun_key is not None:
            self.cb_funcion.set(fun_key)

        if area_key is not None and var_key is not None and fun_key is not None:
            # El asistente ISA propone completar un componente del MISMO
            # lazo: selecciona su número en vez de confiar en una edición
            # manual del texto del tag.
            self.modo_lazo.set("existente")
            self.cb_lazo.config(state="readonly")
            self.actualizar_propuesta()
            etiqueta = next(
                (texto for texto, numero in self.lazos_disponibles.items()
                 if numero == int(lazo)),
                None,
            )
            if etiqueta is not None:
                self.cb_lazo.set(etiqueta)
                self.actualizar_propuesta()
            else:
                self._set_entry_tag(tag_sugerido)
        else:
            self._set_entry_tag(tag_sugerido)
        self._actualizar_traduccion()
        self.entry_tag.focus_set()

    def on_agregar_usuario(self):
        """Agrega un usuario nuevo al catálogo desde la GUI y lo selecciona.
        El usuario queda persistido en la BD para las próximas cargas."""
        nombre = simpledialog.askstring(
            "Nuevo usuario", "Nombre del nuevo usuario:", parent=self
        )
        if nombre is None:
            return  # canceló
        nombre = nombre.strip()
        if not nombre:
            messagebox.showwarning("Nombre vacío", "El nombre del usuario no puede estar vacío.")
            return

        es_nuevo = db.agregar_usuario(nombre)
        self.usuarios = [u["nombre"] for u in db.listar_usuarios()]
        self.cb_usuario["values"] = self.usuarios
        self.cb_usuario.set(nombre)
        if es_nuevo:
            self.status.config(text=f"Usuario '{nombre}' agregado al catálogo.")
        else:
            self.status.config(text=f"El usuario '{nombre}' ya existía; fue seleccionado.")

    def on_copiar_propuesta(self):
        """Copia el tag recomendado sin interrumpir con un cuadro de diálogo."""
        if self.tag_propuesto:
            self.clipboard_clear()
            self.clipboard_append(self.tag_propuesto)
            
            # 1. Cambia temporalmente el texto del botón
            self.btn_copiar.config(text="✅ ¡Copiado!")
            
            # 2. Muestra la confirmación en la barra de estado inferior
            self.status.config(text=f"Tag '{self.tag_propuesto}' copiado al portapapeles.")
            
            # 3. Restaura el texto del botón automáticamente después de 2 segundos
            self.after(2000, lambda: self.btn_copiar.config(text="📋 Copiar al Portapapeles"))
        else:
            messagebox.showwarning("Sin propuesta", "Primero realice una consulta para generar un tag propuesto.")

    def on_exportar_excel(self):
        """Exporta los tags seleccionados del buscador (Paso 5) a un Excel."""
        from openpyxl import Workbook

        tags = self.tree_tags.selection()
        if not tags:
            messagebox.showwarning(
                "Exportación",
                "Seleccione al menos un tag en el buscador (Paso 5) para exportar.",
            )
            return

        conn = db.get_connection()
        placeholders = ",".join("?" * len(tags))
        cursor = conn.execute(
            f"""
            SELECT t.*, a.codigo AS area_codigo, a.nombre AS area_nombre
            FROM tags t JOIN areas a ON t.area_id = a.id
            WHERE t.tag_completo IN ({placeholders})
            """,
            list(tags),
        )
        columnas = [d[0] for d in cursor.description]
        filas = cursor.fetchall()
        conn.close()

        # Columna extra "Tag_Studio5000" (Allen-Bradley) junto a la del tag.
        idx_tag = columnas.index("tag_completo")
        columna_studio = "Tag_Studio5000"
        if columna_studio not in columnas:
            columnas.insert(idx_tag + 1, columna_studio)

        carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, f"tags_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")

        wb = Workbook()
        ws = wb.active
        ws.append(columnas)
        for fila in filas:
            studio = generar_tag_plc(fila["tag_completo"])
            valores = [fila[c] for c in columnas if c != columna_studio]
            valores.insert(idx_tag + 1, studio)
            ws.append(valores)
        wb.save(ruta)

        messagebox.showinfo("Exportación completada", f"{len(filas)} tags exportados")

    def _extender_seleccion(self, direccion):
        """Extiende la selección de la grilla (Shift-Up / Shift-Down)."""
        tv = self.tree_tags
        items = tv.get_children()
        if not items:
            return "break"
        sel = list(tv.selection())
        if not sel:
            return "break"
        base = tv.focus() if tv.focus() in items else sel[-1]
        idx = items.index(base)
        nidx = idx + 1 if direccion == "down" else idx - 1
        if nidx < 0 or nidx >= len(items):
            return "break"
        ini = items.index(sel[0])
        a, b = (ini, nidx) if ini < nidx else (nidx, ini)
        tv.selection_set(items[a:b + 1])
        tv.focus(items[nidx])
        tv.see(items[nidx])
        return "break"

    def on_eliminar(self):
        """Elimina DEFINITIVAMENTE el tag seleccionado en la lista de
        existentes. Doble confirmacion severa (28/08/2026, pedido de
        Ingenieria): esta accion ahora SI borra de verdad -- antes,
        eliminar_tag() tenia un bug (FK con la tabla auditoria sin
        capturar) que hacia que el boton fallara siempre en silencio para
        cualquier tag real. Ya arreglado (ver database.py), asi que la
        confirmacion tiene que estar a la altura del riesgo real."""
        seleccion = self.lista_existentes.curselection()
        if not seleccion:
            messagebox.showwarning("Selección requerida", "Seleccione un tag de la lista para eliminar.")
            return

        texto_item = self.lista_existentes.get(seleccion[0])
        if texto_item.startswith("("):
            return  # Es el mensaje de listado vacío

        # Extrae solo el código del tag (antes del guion largo)
        tag_codigo = texto_item.split("  —  ")[0].strip()

        confirmar = messagebox.askyesno(
            "⚠ Eliminar tag — acción irreversible",
            f"Está a punto de ELIMINAR PERMANENTEMENTE el tag '{tag_codigo}'.\n\n"
            "Esto borra el registro y todo su historial de auditoría de la "
            "base de datos. NO se puede deshacer.\n\n"
            "Si el instrumento ya no aplica pero quiere conservar el número "
            "y la trazabilidad, use 'Estado → Retirado' en vez de eliminar "
            "(Paso 3, edite el tag y guarde con ese estado).\n\n"
            "¿Confirma que quiere eliminarlo de todas formas?",
            icon="warning", default="no",
        )
        if not confirmar:
            return

        # Segunda confirmacion: una sola pregunta es insuficiente para una
        # accion irreversible sobre un registro de planta real.
        confirmar_final = messagebox.askyesno(
            "⚠ ÚLTIMA CONFIRMACIÓN",
            f"Última oportunidad para cancelar.\n\n"
            f"Se va a eliminar '{tag_codigo}' de forma DEFINITIVA e IRREVERSIBLE.\n\n"
            "¿Proceder?",
            icon="warning", default="no",
        )
        if not confirmar_final:
            return

        try:
            db.eliminar_tag(tag_codigo)
        except ValueError as e:
            messagebox.showerror("No se pudo eliminar", str(e))
            return

        self.status.config(text=f"Tag '{tag_codigo}' eliminado.")
        messagebox.showinfo("Eliminado", f"El tag '{tag_codigo}' fue eliminado exitosamente.")
        # Refresca la lista y actualiza la propuesta del siguiente número
        # (solo lectura)
        self.actualizar_propuesta()
        self.refrescar_paso5()

    def generar_esquema_lazo(self, lazo_id):
        """Visualiza el lazo de control: grafo dirigido Sensor->Controlador->Actuador."""
        import networkx as nx
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        partes = lazo_id.strip().split("_")
        try:
            if len(partes) != 3:
                raise ValueError
            area_codigo, variable_letra, numero_texto = partes
            if not area_codigo or not variable_letra:
                raise ValueError
            numero = int(numero_texto)
        except ValueError:
            messagebox.showerror(
                "Lazo inválido",
                f"'{lazo_id}' no es un identificador de lazo válido (ej. '200_P_002').",
            )
            return

        conn = db.get_connection()
        sql = """
            SELECT t.tag_completo, t.numero_loop, t.descripcion, t.estado,
                   a.codigo AS area_codigo, v.letra AS var_letra, f.letra AS fun_letra
            FROM tags t
            JOIN areas a ON t.area_id = a.id
            JOIN variables v ON t.variable_id = v.id
            JOIN funciones f ON t.funcion_id = f.id
            WHERE t.estado != 'Retirado' AND t.numero_loop = ?
              AND a.codigo = ? AND t.variable_id = ?
        """
        variable = conn.execute(
            "SELECT id FROM variables WHERE letra = ?", (variable_letra,)
        ).fetchone()
        if variable is None:
            conn.close()
            messagebox.showerror("Lazo inválido", f"Variable ISA desconocida: '{variable_letra}'.")
            return
        params = [numero, area_codigo, variable["id"]]
        sql += " ORDER BY t.tag_completo"
        filas = conn.execute(sql, params).fetchall()
        conn.close()

        if not filas:
            messagebox.showinfo("Lazo sin tags", f"No hay tags para el lazo '{lazo_id}'.")
            return

        sensores, controladores, actuadores, otros = [], [], [], []
        for fila in filas:
            fun = (fila["fun_letra"] or "").upper()
            if "IC" in fun:
                controladores.append(fila["tag_completo"])
            elif "T" in fun:
                sensores.append(fila["tag_completo"])
            elif "V" in fun:
                actuadores.append(fila["tag_completo"])
            else:
                otros.append(fila["tag_completo"])

        grafo = nx.DiGraph()
        for tag in sensores + controladores + actuadores + otros:
            grafo.add_node(tag)
        for s in sensores:
            for c in controladores:
                grafo.add_edge(s, c)
        for c in controladores:
            for a in actuadores:
                grafo.add_edge(c, a)
        if not controladores:
            for s in sensores:
                for a in actuadores:
                    grafo.add_edge(s, a)

        colores = {tag: "#1B8A3B" for tag in sensores}
        colores.update({tag: "#1F4E79" for tag in controladores})
        colores.update({tag: "#B00020" for tag in actuadores})
        colores.update({tag: "#999999" for tag in otros})

        ventana = tk.Toplevel(self)
        ventana.title(f"Esquema del lazo {lazo_id}")
        ventana.geometry("900x600")

        fig = Figure(figsize=(8.5, 5.5), dpi=100)
        ax = fig.add_subplot(111)
        pos = nx.spring_layout(grafo, seed=42)
        nx.draw_networkx_nodes(
            grafo, pos,
            node_color=[colores[n] for n in grafo.nodes],
            node_size=1800, ax=ax,
        )
        nx.draw_networkx_edges(
            grafo, pos,
            arrowstyle="-|>", arrowsize=16, width=1.6, ax=ax,
        )
        nx.draw_networkx_labels(grafo, pos, font_size=9, font_color="#FFFFFF", ax=ax)
        ax.set_title(
            f"Lazo {lazo_id}: {len(sensores)} sensor(es) -> "
            f"{len(controladores)} controlador(es) -> {len(actuadores)} actuador(es)"
        )
        ax.axis("off")

        lienzo = FigureCanvasTkAgg(fig, master=ventana)
        lienzo.draw()
        lienzo.get_tk_widget().pack(fill="both", expand=True)
        ttk.Button(ventana, text="Cerrar", command=ventana.destroy).pack(pady=6)

if __name__ == "__main__":
    app = TagGovernanceApp()
    app.mainloop()
