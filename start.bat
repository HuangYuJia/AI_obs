@echo off
echo ========================================
echo   OBS Virtual Try-On - Starting Server
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.9+
    pause
    exit /b 1
)

REM Install dependencies
echo [1/3] Installing dependencies...
pip install -r requirements.txt -q
echo     Done.
echo.

REM Create directories
echo [2/3] Creating directories...
if not exist "uploads" mkdir uploads
if not exist "outputs" mkdir outputs
if not exist "clothing" mkdir clothing
if not exist "static" mkdir static
echo     Done.
echo.

REM Start server
echo [3/3] Starting server on http://localhost:8443
echo.
echo ========================================
echo   Open your browser at:
echo   http://localhost:8443
echo ========================================
echo.
echo   OBS WebSocket Settings:
echo   Host: localhost
echo   Port: 4455
echo   (Enable WebSocket in OBS: Tools ^> WebSocket Server Settings)
echo.
echo   Press Ctrl+C to stop the server
echo ========================================
echo.

python server.py
