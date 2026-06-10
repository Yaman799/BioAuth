@echo off
call "%~dp0packaging\scripts\clean_release.bat" %*
exit /b %errorlevel%
