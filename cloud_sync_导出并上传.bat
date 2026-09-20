@echo off
setlocal

rem Double-clickable entry for the archive export (and, from P3, the upload).
rem
rem 手动触发：系统运行期间只往历史库写，不含定时器与后台上传。想上云时
rem 双击这个，它把尚未导出的整点时段一次补齐。详见 scripts\cloud_sync.py
rem 与 docs\02_Architecture\History_And_Cloud_Design.md 第 5.1 节。
rem
rem 放在项目根目录，与 run_gui_模拟数据界面.bat / start_llm_启动本地模型.bat 等入口并排——所有可双击
rem 的入口集中在一处。

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
rem   cloud_sync_导出并上传.bat --dry-run
rem   cloud_sync_导出并上传.bat --dir D:\archive
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\cloud_sync.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Keep the window open on failure so the reason stays readable.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo 归档导出未完成。已成功导出的时段已登记，不会重复导出；
    echo 未登记的时段会在下次运行时重新导出。
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
