@echo off
setlocal

rem Double-clickable launcher for thesis experiment data collection.
rem
rem Asks which experiment to run, picks the serial port, then records every
rem frame the STM32 sends and writes a CSV plus a ready-to-paste Markdown
rem table into docs\07_Thesis\实验数据\.
rem
rem The serial port is exclusive: close run_all_界面加网关.bat / run_gui_hardware_真实硬件界面.bat /
rem run_api_server_手机网关.bat and any serial terminal before starting.

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

echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\collect_data_launcher.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Always pause: the run summary (file paths) must stay readable after a
rem long unattended collection.
echo.
pause

popd
endlocal & exit /b %EXIT_CODE%
