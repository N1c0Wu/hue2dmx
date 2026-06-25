#!/bin/bash

# Determine script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PID_FILE="$SCRIPT_DIR/hue-dmx.pid"

# Determine Python executable (use venv if present)
if [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    PYTHON_EXE="$SCRIPT_DIR/venv/bin/python3"
else
    PYTHON_EXE="python3"
fi

start() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Hue-DMX is already running with PID $(cat "$PID_FILE")."
        exit 1
    fi

    echo "Starting Hue-DMX in background..."
    cd "$SCRIPT_DIR" || exit
    
    # Export service env variables
    export PYTHONUNBUFFERED=1
    export RUNNING_AS_SERVICE=true
    
    # Run in background via nohup and redirect logs
    nohup "$PYTHON_EXE" "$SCRIPT_DIR/hue-dmx.py" >> "$SCRIPT_DIR/hue-dmx-console.log" 2>&1 &
    
    PID=$!
    echo $PID > "$PID_FILE"
    echo "Hue-DMX started with PID $PID. Console output redirected to $SCRIPT_DIR/hue-dmx-console.log."
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping Hue-DMX with PID $PID..."
            kill "$PID"
            # Wait for process to exit
            for i in {1..10}; do
                if ! kill -0 "$PID" 2>/dev/null; then
                    break
                fi
                sleep 0.5
            done
            # Force kill if still running
            if kill -0 "$PID" 2>/dev/null; then
                echo "Process did not stop, force killing..."
                kill -9 "$PID"
            fi
        else
            echo "Process with PID $PID is not running."
        fi
        rm -f "$PID_FILE"
    else
        echo "No PID file found at $PID_FILE."
    fi
}

status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Hue-DMX is running (PID: $PID)."
        else
            echo "PID file exists but process $PID is not running."
        fi
    else
        echo "Hue-DMX is not running."
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    status)
        status
        ;;
    restart)
        stop
        sleep 1
        start
        ;;
    *)
        echo "Usage: $0 {start|stop|status|restart}"
        exit 1
esac

exit 0
