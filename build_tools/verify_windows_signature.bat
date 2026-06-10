@echo off
setlocal
set "TARGET=%~1"
if "%TARGET%"=="" (
    echo [SIGN] No target was provided for verification.
    exit /b 1
)
if not exist "%TARGET%" (
    echo [SIGN] Target not found for verification: %TARGET%
    exit /b 1
)
if /I not "%BIOAUTH_ENABLE_SIGNING%"=="1" (
    echo [SIGN] Signature verification skipped because BIOAUTH_ENABLE_SIGNING is not 1. Public release remains blocked for unsigned artifacts.
    exit /b 0
)
set "SIGNTOOL=%BIOAUTH_SIGNTOOL%"
if "%SIGNTOOL%"=="" set "SIGNTOOL=signtool"
where "%SIGNTOOL%" >nul 2>&1
if errorlevel 1 (
    echo [SIGN] signtool was not found. Set BIOAUTH_SIGNTOOL to the full signtool.exe path.
    exit /b 1
)
"%SIGNTOOL%" verify /pa /v "%TARGET%"
exit /b %ERRORLEVEL%
