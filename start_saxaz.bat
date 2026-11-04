@echo off
echo ===================================
echo       Starting SAXAZ
echo ===================================

cd /d "%~dp0"

IF NOT EXIST "venv\Scripts\activate.bat" (
    echo Virtual environment not found. Creating 'venv'...
    python -m venv venv
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Upgrading pip...
python -m pip install --upgrade pip >nul 2>&1

IF EXIST "requirements.txt" (
    echo Ensuring dependencies are installed...
    pip install -r requirements.txt
) ELSE (
    echo WARNING: requirements.txt not found. Dependencies were not installed.
)

IF NOT EXIST ".env" (
    echo.
    echo WARNING: No .env file found. Make sure you have your environment variables set!
)

echo.

echo Checking media directories...
IF NOT EXIST "media\questions" mkdir "media\questions"
IF NOT EXIST "media\videos" mkdir "media\videos"
IF NOT EXIST "media\thumbnails" mkdir "media\thumbnails"

echo Checking database migrations...
python migrate.py

echo.
echo Generating UI Sound Effects...
python generate_sfx.py

echo.
echo Downloading AI models...
python download_models.py

echo.
echo Starting the FastAPI web server...
echo Access the app at http://localhost:8000 (or your local IP address on the network)
echo Press Ctrl+C to stop the server.
echo.

echo Waiting for server to start before opening browser...
start /b python -c "import socket,time,os;[socket.socket().connect_ex(('127.0.0.1', 8000)) == 0 and (os.system('start chrome http://localhost:8000'), exit()) or time.sleep(1) for _ in range(60)]"

uvicorn main:app --reload --host 0.0.0.0 --port 8000
pause
