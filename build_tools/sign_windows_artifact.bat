@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "TARGET=%~1"
if "%TARGET%"=="" (
    echo [SIGN] No target was provided.
    exit /b 1
)

if not exist "%TARGET%" (
    echo [SIGN] Target not found: %TARGET%
    exit /b 1
)

if /I not "%BIOAUTH_ENABLE_SIGNING%"=="1" (
    echo [SIGN] Signing skipped. Set BIOAUTH_ENABLE_SIGNING=1 to enable signing hooks.
    exit /b 0
)

set "SIGNTOOL=%BIOAUTH_SIGNTOOL%"
if "%SIGNTOOL%"=="" set "SIGNTOOL=signtool"

set "TIMESTAMP_URL=%BIOAUTH_TIMESTAMP_URL%"
if "%TIMESTAMP_URL%"=="" set "TIMESTAMP_URL=http://timestamp.digicert.com"

where "%SIGNTOOL%" >nul 2>&1
if errorlevel 1 (
    echo [SIGN] signtool was not found. Set BIOAUTH_SIGNTOOL to the full signtool.exe path.
    exit /b 1
)

if not "%BIOAUTH_SIGN_CERT_SHA1%"=="" (
    "%SIGNTOOL%" sign /fd SHA256 /td SHA256 /tr "%TIMESTAMP_URL%" /sha1 "%BIOAUTH_SIGN_CERT_SHA1%" "%TARGET%"
    exit /b %ERRORLEVEL%
)

set "BIOAUTH_SIGN_TEMP_CERT_FILE="
if "%BIOAUTH_SIGN_CERT_FILE%"=="" (
    if not "%BIOAUTH_SIGN_CERT_PFX_BASE64%"=="" (
        if "%BIOAUTH_SIGN_CERT_PASSWORD%"=="" (
            echo [SIGN] BIOAUTH_SIGN_CERT_PASSWORD is required when BIOAUTH_SIGN_CERT_PFX_BASE64 is provided.
            exit /b 1
        )
        set "BIOAUTH_SIGN_CERT_FILE=%TEMP%\bioauth_signing_cert_%RANDOM%%RANDOM%.pfx"
        set "BIOAUTH_SIGN_TEMP_CERT_FILE=1"
        powershell -NoProfile -ExecutionPolicy Bypass -Command "[IO.File]::WriteAllBytes($env:BIOAUTH_SIGN_CERT_FILE,[Convert]::FromBase64String($env:BIOAUTH_SIGN_CERT_PFX_BASE64))"
        if errorlevel 1 (
            echo [SIGN] Failed to materialize BIOAUTH_SIGN_CERT_PFX_BASE64 into a temporary certificate file.
            exit /b 1
        )
    )
)

if not "%BIOAUTH_SIGN_CERT_FILE%"=="" (
    if "%BIOAUTH_SIGN_CERT_PASSWORD%"=="" (
        echo [SIGN] BIOAUTH_SIGN_CERT_PASSWORD is required when BIOAUTH_SIGN_CERT_FILE is provided for production signing.
        if "%BIOAUTH_SIGN_TEMP_CERT_FILE%"=="1" del /q "%BIOAUTH_SIGN_CERT_FILE%" >nul 2>&1
        exit /b 1
    )
    "%SIGNTOOL%" sign /fd SHA256 /td SHA256 /tr "%TIMESTAMP_URL%" /f "%BIOAUTH_SIGN_CERT_FILE%" /p "%BIOAUTH_SIGN_CERT_PASSWORD%" "%TARGET%"
    set "SIGN_RESULT=!ERRORLEVEL!"
    if "%BIOAUTH_SIGN_TEMP_CERT_FILE%"=="1" del /q "%BIOAUTH_SIGN_CERT_FILE%" >nul 2>&1
    exit /b !SIGN_RESULT!
)

echo [SIGN] Signing enabled but no BIOAUTH_SIGN_CERT_SHA1, BIOAUTH_SIGN_CERT_FILE, or BIOAUTH_SIGN_CERT_PFX_BASE64 was provided.
exit /b 1
