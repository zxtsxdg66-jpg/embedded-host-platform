@echo off
setlocal

rem Double-clickable launcher for the Android gateway (REST + WebSocket).
rem
rem Asks which mode to run (simulator / hardware), picks a serial port when
rem needed, and -- most importantly -- prints the LAN address to type into
rem the phone. See scripts/run_api_server_launcher.py.

rem Show Chinese text correctly (65001 = UTF-8).
chcp 65001 >nul 2>&1

set "PROJECT_ROOT=%~dp0"
pushd "%PROJECT_ROOT%"

rem Prefer the project's own virtual environment if present, same rule as
rem the other launchers.
if exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

rem Extra arguments are forwarded, e.g.:
rem   run_api_server_手机网关.bat --mode simulator
rem   run_api_server_手机网关.bat --port 9000
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\run_api_server_launcher.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Keep the window open on failure so the message stays readable.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [exit code %EXIT_CODE%]
    pause
)

popd
endlocal & exit /b %EXIT_CODE%
