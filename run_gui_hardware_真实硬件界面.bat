@echo off
setlocal

rem Double-clickable launcher for Hardware mode (real STM32 over serial).
rem
rem Simulator mode can be launched by simply double-clicking run_gui_模拟数据界面.bat,
rem but Hardware mode needs a COM port number, and that number is not
rem stable across replugs/USB sockets. So this launcher asks which port to
rem use instead of hardcoding one -- see scripts/run_gui_hardware.py.

rem Show Chinese text correctly: port descriptions come from Windows and
rem are localized. 65001 = UTF-8.
chcp 65001 >nul 2>&1

set "PROJECT_ROOT=%~dp0"
pushd "%PROJECT_ROOT%"

rem Prefer the project's own virtual environment if present, same rule as
rem run_gui_模拟数据界面.bat, so the venv's PyQt6/pyserial are used automatically.
if exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

rem Any extra arguments are forwarded, e.g.:
rem   run_gui_hardware_真实硬件界面.bat --baudrate 115200
rem   run_gui_hardware_真实硬件界面.bat --port COM7        (skips the prompt)
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\run_gui_hardware.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Keep the window open when double-clicked, so an error message (or the
rem "no serial port found" hint) stays readable instead of flashing away.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [exit code %EXIT_CODE%]
    pause
)

popd
endlocal & exit /b %EXIT_CODE%
