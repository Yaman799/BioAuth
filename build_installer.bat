@echo off
setlocal
cd /d "%~dp0"

if "%BIOAUTH_BUILD_PROFILE%"=="" set "BIOAUTH_BUILD_PROFILE=production"
if "%BIOAUTH_PACKAGE_PROFILE%"=="" set "BIOAUTH_PACKAGE_PROFILE=hybrid-pro-face"
if "%BIOAUTH_APP_VERSION%"=="" set "BIOAUTH_APP_VERSION=%GITHUB_REF_NAME%"
if "%BIOAUTH_APP_VERSION%"=="" set "BIOAUTH_APP_VERSION=1.0.0"
if "%BIOAUTH_APP_VERSION:~0,1%"=="v" set "BIOAUTH_APP_VERSION=%BIOAUTH_APP_VERSION:~1%"
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
echo [INFO] BioAuth version: %BIOAUTH_APP_VERSION%
echo [INFO] Build profile: %BIOAUTH_BUILD_PROFILE%
echo [INFO] Package profile: %BIOAUTH_PACKAGE_PROFILE%
if /I "%BIOAUTH_PACKAGE_PROFILE%"=="hybrid-pro-face" (
    set "BIOAUTH_INCLUDE_FACE=1"
    set "BIOAUTH_INCLUDE_OPENCV=1"
)

echo [1/9] Cleaning release artifacts...
call packaging\scripts\clean_release.bat
if errorlevel 1 goto :fail

echo [2/9] Building EXE...
call build_exe.bat
if errorlevel 1 goto :fail

if not exist "dist\BioAuth\BioAuth.exe" (
    echo [FAIL] dist\BioAuth\BioAuth.exe was not found after build.
    exit /b 1
)

echo [3/9] Resolving installer version...
"%VENV_PY%" build_tools\set_app_version.py "%BIOAUTH_APP_VERSION%"
if errorlevel 1 goto :fail
for /f "usebackq delims=" %%V in (`"%VENV_PY%" build_tools\print_version.py`) do set "BIOAUTH_APP_VERSION=%%V"
for /f "usebackq delims=" %%V in (`"%VENV_PY%" build_tools\print_version.py --windows-file-version`) do set "BIOAUTH_APP_FILE_VERSION=%%V"

echo [4/9] Locating Inno Setup compiler...
set "ISCC_EXE="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "%ISCC_EXE%"=="" (
    where iscc >nul 2>&1
    if not errorlevel 1 set "ISCC_EXE=iscc"
)

if "%ISCC_EXE%"=="" (
    echo [FAIL] Inno Setup Compiler was not found.
    echo Install Inno Setup 6 and run this script again.
    exit /b 1
)

echo [5/9] Building setup installer...
"%ISCC_EXE%" /DMyAppVersion=%BIOAUTH_APP_VERSION% /DMyAppVersionNumeric=%BIOAUTH_APP_FILE_VERSION% "BioAuthInstaller.iss"
if errorlevel 1 goto :fail

echo [6/9] Signing installer if configured...
for %%I in (installer\BioAuthDesktopSetup_*.exe) do call build_tools\sign_windows_artifact.bat "%%I"
if errorlevel 1 goto :fail

echo [7/9] Verifying installer signature if signing is enabled...
for %%I in (installer\BioAuthDesktopSetup_*.exe) do call build_tools\verify_windows_signature.bat "%%I"
if errorlevel 1 goto :fail

echo [8/9] Generating installer checksums...
"%VENV_PY%" build_tools\generate_checksums.py "installer" --output "installer\SHA256SUMS.txt"
if errorlevel 1 goto :fail

echo [9/9] Done.
echo Installer created in: %cd%\installer
exit /b 0

:fail
echo Installer build failed.
exit /b 1
