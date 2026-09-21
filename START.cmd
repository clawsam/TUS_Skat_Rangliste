@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START.ps1"
if errorlevel 1 (
    echo.
    echo Der Lauf ist fehlgeschlagen.
    pause
    exit /b 1
)

echo.
echo Lauf erfolgreich beendet.
pause
