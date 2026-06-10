@echo off
call "%~dp0packaging\scripts\bootstrap_build_env.bat" %*
exit /b %errorlevel%
