@echo off
cd /d "%~dp0"
echo Starting Verdigo Pulse...
python server.py
if errorlevel 1 py server.py
pause
