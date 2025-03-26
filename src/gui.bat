@echo off
echo.
echo You can minimize this window, but do not close it.
echo.
setlocal enabledelayedexpansion

set "VENV_NAME=llmii_env"

set "PYTHON_PATH=python"

%PYTHON_PATH% --version >nul 2>&1
if errorlevel 1 (
    echo Python is not found. Please ensure Python is installed and added to your PATH.
    pause
    exit /b 1
)

where exiftool >nul 2>&1
if errorlevel 1 (
    call src/setup.bat
)

if not exist "%VENV_NAME%\Scripts\activate.bat" (
    call src/setup.bat
)

call "%VENV_NAME%\Scripts\activate.bat"
cls 
python -m src.llmii_gui

echo Done.