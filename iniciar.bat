@echo off
setlocal
cd /d C:\TelemizaTeste

if not exist "C:\TelemizaTeste\.venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado em C:\TelemizaTeste\.venv
    pause
    exit /b 1
)

start "" "http://127.0.0.1:8000"
"C:\TelemizaTeste\.venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
endlocal
