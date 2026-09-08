"""
md_a_pdf_gui.pyw
================
Interfaz grafica (GUI) para el conversor Markdown -> PDF del proyecto
(reutiliza el motor `md_a_pdf.py`, que corre sobre reportlab, sin
dependencias extra ni conexion a internet).

Uso:
    Doble clic sobre Abrir_Conversor_MD_PDF.bat
    (o: pythonw md_a_pdf_gui.pyw)

Flujo guiado en pantalla:
    1) Elegir el archivo .md desde el explorador.
    2) Confirmar (o cambiar) donde se guarda el PDF.
    3) Clic en "CONVERTIR A PDF".
    4) Abrir el PDF o su carpeta con un clic.
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import ttkbootstrap as tb  # Window + Style (solo si esta instalado)
    _TEMA = True
except Exception:  # pragma: no cover - PC sin ttkbootstrap
    tb = None
    _TEMA = False

# El motor de conversion vive al lado de esta GUI (src/md_a_pdf.py).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md_a_pdf  # noqa: E402

VERDE = "#1D6F42"
ROJO = "#E06C75"
GRIS = "#9AA4B0"
AZUL = "#0D6EFD"

TIPOS_MD = [("Markdown", "*.md *.markdown"), ("Todos los archivos", "*.*")]

# Tipo de texto -> (fuente, color, estilo ttkbootstrap)
_FUENTES = {
    "titulo": ("Segoe UI", 17, "bold"),
    "subtitulo": ("Segoe UI", 10),
    "ayuda": ("Segoe UI", 8),
    "pie": ("Segoe UI", 8),
    "estado": ("Segoe UI", 10, "bold"),
}
_COLORES = {
    "info": GRIS,
    "ok": VERDE,
    "error": ROJO,
    "normal": None,  # color por defecto del tema
}


class App:
    def __init__(self):
        if _TEMA:
            self.root = tb.Window(
                title="Conversor MD -> PDF",
                themename="darkly",
                size=(680, 470),
                resizable=(False, False),
            )
            self.app_style = tb.Style()
        else:  # pragma: no cover - respaldo sin ttkbootstrap
            self.root = tk.Tk()
            self.root.title("Conversor MD -> PDF")
            self.root.geometry("680x470")
            self.root.configure(bg="#222222")
            self.root.resizable(False, False)
            self.app_style = None

        self.root.minsize(640, 440)

        self.var_origen = tk.StringVar()
        self.var_destino = tk.StringVar()
        self._destino_manual = False
        self._pdf_generado = None

        self._preparar_estilos()
        self._construir()
        self._marcar_estado("info", "Listo. Elija un archivo .md para comenzar.")
        self._actualizar_estado_botones()

    # ------------------------------------------------------------------
    # Textos con fuente/color: patrón comprobado de app_tags.py
    # (ttk no acepta font= en Tk pelado, pero sí bajo ttkbootstrap;
    #  en el respaldo sin ttkbootstrap se usa tk.Label clasico).
    # ------------------------------------------------------------------
    def _preparar_estilos(self):
        if not _TEMA:
            return
        for tipo, fuente in _FUENTES.items():
            self.app_style.configure(
                f"TxTipo.{tipo}.TLabel", font=fuente,
            )
        for estado, color in _COLORES.items():
            if color is not None:
                self.app_style.configure(
                    f"TxEstado.{estado}.TLabel", foreground=color,
                    font=_FUENTES["estado"],
                )
        self.app_style.configure(
            "TxEstado.info.TLabel", foreground=GRIS, font=_FUENTES["estado"],
        )
        self.app_style.configure("TxSubtitulo.TLabel", foreground=GRIS)
        self.app_style.configure("TxAyuda.TLabel", foreground=GRIS)
        self.app_style.configure("TxPie.TLabel", foreground=GRIS)

    def _texto(self, master, texto, tipo="normal", color="normal", wrap=0):
        """Crea un label de texto con fuente/color sin depender de ttk font=."""
        fuente = _FUENTES.get(tipo, _FUENTES["subtitulo"])
        if _TEMA:
            estilo = f"TxTipo.{tipo}.TLabel" if color == "normal" else f"TxEstado.{color}.TLabel"
            kw = dict(text=texto, style=estilo)
            if wrap:
                kw["wraplength"] = wrap
            return ttk.Label(master, **kw)
        # Respaldo: tk.Label acepta font/color directamente.
        fg = _COLORES.get(color)
        kw = dict(text=texto, font=fuente, bg=self.root.cget("bg"))
        if fg:
            kw["fg"] = fg
        if wrap:
            kw["wraplength"] = wrap
        return tk.Label(master, **kw)

    # ------------------------------------------------------------------
    # Construcción de la interfaz
    # ------------------------------------------------------------------
    def _construir(self):
        cont = ttk.Frame(self.root, padding=22)
        cont.pack(fill="both", expand=True)

        # --- Encabezado -------------------------------------------------
        self._texto(cont, "📄 Conversor de Markdown a PDF", "titulo").pack(anchor="w")
        self._texto(cont, "Elija un archivo .md y conviértalo a PDF en un clic.",
                    "subtitulo").pack(anchor="w", pady=(2, 14))

        # --- Paso 1: archivo de origen ----------------------------------
        origen = ttk.Labelframe(cont, text="1 · Archivo Markdown de origen", padding=12)
        origen.pack(fill="x")
        fila = ttk.Frame(origen)
        fila.pack(fill="x")
        self.entry_origen = ttk.Entry(fila, textvariable=self.var_origen, state="readonly")
        self.entry_origen.pack(side="left", fill="x", expand=True)
        ttk.Button(fila, text="📂 Examinar…", command=self.elegir_archivo,
                   style="primary.TButton" if _TEMA else "TButton",
                   padding=(14, 6)).pack(side="left", padx=(8, 0))
        self._texto(origen, "Formatos aceptados: .md y .markdown", "ayuda").pack(
            anchor="w", pady=(6, 0))

        # --- Paso 2: destino ---------------------------------------------
        destino = ttk.Labelframe(cont, text="2 · Dónde guardar el PDF", padding=12)
        destino.pack(fill="x", pady=(12, 0))
        fila2 = ttk.Frame(destino)
        fila2.pack(fill="x")
        self.entry_destino = ttk.Entry(fila2, textvariable=self.var_destino, state="readonly")
        self.entry_destino.pack(side="left", fill="x", expand=True)
        self.btn_cambiar = ttk.Button(fila2, text="📁 Cambiar…", command=self.elegir_destino,
                                      padding=(10, 6))
        self.btn_cambiar.pack(side="left", padx=(8, 0))
        self.btn_restaurar = ttk.Button(fila2, text="↺", command=self.restaurar_destino,
                                        width=3, padding=(4, 6), state="disabled")
        self.btn_restaurar.pack(side="left", padx=(6, 0))
        self._texto(destino,
                    "Por defecto se guarda en la misma carpeta que el .md, con el mismo nombre.",
                    "ayuda").pack(anchor="w", pady=(6, 0))

        # --- Acción principal ---------------------------------------------
        accion = ttk.Frame(cont)
        accion.pack(fill="x", pady=(18, 0))
        self.btn_convertir = ttk.Button(
            accion, text="🔄  CONVERTIR A PDF", command=self.iniciar_conversion,
            style="success.TButton" if _TEMA else "TButton", padding=(26, 12),
        )
        self.btn_convertir.pack(side="left")

        self.progreso = ttk.Progressbar(accion, mode="indeterminate", length=260)
        self.progreso.pack(side="left", fill="x", expand=True, padx=(16, 0))

        # --- Estado / resultado -------------------------------------------
        self.lbl_estado = self._texto(cont, "", "estado", color="info", wrap=620)
        self.lbl_estado.pack(fill="x", pady=(14, 4))

        resultado = ttk.Frame(cont)
        resultado.pack(fill="x", pady=(4, 0))
        self.btn_abrir_pdf = ttk.Button(resultado, text="👁  Abrir el PDF",
                                        command=self.abrir_pdf, state="disabled",
                                        style="primary.TButton" if _TEMA else "TButton",
                                        padding=(12, 6))
        self.btn_abrir_pdf.pack(side="left")
        self.btn_abrir_carpeta = ttk.Button(resultado, text="📂  Abrir carpeta",
                                            command=self.abrir_carpeta, state="disabled",
                                            padding=(12, 6))
        self.btn_abrir_carpeta.pack(side="left", padx=(8, 0))

        self._texto(cont, "Conversor sin conexión (reportlab) — listo para usar en el Ingenio.",
                    "pie").pack(side="bottom", anchor="w", pady=(10, 0))

    # ------------------------------------------------------------------
    # Selección de archivos
    # ------------------------------------------------------------------
    def elegir_archivo(self):
        ruta = filedialog.askopenfilename(
            title="Seleccione el archivo Markdown",
            filetypes=TIPOS_MD,
        )
        if not ruta:
            return
        self.var_origen.set(ruta)
        if not self._destino_manual:
            self.var_destino.set(self._destino_por_defecto(ruta))
        self._actualizar_estado_botones()
        self._marcar_estado("info", "Archivo elegido. Presione CONVERTIR A PDF para continuar.")

    def elegir_destino(self):
        if not self.var_origen.get():
            messagebox.showinfo("Primero elija el .md",
                                "Seleccione primero el archivo Markdown de origen.",
                                parent=self.root)
            return
        ruta = filedialog.asksaveasfilename(
            title="Guardar PDF como…",
            defaultextension=".pdf",
            initialdir=os.path.dirname(self.var_destino.get() or self.var_origen.get()),
            initialfile=os.path.basename(self.var_destino.get() or ""),
            filetypes=[("PDF", "*.pdf")],
        )
        if not ruta:
            return
        self.var_destino.set(ruta)
        self._destino_manual = True
        self.btn_restaurar.config(state="normal")

    def restaurar_destino(self):
        """Vuelve a poner el destino automático junto al .md."""
        if not self.var_origen.get():
            return
        self.var_destino.set(self._destino_por_defecto(self.var_origen.get()))
        self._destino_manual = False
        self.btn_restaurar.config(state="disabled")

    @staticmethod
    def _destino_por_defecto(path_md):
        return os.path.splitext(path_md)[0] + ".pdf"

    # ------------------------------------------------------------------
    # Conversión
    # ------------------------------------------------------------------
    def _actualizar_estado_botones(self):
        hay_origen = bool(self.var_origen.get())
        self.btn_convertir.config(state="normal" if hay_origen else "disabled")
        self.btn_cambiar.config(state="normal" if hay_origen else "disabled")

    def iniciar_conversion(self):
        origen = self.var_origen.get().strip()
        destino = self.var_destino.get().strip()

        if not origen or not os.path.isfile(origen):
            messagebox.showerror("Archivo no encontrado",
                                 "El archivo Markdown elegido ya no existe.\n"
                                 "Vuélvalo a seleccionar con «Examinar…».",
                                 parent=self.root)
            return
        if not destino:
            destino = self._destino_por_defecto(origen)
            self.var_destino.set(destino)
        if os.path.exists(destino) and not messagebox.askyesno(
                "El PDF ya existe",
                f"Ya existe:\n{destino}\n\n¿Desea reemplazarlo?",
                parent=self.root):
            return

        self._pdf_generado = None
        self._resultado_hilo = None
        self.btn_convertir.config(state="disabled")
        self.progreso.start(12)
        self._marcar_estado("info", "Convirtiendo… esto suele tardar unos segundos.")
        self.btn_abrir_pdf.config(state="disabled")
        self.btn_abrir_carpeta.config(state="disabled")

        threading.Thread(target=self._tarea_conversion, args=(origen, destino),
                         daemon=True).start()
        # Tk solo se toca desde el hilo principal: la UI sondea el resultado.
        self.root.after(100, self._vigilar_hilo)

    def _tarea_conversion(self, origen, destino):
        try:
            ruta = md_a_pdf.convertir(origen, destino)
            ok, mensaje, detalle = True, ruta, None
        except Exception as error:  # noqa: BLE001 - se reporta en la UI
            import traceback
            ok, mensaje, detalle = False, "", traceback.format_exc()
        self._resultado_hilo = (ok, mensaje, detalle)

    def _vigilar_hilo(self):
        """Sondeo desde el hilo principal hasta que el worker termina."""
        if self._resultado_hilo is None:
            self.root.after(100, self._vigilar_hilo)
            return
        self._fin_conversion(*self._resultado_hilo)

    def _fin_conversion(self, ok, mensaje, detalle):
        self.progreso.stop()
        self._actualizar_estado_botones()
        if ok:
            self._pdf_generado = mensaje
            self._marcar_estado("ok", f"✅  PDF generado correctamente:\n{mensaje}")
            self.btn_abrir_pdf.config(state="normal")
            self.btn_abrir_carpeta.config(state="normal")
            messagebox.showinfo("Conversión exitosa",
                                f"PDF generado:\n{mensaje}\n\n"
                                "Puede abrirlo con el botón «Abrir el PDF».",
                                parent=self.root)
        else:
            self._marcar_estado("error",
                                "❌  No se pudo generar el PDF. Revise que el archivo .md "
                                "tenga el formato esperado.")
            messagebox.showerror("Error al convertir",
                                 "Ocurrió un error al generar el PDF.\n\n"
                                 f"{detalle}",
                                 parent=self.root)

    def _marcar_estado(self, color, texto):
        """Cambia el texto y color del estado (info/ok/error)."""
        self.lbl_estado.config(text=texto)
        if _TEMA:
            self.lbl_estado.config(style=f"TxEstado.{color}.TLabel")

    # ------------------------------------------------------------------
    # Acciones post-conversión
    # ------------------------------------------------------------------
    def abrir_pdf(self):
        if self._pdf_generado and os.path.isfile(self._pdf_generado):
            os.startfile(self._pdf_generado)  # noqa: S606 - visor PDF por defecto

    def abrir_carpeta(self):
        if self._pdf_generado:
            carpeta = os.path.dirname(self._pdf_generado)
            if os.path.isdir(carpeta):
                os.startfile(carpeta)  # noqa: S606


def main():
    App().root.mainloop()


if __name__ == "__main__":
    main()
