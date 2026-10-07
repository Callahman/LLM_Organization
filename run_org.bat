@echo off
setlocal
REM === Adjust these paths for your setup ===
set KOBOLDCPP_DIR=D:\LLM
set MODEL_PATH=D:\LLM\QWEN\Qwen3.8-27B-UD-Q4_K_M.gguf
set KOBOLD_PORT=5001
set ORG_DIR=D:\LLM\LLM_Organization

echo Starting KoboldCpp server...
REM Launch koboldcpp.exe directly (start /d sets the working directory). No
REM cmd /k wrapper and no nested quotes: a nested-quoted start line corrupts
REM cmd's batch-file position tracking, which makes the "goto waitloop" below
REM fail with "The system cannot find the batch label specified".
start "KoboldCpp Server" /d %KOBOLDCPP_DIR% koboldcpp.exe --model %MODEL_PATH% --usecublas --gpulayers 99 --contextsize 100000 --flashattention --quantkv q4_0 --jinja --jinjatools --port %KOBOLD_PORT%

echo Waiting for the model to finish loading...
:waitloop
powershell -NoProfile -Command "try { Invoke-RestMethod -Uri 'http://localhost:%KOBOLD_PORT%/v1/models' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    timeout /t 3 >nul
    goto waitloop
)

echo Server ready. Launching the Organization pipeline...
cd /d %ORG_DIR%

REM === Observability dashboard (read-only; third window) ===
echo Starting the observability dashboard (http://127.0.0.1:8090)...
start "Observability Dashboard" cmd /k "cd /d %ORG_DIR% && .venv\Scripts\python observability\dashboard.py --port 8090"
timeout /t 2 >nul

REM === The pipeline runs in THIS window, so you can interact with it ===
REM --interactive prompts you at the Leader's clarifying questions and the
REM mission approval. To run unattended (auto-answer / auto-approve), remove
REM the --interactive flag.
.venv\Scripts\python run_session.py --interactive

echo.
echo Organization run ended. The KoboldCpp server window is still running separately.
pause
