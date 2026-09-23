@echo off
setlocal

rem Double-clickable entry for the CURRENT-HOUR snapshot upload.
rem
rem 和 cloud_sync_导出并上传.bat 跑的是同一个脚本，只多一个 --snapshot：
rem 它在补齐已结束时段之后，再把「当前这一小时到现在为止」截一份快照传上去。
rem 归档只处理已经结束的整点，所以整点之前「把现在的数据传上去」原本做不到，
rem 而演示要做的恰好是这件事。快照不登记台账，整点过后那一小时仍会完整导出
rem 一份归档。详见 docs\02_Architecture\History_And_Cloud_Design.md 第 5.4 节。
rem
rem 放在项目根目录，与 cloud_sync_导出并上传.bat 并排——所有可双击的入口集中在一处。

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
rem   cloud_snapshot_上传当前时段快照.bat --dry-run
rem   cloud_snapshot_上传当前时段快照.bat --no-upload
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\cloud_sync.py" --snapshot %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Keep the window open on failure so the reason stays readable.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo 未全部完成。已成功导出的整点时段已登记，不会重复导出；
    echo 未登记的时段下次运行会重新导出。快照不进待发队列，要重传就再跑一次。
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
