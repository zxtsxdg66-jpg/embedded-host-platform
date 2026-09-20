@echo off
setlocal

rem Double-clickable launcher that runs the PC desktop UI AND the Android
rem gateway together, sharing one serial connection to the STM32.
rem
rem Use this instead of starting run_gui_hardware_真实硬件界面.bat and run_api_server_手机网关.bat
rem separately: a COM port can only be opened by one process, so in hardware
rem mode the second one would fail with PermissionError(13). See
rem scripts/run_all.py for the full explanation.

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
rem   run_all_界面加网关.bat --mode hardware --port-serial COM10
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\run_all_launcher.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Keep the window open on failure so the message stays readable.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [exit code %EXIT_CODE%]
    pause
)

popd
endlocal & exit /b %EXIT_CODE%
