@echo off
setlocal

REM ---- 1. Initialize Conda ----
CALL "%USERPROFILE%\anaconda3\Scripts\activate.bat" ocr-llm-bot

REM ---- 2. Start Ollama server in background ----
echo Starting Ollama server...
start "" /B ollama.exe serve

REM Optional: wait a bit to ensure server is ready
timeout /t 3 >nul

REM ---- 3. Run Streamlit app ----
echo Starting Streamlit...
streamlit run app.py

endlocal
