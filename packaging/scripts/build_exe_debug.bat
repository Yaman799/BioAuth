\
@echo off
setlocal
cd /d "%~dp0"
cd /d "%~dp0..\.."

set "VENV_PY=%cd%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [FAIL] .venv\Scripts\python.exe was not found.
    exit /b 1
)

set PYTHONNOUSERSITE=1
set PIP_DISABLE_PIP_VERSION_CHECK=1
set QT_LOGGING_RULES=*.debug=true;qt.qml.binding.removal.info=false

echo [1/7] Python:
"%VENV_PY%" -c "import sys; print(sys.executable)"
if errorlevel 1 goto :fail

echo [2/7] Verifying build interpreter...
"%VENV_PY%" build_tools\check_build_python.py
if errorlevel 1 goto :fail

echo [3/7] Installing pinned build toolchain...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :fail
"%VENV_PY%" -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

echo [4/7] Running build preflight...
echo [INFO] Legacy Tk sources are not part of the packaged EXE path.
"%VENV_PY%" build_tools\preflight.py
if errorlevel 1 goto :fail

echo [5/7] Cleaning old build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [6/7] Building DEBUG console executable...
"%VENV_PY%" -m PyInstaller --noconfirm --clean --log-level=DEBUG --console ^
  --name BioAuth_Debug ^
  --icon bioauth.ico ^
  --version-file version_info.txt ^
  --runtime-hook build_tools\runtime_pyside6.py ^
  --add-data "qml;qml" ^
  --add-data "PRIVACY_POLICY.md;." ^
  --add-data "EULA.txt;." ^
  --add-data "bioauth.ico;." ^
  --hidden-import logger ^
  --hidden-import monitor ^
  --hidden-import worker_bootstrap ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput.mouse._win32 ^
  --collect-all PySide6 ^
  --collect-all pygame ^
  --collect-all sklearn ^
  --collect-all pyod ^
  --collect-all joblib ^
  --collect-all threadpoolctl ^
  desktop_app.py
if errorlevel 1 goto :fail

echo [7/7] Running packaged self-check...
dist\BioAuth_Debug\BioAuth_Debug.exe --self-check-packaging
if errorlevel 1 goto :fail

echo Debug build succeeded.
echo EXE path: %cd%\dist\BioAuth_Debug\BioAuth_Debug.exe
pause
exit /b 0

:fail
echo.
echo Debug build failed.
pause
exit /b 1
