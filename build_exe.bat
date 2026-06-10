@echo off
setlocal
cd /d "%~dp0"

set "VENV_PY=%cd%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [INFO] .venv was not found. Bootstrapping build environment...
    call packaging\scripts\bootstrap_build_env.bat
    if errorlevel 1 exit /b 1
)

if not exist "%VENV_PY%" (
    echo [FAIL] .venv\Scripts\python.exe was not found after bootstrap.
    exit /b 1
)

set PYTHONNOUSERSITE=1
set PIP_DISABLE_PIP_VERSION_CHECK=1
set QT_LOGGING_RULES=qt.qml.binding.removal.info=false
if "%BIOAUTH_BUILD_PROFILE%"=="" set "BIOAUTH_BUILD_PROFILE=production"
if "%BIOAUTH_APP_VERSION%"=="" set "BIOAUTH_APP_VERSION=%GITHUB_REF_NAME%"
if "%BIOAUTH_APP_VERSION%"=="" set "BIOAUTH_APP_VERSION=1.0.0"
if "%BIOAUTH_APP_VERSION:~0,1%"=="v" set "BIOAUTH_APP_VERSION=%BIOAUTH_APP_VERSION:~1%"
if /I "%BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED%"=="1" (
    if /I "%BIOAUTH_BUILD_FLAVOR%"=="demo-classic-protected" (
        if "%BIOAUTH_EXE_NAME%"=="" set "BIOAUTH_EXE_NAME=BioAuth_DemoClassicProtected"
        if "%BIOAUTH_DIST_NAME%"=="" set "BIOAUTH_DIST_NAME=BioAuth_DemoClassicProtected"
    ) else (
        echo [WARN] Ignoring BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED because BIOAUTH_BUILD_FLAVOR is not demo-classic-protected.
        set "BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED="
    )
)
if "%BIOAUTH_EXE_NAME%"=="" set "BIOAUTH_EXE_NAME=BioAuth"
if "%BIOAUTH_DIST_NAME%"=="" set "BIOAUTH_DIST_NAME=BioAuth"
if "%BIOAUTH_PACKAGE_PROFILE%"=="" (
    if /I "%BIOAUTH_BUILD_PROFILE%"=="dev" set "BIOAUTH_PACKAGE_PROFILE=dev"
    if /I "%BIOAUTH_BUILD_PROFILE%"=="classic" set "BIOAUTH_PACKAGE_PROFILE=classic-minimal"
    if /I "%BIOAUTH_BUILD_PROFILE%"=="classic-minimal" set "BIOAUTH_PACKAGE_PROFILE=classic-minimal"
    if /I "%BIOAUTH_BUILD_WITH_HYBRID%"=="1" set "BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face"
    if /I "%BIOAUTH_BUILD_WITH_HYBRID%"=="0" set "BIOAUTH_PACKAGE_PROFILE=classic-minimal"
    if "%BIOAUTH_PACKAGE_PROFILE%"=="" set "BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face"
)
echo [INFO] BioAuth version: %BIOAUTH_APP_VERSION%
echo [INFO] Build profile: %BIOAUTH_BUILD_PROFILE%
echo [INFO] Package profile: %BIOAUTH_PACKAGE_PROFILE%
echo [INFO] EXE name: %BIOAUTH_EXE_NAME%
echo [INFO] Dist name: %BIOAUTH_DIST_NAME%
echo [INFO] Demo classic protected build: %BIOAUTH_BUILD_DEMO_CLASSIC_PROTECTED%
if /I "%BIOAUTH_PACKAGE_PROFILE%"=="hybrid-pro-face" (
    set "BIOAUTH_INCLUDE_FACE=1"
    set "BIOAUTH_INCLUDE_OPENCV=1"
)

echo [1/11] Python:
"%VENV_PY%" -c "import sys; print(sys.executable)"
if errorlevel 1 goto :fail

echo [2/11] Verifying build interpreter...
"%VENV_PY%" build_tools\check_build_python.py
if errorlevel 1 goto :fail

echo [3/11] Installing pinned build toolchain...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :fail
"%VENV_PY%" -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

