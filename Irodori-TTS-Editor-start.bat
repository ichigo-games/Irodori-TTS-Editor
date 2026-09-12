@echo off
setlocal
title Irodori TTS Editor
if not defined IRODORI_HOME set "IRODORI_HOME=E:\Irodori-TTS"
set "EDITOR_PYTHON=%IRODORI_HOME%\.venv\Scripts\python.exe"
if not exist "%EDITOR_PYTHON%" (
    echo Python not found: "%EDITOR_PYTHON%"
    echo Set IRODORI_HOME to your Irodori-TTS installation folder.
    pause
    exit /b 1
)
echo Irodori TTS Editor
echo Open http://127.0.0.1:8765 in your browser after startup.
echo Press Ctrl+C to stop the server.
echo.
"%EDITOR_PYTHON%" -B -X utf8 "%~dp0run.py"
set "EDITOR_EXIT_CODE=%ERRORLEVEL%"
if not "%EDITOR_EXIT_CODE%"=="0" (
    echo.
    echo Server stopped with exit code %EDITOR_EXIT_CODE%.
    pause
)
exit /b %EDITOR_EXIT_CODE%
