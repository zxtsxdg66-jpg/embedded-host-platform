@echo off
setlocal

rem Double-clickable launcher for the local language model (Ollama).
rem Run this BEFORE the desktop UI when demonstrating the assistant: it starts
rem the service if needed and sends one real request so the model is already
rem loaded in memory. See scripts/start_llm.py for the full explanation.
rem
rem The assistant does NOT depend on this: with no model the Q&A still answers,
rem it just uses template wording instead of a more natural one.
rem
rem Same script as scripts\start_llm_启动本地模型.bat, kept at the project root next to
rem run_all_界面加网关.bat so every double-clickable entry point sits in one place.

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
rem   start_llm_启动本地模型.bat --check
rem   start_llm_启动本地模型.bat --timeout 90
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\start_llm.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Keep the window open on failure so the reason stays readable.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo 模型未就绪。上位机仍可正常启动与演示，只是问答走模板措辞。
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
