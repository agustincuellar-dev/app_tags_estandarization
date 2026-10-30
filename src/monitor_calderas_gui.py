"""Monitor de VTI/VTF — Calderas (interfaz).

Barre cada N segundos las RPM, corrientes y RTD de rodamientos y guarda
todo en SQLite. Exporta a CSV y XLSX.

    pythonw src/monitor_calderas_gui.py
"""

from __future__ import annotations

import datetime as dt
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import ttkbootstrap as tb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import monitor_calderas as mc  # noqa: E402

AZUL = "#002157"
AMBAR = "#FFBB02"
BASE = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    _REC = Path(getattr(sys, "_MEIPASS", BASE)) / "recursos"
    LOGO = _REC / "monitor.png"
    ICO = _REC / "monitor.ico"
else:
    LOGO = BASE / "monitor.png"
    ICO = BASE / "monitor.ico"

# Identidad fija de la aplicación: hace que el .exe, el acceso directo y la
# ventana abierta se agrupen como UNA sola aplicación en la barra de tareas.
# Sin esto, el .exe de un archivo (onefile) corre desde una carpeta temporal y
# la barra lo ve como un programa distinto del que se ancló.
APP_ID = "LaFlorida.MonitorVTI.Calderas"


def registrar_identidad():
    """Fija la identidad del proceso y deja constancia en el log de arranque."""
    try:
        import ctypes

        hr = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        leido = ctypes.c_wchar_p()
        ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(leido))
        linea = (f"{__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S} "
                 f"AUMID={leido.value!r} hr={hr:#x} empaquetado={getattr(sys, 'frozen', False)}")
        with open(mc.DATOS_DIR / "monitor_arranque.log", "a", encoding="utf-8") as fh:
            fh.write(linea + chr(10))
    except Exception as exc:
        try:
            with open(mc.DATOS_DIR / "monitor_arranque.log", "a", encoding="utf-8") as fh:
                fh.write(f"ERROR al fijar AUMID: {type(exc).__name__}: {exc}" + chr(10))
        except Exception:
            pass


