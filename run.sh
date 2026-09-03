#!/bin/bash
# run.sh - Simple watchdog script for Velqron Dashboard
# Runs the Streamlit app in an infinite loop. Restarts on crash.

echo "====================================="
echo " Starting Velqron MVP Watchdog"
echo "====================================="

export PYTHONPATH=$PYTHONPATH:.

# Locate streamlit binary (check virtual environments, then system PATH)
if [ -f "./venv/bin/streamlit" ]; then
    STREAMLIT_BIN="./venv/bin/streamlit"
elif [ -f "./.venv/bin/streamlit" ]; then
    STREAMLIT_BIN="./.venv/bin/streamlit"
elif command -v streamlit >/dev/null 2>&1; then
    STREAMLIT_BIN="streamlit"
else
    echo "[ERROR] Streamlit not found."
    echo "Please activate your virtual environment or install dependencies:"
    echo "    source venv/bin/activate"
    echo "    pip install -r requirements.txt"
    exit 1
fi

while true; do
    echo "[$(date)] Launching Dashboard..."
    $STREAMLIT_BIN run dashboard.py --server.port 8501 --server.address 0.0.0.0
    
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date)] Dashboard exited normally. Stopping."
        break
    else
        echo "[$(date)] Dashboard crashed with exit code $EXIT_CODE."
        echo "Restarting in 5 seconds..."
        sleep 5
    fi
done
