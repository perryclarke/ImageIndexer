@echo off
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
    echo exiftool is not found. Attempting to install using winget...
    winget install -e --id OliverBetz.ExifTool
    if errorlevel 1 (
        echo Failed to install exiftool. Please install it manually.
        pause
        exit /b 1
    )
    echo exiftool has been installed. Please restart this script for the changes to take effect.
    pause
    exit /b 0
) else (
    echo exiftool is already installed.
)

if not exist "%VENV_NAME%\Scripts\activate.bat" (
    echo Creating new virtual environment: %VENV_NAME%
    %PYTHON_PATH% -m venv %VENV_NAME%
    if errorlevel 1 (
        echo Failed to create virtual environment. Please check your Python installation.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment %VENV_NAME% already exists.
)

call "%VENV_NAME%\Scripts\activate.bat"

if not exist requirements.txt (
    echo requirements.txt not found. Please create a requirements.txt file in the same directory as this script.
    pause
    exit /b 1
)

python -m pip install --upgrade pip

echo Installing packages from requirements.txt...
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install some packages. Please check your internet connection and requirements.txt file.
    pause
    exit /b 1
)

:load_app
cls
echo.
echo ******************************************************
echo ** AFTER SELECTING A MODEL AN EXIT CODE WILL APPEAR ** 
echo **              THIS IS NOT AN ERROR                **
echo **        CLOSE THIS WINDOW WHEN YOU ARE DONE       **
echo ******************************************************
echo.
python -m src.llmii_setup

deactivate
exit /b 1