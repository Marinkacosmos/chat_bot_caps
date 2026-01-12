@echo off
setlocal

REM ---- 1. Install Conda env----
CALL "%USERPROFILE%\anaconda3\Scripts\conda.exe" env create -f .\environment.yml

REM ---- 2. Initialize Conda env----
CALL "%USERPROFILE%\anaconda3\Scripts\activate.bat" ocr-llm-bot

REM ---- 3. Start Ollama server in background ----
echo Starting Ollama server...
start "" /B ollama.exe serve

REM ---- 4. Download Ollama model----
ollama pull gpt-oss

endlocal

