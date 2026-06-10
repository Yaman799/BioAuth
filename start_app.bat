@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "BIOAUTH_DEBUG_PANEL=1"
set "BIOAUTH_DEBUG_SOURCE=start_app.bat"

set "FORCE_REINSTALL=0"
set "CONSOLE_MODE=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--reinstall" set "FORCE_REINSTALL=1"
if /I "%~1"=="--console" set "CONSOLE_MODE=1"
shift
goto parse_args

:args_done
if exist "dist\BioAuth\BioAuth.exe" (
    echo [BioAuth] Launch mode: dist\BioAuth\BioAuth.exe
    start "" "dist\BioAuth\BioAuth.exe"
    exit /b 0
)

echo [BioAuth] Launch mode: source/.venv

call :find_python
if errorlevel 1 goto python_missing

if not exist ".venv\Scripts\python.exe" (
    echo [BioAuth] Creating local virtual environment...
    %PYTHON_LAUNCHER% %PYTHON_ARGS% -m venv ".venv"
    if errorlevel 1 goto venv_failed
)

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
set "VENV_PYW=%CD%\.venv\Scripts\pythonw.exe"

if not exist "%VENV_PY%" goto venv_failed

set "NEED_INSTALL=0"
if "%FORCE_REINSTALL%"=="1" set "NEED_INSTALL=1"
if not exist ".venv\.deps_ok" set "NEED_INSTALL=1"
if "%NEED_INSTALL%"=="0" (
    "%VENV_PY%" -c "from pathlib import Path; import sys; stamp=Path('.venv/.deps_ok'); reqs=[Path('requirements.txt')]; face=Path('requirements-face.txt'); reqs.append(face) if face.exists() else None; newest=max(p.stat().st_mtime for p in reqs if p.exists()); sys.exit(0 if stamp.exists() and stamp.stat().st_mtime >= newest else 1)"
    if errorlevel 1 set "NEED_INSTALL=1"
)

if "%NEED_INSTALL%"=="1" goto install_deps

goto launch_app

:install_deps
echo [BioAuth] Installing required packages... this can take a few minutes on the first run.
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto install_failed
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto install_failed
if exist "requirements-face.txt" (
    "%VENV_PY%" -m pip install -r requirements-face.txt
    if errorlevel 1 goto install_failed
)
> ".venv\.deps_ok" echo ok

:launch_app
if "%CONSOLE_MODE%"=="1" (
    "%VENV_PY%" desktop_app.py
    exit /b %errorlevel%
)

if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" "%CD%\start_app.pyw"
) else (
    start "" "%VENV_PY%" desktop_app.py
)
exit /b 0

:find_python
set "PYTHON_LAUNCHER="
set "PYTHON_ARGS="

where py >nul 2>&1
if not errorlevel 1 (
    py -3.11 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_LAUNCHER=py"
        set "PYTHON_ARGS=-3.11"
        exit /b 0
    )
    py -3 -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_LAUNCHER=py"
        set "PYTHON_ARGS=-3"
        exit /b 0
    )
)

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_LAUNCHER=python"
        set "PYTHON_ARGS="
        exit /b 0
    )
)
exit /b 1

:python_missing
echo [BioAuth] Python was not found.
echo Install Python 3.11 for Windows, then run start_app.bat again.
pause
exit /b 1

:venv_failed
echo [BioAuth] Failed to create the local virtual environment.
pause
exit /b 1

:install_failed
echo [BioAuth] Failed to install required packages.
echo You can retry with: start_app.bat --reinstall
echo Or run: start_app.bat --console to see startup errors in a console.
pause
exit /b 1
