@echo off
cd /d "%~dp0"
call "%~dp0_find_python.bat"
if not defined PY pause
if not defined PY exit /b 1
%PY% doctor.py
if errorlevel 1 echo.
if errorlevel 1 echo Fix the items marked with !! above, then run this again.
if errorlevel 1 pause
if errorlevel 1 exit /b 1
%PY% app.py
pause
