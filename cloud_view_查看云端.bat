@echo off
setlocal

rem Double-clickable viewer for what has already been uploaded to OSS.
rem
rem 只读：列出云上已有的归档，并打开阿里云控制台的文件列表页。
rem 它不上传、不删除、不改动任何东西——要上传请用 cloud_sync_导出并上传.bat。
rem
rem 详见 scripts\cloud_view.py 与 docs\06_UserGuide\User_Manual.md 4.3 节。

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
rem   cloud_view_查看云端.bat --no-browser
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%PROJECT_ROOT%scripts\cloud_view.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

rem Keep the window open on failure so the reason stays readable.
if not "%EXIT_CODE%"=="0" (
    echo.
    echo 没能查看云端文件。常见原因：还没填 oss_config.json，或者当前没有网络。
    echo [exit code %EXIT_CODE%]
    pause
) else (
    rem Leave the listing on screen long enough to read it.
    ping -n 6 127.0.0.1 >nul 2>&1
)

popd
endlocal & exit /b %EXIT_CODE%
