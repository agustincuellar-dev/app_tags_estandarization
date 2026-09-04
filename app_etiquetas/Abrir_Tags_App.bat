@echo off
setlocal
cd /d "%~dp0"
"C:\Users\Administrador\AppData\Local\Programs\Python\Python313\python.exe" app_tags.py
if errorlevel 1 (
    echo.
    echo La aplicacion no pudo iniciarse. Revise el error mostrado arriba.
    pause
)
endlocal
