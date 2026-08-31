@echo off
setlocal enabledelayedexpansion

rem ============================================================
rem  Deploy course_schedule plugin into N.E.K.O dev environment
rem  Double-click or run: deploy.bat [NekoSrc path]
rem ============================================================

set "PLUGIN_REPO=https://github.com/lingtongxinyv/n.e.k.o_plugin_course_schedule_plugin.git"
set "PLUGIN_ID=course_schedule"
set "WORK_ROOT=%TEMP%\neko-plugin-deploy"

rem -- optional arg: N.E.K.O source path --
set "NEKO_SRC=%~1"

echo.
echo  ============================================================
echo    Deploy N.E.K.O course_schedule plugin
echo  ============================================================
echo.

rem -- Step 0: prerequisites --
echo  [Step 0/5] Check prerequisites...
where git >nul 2>&1
if errorlevel 1 (
    echo    [FAIL] git not found
    echo    Install: https://git-scm.com/download/win
    exit /b 1
)
for /f "delims=" %%i in ('where git') do set "GIT_PATH=%%i"
echo    [OK] git : !GIT_PATH!

where uv >nul 2>&1
if errorlevel 1 (
    echo    [FAIL] uv not found
    echo    Install: https://docs.astral.sh/uv/getting-started/installation/
    exit /b 1
)
for /f "delims=" %%i in ('where uv') do set "UV_PATH=%%i"
echo    [OK] uv  : !UV_PATH!

rem -- Step 1: locate N.E.K.O source --
echo.
echo  [Step 1/5] Locate N.E.K.O source...

if not defined NEKO_SRC (
    if exist "%USERPROFILE%\Documents\N.E.K.O-src\pyproject.toml"      set "NEKO_SRC=%USERPROFILE%\Documents\N.E.K.O-src"
    if not defined NEKO_SRC if exist "%USERPROFILE%\N.E.K.O-src\pyproject.toml"             set "NEKO_SRC=%USERPROFILE%\N.E.K.O-src"
    if not defined NEKO_SRC if exist "%USERPROFILE%\code\N.E.K.O-src\pyproject.toml"         set "NEKO_SRC=%USERPROFILE%\code\N.E.K.O-src"
    if not defined NEKO_SRC if exist "%USERPROFILE%\source\repos\N.E.K.O-src\pyproject.toml" set "NEKO_SRC=%USERPROFILE%\source\repos\N.E.K.O-src"
    if not defined NEKO_SRC if exist "C:\N.E.K.O-src\pyproject.toml"                         set "NEKO_SRC=C:\N.E.K.O-src"
)

if not defined NEKO_SRC (
    echo    [WARN] Could not auto-detect N.E.K.O source.
    echo    Please enter the path to the N.E.K.O source folder:
    set /p "NEKO_SRC=    > "
)

rem strip surrounding quotes
set "NEKO_SRC=!NEKO_SRC:"=!"

if not exist "!NEKO_SRC!\pyproject.toml" (
    echo    [FAIL] Invalid path: !NEKO_SRC!
    echo           pyproject.toml not found.
    exit /b 1
)

set "PLUGIN_MOUNT=!NEKO_SRC!\plugin\plugins\!PLUGIN_ID!"
echo    [OK] N.E.K.O src   : !NEKO_SRC!
echo    [OK] Mount target  : !PLUGIN_MOUNT!

rem -- Step 2: get plugin source --
echo.
echo  [Step 2/5] Get plugin source from GitHub...

if not exist "!WORK_ROOT!" mkdir "!WORK_ROOT!"
set "PLUGIN_DIR=!WORK_ROOT!\!PLUGIN_ID!"

if exist "!PLUGIN_DIR!" (
    echo    Existing dir found, running git pull...
    pushd "!PLUGIN_DIR!"
    git pull --ff-only
    if errorlevel 1 (
        echo    Pull failed, deleting and re-clone...
        popd
        rmdir /s /q "!PLUGIN_DIR!"
        git clone "!PLUGIN_REPO!" "!PLUGIN_DIR!"
        if errorlevel 1 (
            echo    [FAIL] git clone failed
            exit /b 1
        )
    ) else (
        popd
    )
) else (
    git clone "!PLUGIN_REPO!" "!PLUGIN_DIR!"
    if errorlevel 1 (
        echo    [FAIL] git clone failed
        exit /b 1
    )
)
echo    [OK] Plugin source ready: !PLUGIN_DIR!

rem -- Step 3: mount into N.E.K.O tree --
echo.
echo  [Step 3/5] Mount plugin into N.E.K.O...

if not exist "!NEKO_SRC!\plugin\plugins" mkdir "!NEKO_SRC!\plugin\plugins"

robocopy "!PLUGIN_DIR!" "!PLUGIN_MOUNT!" /MIR ^
    /XD .git .github __pycache__ .pytest_cache .ruff_cache node_modules .venv ^
    /XF *.pyc *.pyo *.log sync.ps1 ^
    /NFL /NDL /NJH /NJS /NP
rem robocopy 0-7 = OK, >7 = FAIL
if errorlevel 8 (
    echo    [FAIL] robocopy failed ^(exit %ERRORLEVEL%^)
    exit /b 1
)
echo    [OK] Mounted -^> !PLUGIN_MOUNT!

rem -- Step 4: uv sync --
echo.
echo  [Step 4/5] uv sync plugin dependencies...
pushd "!NEKO_SRC!"
uv run --with pip python -m plugin.neko_plugin_cli.cli sync !PLUGIN_ID! --clean
if errorlevel 1 (
    echo    [WARN] sync returned non-zero, continuing...
) else (
    echo    [OK] Deps synced
)
popd

rem -- Step 5: release check --
echo.
echo  [Step 5/5] neko-plugin check --release...
pushd "!NEKO_SRC!"
uv run python -m plugin.neko_plugin_cli.cli check !PLUGIN_ID! --release
if errorlevel 1 (
    echo    [FAIL] release check FAILED
    echo           See output above for details.
    popd
    exit /b 1
)
popd
echo    [OK] release check PASSED

rem -- Done --
echo.
echo  ============================================================
echo    Plugin deployed successfully!
echo  ============================================================
echo.
echo    Mounted at : !PLUGIN_MOUNT!
echo    Quick verify:
echo      cd "!NEKO_SRC!"
echo      uv run python -m plugin.neko_plugin_cli.cli check !PLUGIN_ID! --release
echo.
echo    Start N.E.K.O, open Dashboard ^> Course Schedule panel.
echo.
endlocal
pause
