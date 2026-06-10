@echo off
setlocal
cd /d "%~dp0"
cd /d "%~dp0..\.."

echo Cleaning local artifacts...

for %%D in (build dist installer __pycache__) do (
    if exist "%%D" (
        echo - Removing %%D
        rmdir /s /q "%%D"
    )
)

for /d /r %%D in (__pycache__) do (
    if exist "%%D" (
        echo - Removing %%D
        rmdir /s /q "%%D"
    )
)

for /r %%F in (*.pyc) do (
    if exist "%%F" (
        echo - Deleting %%F
        del /f /q "%%F"
    )
)

for /r %%F in (*.pyo) do (
    if exist "%%F" (
        echo - Deleting %%F
        del /f /q "%%F"
    )
)

for /r %%F in (pytest*.log *.tmp *.bak *.orig *.rej) do (
    if exist "%%F" (
        echo - Deleting %%F
        del /f /q "%%F"
    )
)

for %%F in (old_supervised_block.txt train_model_chunk.txt .coverage) do (
    if exist "%%F" (
        echo - Deleting %%F
        del /f /q "%%F"
    )
)

echo Done.
exit /b 0