echo [4/11] Installing project dependencies...
if /I "%BIOAUTH_PACKAGE_PROFILE%"=="dev" (
    "%VENV_PY%" -m pip install -r requirements-dev.txt
    if errorlevel 1 goto :fail
) else (
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
    if /I "%BIOAUTH_PACKAGE_PROFILE%"=="hybrid-pro" (
        echo [INFO] Installing optional Pro/Hybrid runtime profile...
        "%VENV_PY%" -m pip install -r requirements-pro.txt
        if errorlevel 1 goto :fail
    )
    if /I "%BIOAUTH_PACKAGE_PROFILE%"=="hybrid-pro-face" (
        echo [INFO] Installing optional Pro/Hybrid runtime profile...
        "%VENV_PY%" -m pip install -r requirements-pro.txt
        if errorlevel 1 goto :fail
        echo [INFO] Installing optional Face Confirmation runtime profile...
        "%VENV_PY%" -m pip install -r requirements-face.txt
        if errorlevel 1 goto :fail
    )
)

echo [5/11] Applying build version and generating Windows version resource...
"%VENV_PY%" build_tools\set_app_version.py "%BIOAUTH_APP_VERSION%"
if errorlevel 1 goto :fail
"%VENV_PY%" build_tools\write_version_info.py --output version_info.txt
if errorlevel 1 goto :fail

echo [6/11] Cleaning release artifacts...
call packaging\scripts\clean_release.bat
if errorlevel 1 goto :fail
"%VENV_PY%" build_tools\write_version_info.py --output version_info.txt
if errorlevel 1 goto :fail

echo [7/11] Verifying packaged Python sources...
"%VENV_PY%" -m py_compile desktop_app.py desktop_app_tk.py worker_bootstrap.py update_client.py bioauth_version.py release_runtime.py bio_platform\startup.py build_tools\packaged_runtime_support.py build_tools\packaged_smoke.py
if errorlevel 1 goto :fail
echo [INFO] Legacy Tk sources are not part of the packaged EXE path.

echo [8/11] Running build preflight...
"%VENV_PY%" build_tools\preflight.py
if errorlevel 1 goto :fail

echo [9/11] Cleaning old build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [10/11] Building %BIOAUTH_EXE_NAME%.exe...
"%VENV_PY%" -m PyInstaller --noconfirm --clean BioAuth.spec
if errorlevel 1 goto :fail

echo [11/15] Signing BioAuth.exe if configured...
rem Default product signing command: build_tools\sign_windows_artifact.bat "dist\BioAuth\BioAuth.exe"
call build_tools\sign_windows_artifact.bat "dist\%BIOAUTH_DIST_NAME%\%BIOAUTH_EXE_NAME%.exe"
if errorlevel 1 goto :fail

echo [12/15] Running release hygiene check...
"%VENV_PY%" build_tools\release_hygiene.py --dist "dist\%BIOAUTH_DIST_NAME%"
if errorlevel 1 goto :fail

echo [13/15] Generating release checksums...
"%VENV_PY%" build_tools\generate_checksums.py "dist\%BIOAUTH_DIST_NAME%" --output "dist\%BIOAUTH_DIST_NAME%\SHA256SUMS.txt"
if errorlevel 1 goto :fail

echo [14/15] Running packaged self-check...
dist\%BIOAUTH_DIST_NAME%\%BIOAUTH_EXE_NAME%.exe --self-check-packaging
if errorlevel 1 goto :fail
echo [INFO] Running packaged release-readiness self-check...
dist\%BIOAUTH_DIST_NAME%\%BIOAUTH_EXE_NAME%.exe --self-check-release-readiness
if errorlevel 1 goto :fail
if /I "%BIOAUTH_BUILD_FULL_SMOKE%"=="1" (
    echo [INFO] Running packaged runtime smoke...
    set PYNPUT_BACKEND=dummy
    set QT_QPA_PLATFORM=offscreen
    dist\%BIOAUTH_DIST_NAME%\%BIOAUTH_EXE_NAME%.exe --self-check-runtime-smoke
    if errorlevel 1 goto :fail
    echo [INFO] Running packaged performance smoke...
    dist\%BIOAUTH_DIST_NAME%\%BIOAUTH_EXE_NAME%.exe --self-check-performance
    if errorlevel 1 goto :fail
)

echo [15/15] Build succeeded.
echo EXE path: %cd%\dist\%BIOAUTH_DIST_NAME%\%BIOAUTH_EXE_NAME%.exe
exit /b 0

:fail
echo.
echo Build failed.
echo Run packaging\scripts\build_exe_debug.bat and send me the first error block.
exit /b 1
