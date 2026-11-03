@echo off
cd /d "%~dp0"
call "%~dp0_find_python.bat"
if not defined PY pause
if not defined PY exit /b 1
echo Using: %PY%
%PY% gen_labs.py
pause
