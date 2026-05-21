@echo off
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0launcher.ps1"
if %errorlevel% neq 0 pause