class App(tb.Window):
    def __init__(self):
        super().__init__(title="Monitor VTI / VTF — Calderas", themename="darkly", size=(1270, 700))
        self.minsize(1100, 600)
        try:
            self.iconbitmap(str(ICO))
        except Exception:
            pass
        self.almacen = mc.Almacen()
        self.cola: queue.Queue = queue.Queue()
        self.hilo: threading.Thread | None = None
        self.parar = threading.Event()
        self.barridos = 0
        self.ultimo_barrido = 0.0

        self.style.configure("Accion.TButton", background=AMBAR, foreground=AZUL,
                             font=("Segoe UI", 10, "bold"), padding=(14, 8))
        self._construir()
        self._poblar_tabla()
        self.after(300, self._poll)
        self._actualizar_resumen()

    # ------------------------------------------------------------------
    def _construir(self):
        cab = tk.Frame(self, bg="white")
        cab.pack(fill="x")
        interior = tk.Frame(cab, bg="white")
        interior.pack(fill="x", padx=14, pady=8)
        try:
            from PIL import Image, ImageTk

            with Image.open(LOGO) as im:
                self._logo = ImageTk.PhotoImage(im.convert("RGBA").resize((52, 52), Image.Resampling.LANCZOS))
            tk.Label(interior, image=self._logo, bg="white").pack(side="left", padx=(0, 12))
        except Exception:
            pass
        textos = tk.Frame(interior, bg="white")
        textos.pack(side="left")
        tk.Label(textos, text="Monitor VTI / VTF", bg="white", fg=AZUL,
                 font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(textos, text="Calderas 8, 9 y 10 + caldera 11 — RPM, corriente y RTD",
                 bg="white", fg="#555555", font=("Segoe UI", 9)).pack(anchor="w")
        tk.Frame(cab, bg=AMBAR, height=3).pack(fill="x", side="bottom")

        controles = ttk.Frame(self, padding=(14, 10, 14, 4))
        controles.pack(fill="x")
        ttk.Label(controles, text="PLC calderas 8-9-10").grid(row=0, column=0, sticky="w")
        self.var_ip = tk.StringVar(value=mc.PLCS["calderas"])
        ttk.Entry(controles, textvariable=self.var_ip, width=15).grid(row=0, column=1, padx=(6, 14))
        ttk.Label(controles, text="PLC caldera 11").grid(row=0, column=2, sticky="w")
        self.var_ip11 = tk.StringVar(value=mc.PLCS["cald11"])
        ttk.Entry(controles, textvariable=self.var_ip11, width=15).grid(row=0, column=3, padx=(6, 14))
        ttk.Label(controles, text="Intervalo (s)").grid(row=0, column=4, sticky="w")
        self.var_intervalo = tk.StringVar(value=str(int(mc.INTERVALO_POR_DEFECTO)))
        ttk.Spinbox(controles, from_=2, to=3600, textvariable=self.var_intervalo, width=5).grid(
            row=0, column=5, padx=(6, 14))
        self.var_simulado = tk.BooleanVar(value=False)
        ttk.Checkbutton(controles, text="Simulado", variable=self.var_simulado).grid(
            row=0, column=6, padx=(0, 14))
        self.btn_iniciar = ttk.Button(controles, text="▶  Iniciar", style="Accion.TButton",
                                      command=self.iniciar)
        self.btn_iniciar.grid(row=0, column=7, padx=(0, 8))
        self.btn_detener = ttk.Button(controles, text="■  Detener", command=self.detener,
                                      state="disabled")
        self.btn_detener.grid(row=0, column=8, padx=(0, 18))
        ttk.Button(controles, text="Exportar CSV", command=lambda: self.exportar("csv")).grid(
            row=0, column=9, padx=(0, 6))
        ttk.Button(controles, text="Exportar XLSX", command=lambda: self.exportar("xlsx")).grid(
            row=0, column=10, padx=(0, 6))
        ttk.Button(controles, text="Abrir carpeta", command=self.abrir_carpeta).grid(row=0, column=11)

        vista = ttk.Frame(self, padding=(14, 4, 14, 2))
        vista.pack(fill="x")
        ttk.Label(vista, text="Ver").pack(side="left")
        self.var_vista = tk.StringVar(value="Activas")
        combo = ttk.Combobox(vista, textvariable=self.var_vista, width=12, state="readonly",
                             values=("Activas", "Archivadas", "Todas"))
        combo.pack(side="left", padx=(6, 14))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._poblar_tabla())
        self.btn_archivo = ttk.Button(vista, text="Archivar / Reactivar", command=self._alternar_archivo)
        self.btn_archivo.pack(side="left", padx=(0, 14))
        self.lbl_motivo = ttk.Label(vista, text="", style="secondary.TLabel")
        self.lbl_motivo.pack(side="left")

        marco = ttk.Frame(self, padding=(14, 6))
        marco.pack(fill="both", expand=True)
        cols = ("plc", "grupo", "senal", "descripcion", "valor", "unidad", "calidad", "hora")
        self.tabla = ttk.Treeview(marco, columns=cols, show="headings", height=18)
        for c, t, w, a in (("plc", "PLC", 120, "w"), ("grupo", "Grupo", 90, "w"),
                           ("senal", "Señal", 180, "w"), ("descripcion", "Descripción", 330, "w"),
                           ("valor", "Valor", 100, "e"), ("unidad", "Unidad", 60, "center"),
                           ("calidad", "Calidad", 110, "center"), ("hora", "Última lectura", 130, "center")):
            self.tabla.heading(c, text=t)
            self.tabla.column(c, width=w, anchor=a)
        self.tabla.tag_configure("error", foreground="#FF7B72")
        self.tabla.tag_configure("rtd", foreground="#79C0FF")
        self.tabla.tag_configure("archivada", foreground="#8B8B8B")
        self.tabla.bind("<<TreeviewSelect>>", lambda _e: self._mostrar_motivo())
        self.tabla.pack(fill="both", expand=True)

        pie = ttk.Frame(self, padding=(14, 4, 14, 10))
        pie.pack(fill="x")
        self.lbl_estado = ttk.Label(pie, text="Detenido.", style="secondary.TLabel")
        self.lbl_estado.pack(side="left")
        self.lbl_resumen = ttk.Label(pie, text="", style="secondary.TLabel")
        self.lbl_resumen.pack(side="right")

    def _poblar_tabla(self):
        self.tabla.delete(*self.tabla.get_children())
        vista = self.var_vista.get()
        for s in mc.senales_con_estado():
            if vista == "Activas" and s.archivada:
                continue
            if vista == "Archivadas" and not s.archivada:
                continue
            if s.archivada:
                valores = (s.nombre_plc, s.grupo, s.clave, s.descripcion, "—", s.unidad,
                           "ARCHIVADA", "no se lee")
                etiquetas = ("archivada",)
            else:
                valores = (s.nombre_plc, s.grupo, s.clave, s.descripcion, "—", s.unidad,
                           "sin datos", "")
                etiquetas = ("rtd",) if s.grupo == "RTD" else ()
            self.tabla.insert("", "end", iid=s.clave, values=valores, tags=etiquetas)

    def _senal_seleccionada(self):
        sel = self.tabla.selection()
        if not sel:
            return None
        return next((s for s in mc.senales_con_estado() if s.clave == sel[0]), None)

    def _mostrar_motivo(self):
        senal = self._senal_seleccionada()
        if senal is None:
            self.lbl_motivo.config(text="")
            return
        if senal.archivada:
            self.lbl_motivo.config(text=f"Archivada — {senal.motivo or 'sin lectura por ahora'}")
        else:
            self.lbl_motivo.config(text=f"Activa — {senal.nombre_plc}: {senal.tag}")

    def _alternar_archivo(self):
        senal = self._senal_seleccionada()
        if senal is None:
            messagebox.showinfo("Elegí una señal", "Seleccioná una fila de la tabla primero.")
            return
        nuevo_estado = not senal.archivada
        mc.fijar_archivada(senal.clave, nuevo_estado)
        accion = "archivada (deja de leerse y de guardarse)" if nuevo_estado else "reactivada"
        self.lbl_estado.config(text=f"{senal.clave} {accion}. Se aplica desde el próximo barrido.")
        self._poblar_tabla()
        self._mostrar_motivo()
        if self.hilo and self.hilo.is_alive():      # reinicia el barrido con la lista nueva
            self.detener()
            self.after(1200, self.iniciar)

    # ------------------------------------------------------------------
    def iniciar(self):
        if self.hilo and self.hilo.is_alive():
            return
        try:
            intervalo = max(2.0, float(self.var_intervalo.get()))
        except ValueError:
            messagebox.showerror("Intervalo inválido", "El intervalo debe ser un número de segundos.")
            return
        ip = self.var_ip.get().strip() or mc.PLCS["calderas"]
        ip11 = self.var_ip11.get().strip() or mc.PLCS["cald11"]
        fuente = (mc.FuenteSimulada() if self.var_simulado.get()
                  else mc.FuenteMultiple({"calderas": ip, "cald11": ip11}))
        self.parar = threading.Event()
        self.barridos = 0
        self.btn_iniciar.config(state="disabled")
        self.btn_detener.config(state="normal")
        self.lbl_estado.config(text=(f"Conectando con {ip} y {ip11}…"
                                     if not self.var_simulado.get() else "Iniciando en modo simulado…"))

        def trabajo():
            def aviso(n, lecturas):
                self.cola.put(("barrido", n, lecturas))
            try:
                mc.bucle_monitoreo(fuente, self.almacen, intervalo, None, self.parar, aviso)
            except Exception as exc:
                self.cola.put(("error", f"{type(exc).__name__}: {exc}", None))
            finally:
                self.cola.put(("fin", None, None))

        self.hilo = threading.Thread(target=trabajo, daemon=True)
        self.hilo.start()

    def detener(self):
        self.parar.set()
        self.lbl_estado.config(text="Deteniendo…")

    def _poll(self):
        try:
            while True:
                tipo, dato, lecturas = self.cola.get_nowait()
                if tipo == "barrido":
                    self._aplicar_barrido(dato, lecturas)
                elif tipo == "error":
                    self.lbl_estado.config(text=f"Error: {dato}")
                    messagebox.showerror("Error de comunicación", dato)
                elif tipo == "fin":
                    self.btn_iniciar.config(state="normal")
                    self.btn_detener.config(state="disabled")
                    self.lbl_estado.config(text=f"Detenido. {self.barridos} barridos guardados.")
                    self._actualizar_resumen()
        except queue.Empty:
            pass
        if self.hilo and self.hilo.is_alive():
            transcurrido = time.time() - self.ultimo_barrido
            self.lbl_estado.config(text=f"Monitoreando… {self.barridos} barridos · "
                                        f"último hace {transcurrido:.0f} s")
        self.after(400, self._poll)

    def _aplicar_barrido(self, n, lecturas):
        self.barridos = n
        self.ultimo_barrido = time.time()
        for l in lecturas:
            calidad = l["calidad"]
            valor = "—" if l["valor"] is None else (f"{l['valor']:.1f}" if l["grupo"] != "RTD"
                                                    else f"{l['valor']:.2f}")
            if calidad == "SIN_CABLEAR":
                etiquetas = ("sin_cablear",)
            elif calidad != "OK":
                etiquetas = ("error",)
            else:
                etiquetas = ("rtd",) if l["grupo"] == "RTD" else ()
            if self.tabla.exists(l["clave"]):
                senal = next((s for s in mc.SENALES if s.clave == l["clave"]), None)
                nombre_plc = senal.nombre_plc if senal else l.get("plc", "")
                self.tabla.item(l["clave"], values=(nombre_plc, l["grupo"], l["clave"],
                                                    l["descripcion"], valor, l["unidad"], calidad,
                                                    dt.datetime.now().strftime("%H:%M:%S")),
                                tags=etiquetas)
        self._actualizar_resumen()

    def _actualizar_resumen(self):
        total, primero, ultimo, barridos = self.almacen.resumen()
        self.lbl_resumen.config(text=f"Base: {total:,} filas · {barridos} instantes · "
                                     f"desde {primero or '—'}")

    def exportar(self, formato):
        try:
            if formato == "csv":
                ruta, n = mc.exportar_csv(self.almacen)
            else:
                ruta, n = mc.exportar_xlsx(self.almacen)
        except Exception as exc:
            messagebox.showerror("No se pudo exportar", f"{type(exc).__name__}: {exc}")
            return
        if n == 0:
            messagebox.showinfo("Sin datos", "Todavía no hay lecturas guardadas.")
            return
        self.lbl_estado.config(text=f"Exportado: {ruta.name} ({n} filas)")
        messagebox.showinfo("Exportado", f"{n} filas exportadas a:\n{ruta}")

    def abrir_carpeta(self):
        mc.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(mc.EXPORT_DIR)
        except Exception:
            subprocess.Popen(["explorer", str(mc.EXPORT_DIR)])


def _una_sola_instancia():
    """Un solo proceso por base: dos instancias duplicarían cada barrido."""
    import msvcrt

    ruta = mc.DATOS_DIR / "monitor.lock"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fh = open(ruta, "a+")
    fh.seek(0)
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return fh          # el bloqueo se libera solo al terminar el proceso
    except OSError:
        fh.close()
        return None


def main():
    registrar_identidad()
    cerrojo = _una_sola_instancia()
    if cerrojo is None:
        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showwarning("Monitor VTI / VTF",
                               "El monitor ya está abierto.\n\n"
                               "Cerrá esa ventana antes de abrir otra: dos ventanas "
                               "guardarían cada barrido dos veces en la misma base.")
        raiz.destroy()
        return
    app = App()
    if "--manual" not in sys.argv:      # desde el .exe o el acceso directo, arranca solo
        app.after(400, app.iniciar)
    if "--minimizado" in sys.argv:      # arranca guardado en la barra (uso al iniciar sesión)
        app.after(1500, app.iconify)
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        try:
            mc.DATOS_DIR.mkdir(parents=True, exist_ok=True)
            (mc.DATOS_DIR / "monitor_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise
