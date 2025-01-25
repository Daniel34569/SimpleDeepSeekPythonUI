@echo off
REM Check Python existence and version compatibility
python -c "import sys; sys.exit(0 if sys.version_info >= (3,6) else 1)" 2>nul
if %ERRORLEVEL% neq 0 (
    echo Error: Python 3.6+ is required for f-string support.
    echo Please install Python 3.6 or newer and add it to system PATH.
    pause
    exit /b 1
)

if exist venv\ (
    echo Found existing virtual environment
    call venv\Scripts\activate.bat
) else (
    echo Creating new virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo Installing dependencies...
    pip install -r requirements.txt
)

echo Starting application...
python main.py

REM Keep window open after execution
cmd /k