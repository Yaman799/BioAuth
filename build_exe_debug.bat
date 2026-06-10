@echo off
call "%~dp0packaging\scripts\build_exe_debug.bat" %*
exit /b %errorlevel%
