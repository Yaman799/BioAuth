@echo off
setlocal
cd /d "%~dp0"
cd /d "%~dp0..\.."

if "%BIOAUTH_PACKAGE_PROFILE%"=="" set "BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face"
if /I "%BIOAUTH_PACKAGE_PROFILE%"=="hybrid-pro-face" (
    set "BIOAUTH_INCLUDE_FACE=1"
    set "BIOAUTH_INCLUDE_OPENCV=1"
)

if exist ".venv\Scripts\python.exe" (
    echo .venv already exists.
    goto :verify
)

echo [1/4] Creating .venv with Python 3.11 x64...
py -3.11-64 -m venv .venv >nul 2>nul
if errorlevel 1 (
    py -3.11 -m venv .venv >nul 2>nul
)
if errorlevel 1 (
    python -m venv .venv
)
if errorlevel 1 goto :fail

:verify
echo [2/4] Verifying build interpreter...
".\.venv\Scripts\python.exe" build_tools\check_build_python.py
if errorlevel 1 goto :fail

echo [3/4] Upgrading pip...
".\.venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :fail

echo [4/4] Installing requirements...
".\.venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail
if /I "%BIOAUTH_PACKAGE_PROFILE%"=="dev" (
    ".\.venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
    if errorlevel 1 goto :fail
) else (
    ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
    if /I "%BIOAUTH_PACKAGE_PROFILE%"=="hybrid-pro" (
        echo [INFO] Installing optional Pro/Hybrid runtime profile...
        ".\.venv\Scripts\python.exe" -m pip install -r requirements-pro.txt
        if errorlevel 1 goto :fail
    )
    if /I "%BIOAUTH_PACKAGE_PROFILE%"=="hybrid-pro-face" (
        echo [INFO] Installing optional Pro/Hybrid runtime profile...
        ".\.venv\Scripts\python.exe" -m pip install -r requirements-pro.txt
        if errorlevel 1 goto :fail
        echo [INFO] Installing optional Face Confirmation runtime profile...
        ".\.venv\Scripts\python.exe" -m pip install -r requirements-face.txt
        if errorlevel 1 goto :fail
    )
)

echo Environment is ready for package profile: %BIOAUTH_PACKAGE_PROFILE%.
exit /b 0

:fail
echo Environment bootstrap failed.
exit /b 1
