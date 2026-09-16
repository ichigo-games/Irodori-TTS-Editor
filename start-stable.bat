@echo off
setlocal
"E:\Irodori-TTS\.venv\Scripts\python.exe" -B -X utf8 "%~dp0run.py" --profile stable
if errorlevel 1 pause
