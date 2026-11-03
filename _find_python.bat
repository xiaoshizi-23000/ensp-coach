@echo off
rem Locate a Python 3 interpreter. Result goes into PY (quoted when it is a path).
set "PY="
set "PF86=%ProgramFiles(x86)%"

if not defined PY if exist "%~dp0runtime\python.exe" set PY="%~dp0runtime\python.exe"
if not defined PY if exist "%~dp0..\runtime\python.exe" set PY="%~dp0..\runtime\python.exe"

if not defined PY if exist "%~dp0python_path.txt" set /p PYPATH=<"%~dp0python_path.txt"
if not defined PY if defined PYPATH if exist "%PYPATH%" set PY="%PYPATH%"

if not defined PY py -3 -c "import sys" >nul 2>&1
if not defined PY if not errorlevel 1 set PY=py -3

if not defined PY python -c "import sys" >nul 2>&1
if not defined PY if not errorlevel 1 set PY=python

if not defined PY python3 -c "import sys" >nul 2>&1
if not defined PY if not errorlevel 1 set PY=python3

if not defined PY for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%~d\python.exe" set PY="%%~d\python.exe"
if not defined PY for /d %%d in ("C:\Python3*") do if exist "%%~d\python.exe" set PY="%%~d\python.exe"
if not defined PY for /d %%d in ("%ProgramFiles%\Python3*") do if exist "%%~d\python.exe" set PY="%%~d\python.exe"
if not defined PY for /d %%d in ("%PF86%\Python3*") do if exist "%%~d\python.exe" set PY="%%~d\python.exe"

if not defined PY echo.
if not defined PY echo   [X] Python 3 not found on this computer.
if not defined PY echo.
if not defined PY echo   1. Install Python 3 from https://www.python.org/downloads/
if not defined PY echo      and tick "Add python.exe to PATH" during setup.
if not defined PY echo   2. Or put a portable Python folder named "runtime" next to this file.
if not defined PY echo.
exit /b 0
