@echo off
setlocal

rem Double-clickable counterpart of start_llm_启动本地模型.bat: unloads the local language
rem model so it stops holding ~3 GB of RAM. The service is left running, so
rem the next question just reloads the model (about 9 s).
rem
rem Pass --server to also stop the Ollama service and its tray program:
rem   stop_llm_停止本地模型.bat --server
rem Pass --status to only look, changing nothing.
rem
rem Nothing is deleted: the model files on D: stay where they are, this only
rem touches memory and processes. See scripts/stop_llm.py for the details.

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
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\stop_llm.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Keep the window open on failure so the reason stays readable.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [exit code %EXIT_CODE%]
    pause
) else (
    rem Leave the result on screen for a moment. ping instead of timeout:
    rem timeout aborts with "Input redirection is not supported" whenever
    rem stdin is redirected, e.g. when this .bat is called from a script.
    ping -n 4 127.0.0.1 >nul 2>&1
)

popd
endlocal & exit /b %EXIT_CODE%
