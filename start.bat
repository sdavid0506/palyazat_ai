@echo off
cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo HIBA: A program nincs telepitve!
    echo Futtasd elobb az install.bat fajlt.
    pause
    exit /b 1
)

if not exist .env (
    echo HIBA: Hianyzik a .env fajl!
    echo Helyezd el a .env fajlt a program melle.
    pause
    exit /b 1
)

set PYTHONUTF8=1
start "" venv\Scripts\pythonw.exe main.py
