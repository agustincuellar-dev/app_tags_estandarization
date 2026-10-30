@echo off
rem ============================================================
rem  Abre el Monitor de VTI / VTF de Calderas
rem  (usa pythonw: no aparece la ventana de consola)
rem ============================================================
set "PY=C:\Users\Administrador\AppData\Local\Programs\Python\Python313\pythonw.exe"
start "" "%PY%" "%~dp0monitor_calderas_gui.py"
