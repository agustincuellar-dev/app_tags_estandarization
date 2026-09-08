@echo off
rem ============================================================
rem  Abre la interfaz grafica del Conversor Markdown -> PDF
rem  (usa pythonw: no aparece la ventana de consola)
rem ============================================================
set "PY=C:\Users\Administrador\AppData\Local\Programs\Python\Python313\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"

start "" "%PY%" "%~dp0md_a_pdf_gui.pyw"
