@echo off
cd /d "%~dp0"

echo ================================================
echo   AI Palyazatiro - Telepito
echo ================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo HIBA: Python nincs telepitve!
    echo Telepitsd a Python 3.12-t: https://www.python.org/downloads/
    echo Pipald be: "Add Python to PATH"
    pause
    exit /b 1
)

echo Python verzio:
python --version
echo.

echo [1/3] Virtualis kornyezet letrehozasa...
python -m venv venv
if errorlevel 1 (
    echo HIBA: venv letrehozasa sikertelen!
    pause
    exit /b 1
)
echo OK
echo.

echo [2/3] pip frissitese...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
echo OK
echo.

echo [3/3] Csomagok telepitese (5-15 perc)...
venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 (
    echo HIBA: Csomagok telepitese sikertelen!
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Telepites sikeres! Inditsd: start.bat
echo ================================================
pause
