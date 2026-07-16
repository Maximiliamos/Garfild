@echo off
setlocal
title Garfield
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "APP=%~dp0garfield_flagship.py"

if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%APP%"
  goto :done
)

if exist "C:\Python314\python.exe" (
  "C:\Python314\python.exe" "%APP%"
  goto :done
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3.14 "%APP%"
  if not errorlevel 1 goto :done
  py -3 "%APP%"
  if not errorlevel 1 goto :done
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%APP%"
  goto :done
)

echo Python not found. Install Python 3.10+ or create .venv in this folder.
pause
exit /b 1

:done
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Garfield exited with code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
