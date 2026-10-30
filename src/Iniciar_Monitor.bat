@echo off
rem ============================================================
rem  Inicia el monitor de VTI/VTF y deja el barrido andando
rem  cada 30 s, guardando en datos\monitor_calderas.db
rem ============================================================
set "PY=C:\Users\Administrador\AppData\Local\Programs\Python\Python313\pythonw.exe"
start "" "%PY%" "%~dp0Iniciar_Monitor.pyw"
