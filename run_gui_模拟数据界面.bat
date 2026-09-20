@echo off
setlocal

rem Locate the project root as the directory this .bat file lives in, so
rem it works no matter what directory it is double-clicked or invoked from.
set "PROJECT_ROOT=%~dp0"
pushd "%PROJECT_ROOT%"

rem Prefer a local virtual environment's own interpreter if one exists
rem (the common ".venv" convention), so the currently-set-up venv's
rem installed packages (PyQt6, etc.) are used automatically. Falls back to
rem whatever "python" resolves to on PATH otherwise (e.g. an already
rem-activated venv/conda environment, or a system-wide install).
if exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

rem Any arguments passed to this .bat are forwarded as-is, e.g.:
rem   run_gui_模拟数据界面.bat --mode hardware --port COM3
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\run_gui.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

popd
endlocal & exit /b %EXIT_CODE%


rem 2026-09-19 启动器改名后本文件出现中文（文件名互相引用），
rem 按既有规矩必须声明 UTF-8 代码页，否则 cmd 会按 GBK 解而乱码。
chcp 65001 >nul 2>&1