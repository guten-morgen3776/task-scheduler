#!/usr/bin/env bash
# task-scheduler launcher.
# Double-click this file in Finder (or pin it to the Dock) to start both
# servers and open the app in your browser. Ctrl+C in the terminal window
# stops whatever this script started.

set -uo pipefail

PORT_BACKEND=8000
PORT_FRONTEND=5173

# Resolve the repo root from the script's own location so this still works
# if the directory is moved.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$SCRIPT_DIR"

LOG_DIR="$HOME/.task-scheduler-logs"
mkdir -p "$LOG_DIR"

# Finder launches a .command file with a stripped PATH. Make sure Homebrew
# (uv / pnpm / node) is reachable.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

is_listening() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
}

backend_pid=""
frontend_pid=""

cleanup() {
  echo ""
  echo "Stopping servers we started..."
  [ -n "$backend_pid" ]  && kill "$backend_pid"  2>/dev/null
  [ -n "$frontend_pid" ] && kill "$frontend_pid" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

if is_listening "$PORT_BACKEND"; then
  echo "Backend already running on :$PORT_BACKEND — reusing it."
else
  echo "Starting backend on :$PORT_BACKEND ..."
  ( cd "$REPO/backend" \
    && uv run uvicorn app.main:app --port "$PORT_BACKEND" \
       > "$LOG_DIR/backend.log" 2>&1 ) &
  backend_pid=$!
fi

if is_listening "$PORT_FRONTEND"; then
  echo "Frontend already running on :$PORT_FRONTEND — reusing it."
else
  echo "Starting frontend on :$PORT_FRONTEND ..."
  ( cd "$REPO/frontend" \
    && pnpm dev --port "$PORT_FRONTEND" \
       > "$LOG_DIR/frontend.log" 2>&1 ) &
  frontend_pid=$!
fi

# Wait up to ~20s for both endpoints to respond.
echo "Waiting for servers to be ready..."
ready=0
for _ in $(seq 1 40); do
  if curl -fs -o /dev/null "http://localhost:$PORT_FRONTEND/" \
     && curl -fs -o /dev/null "http://localhost:$PORT_BACKEND/health"; then
    ready=1
    break
  fi
  sleep 0.5
done

if [ $ready -eq 1 ]; then
  open "http://localhost:$PORT_FRONTEND/"
else
  echo "WARNING: servers did not respond within the wait window." >&2
  echo "  Logs: $LOG_DIR/backend.log $LOG_DIR/frontend.log" >&2
fi

echo ""
echo "task-scheduler:"
echo "  Frontend: http://localhost:$PORT_FRONTEND/"
echo "  Backend:  http://localhost:$PORT_BACKEND/"
echo "  Logs:     $LOG_DIR/{backend,frontend}.log"
echo ""

if [ -z "$backend_pid" ] && [ -z "$frontend_pid" ]; then
  echo "(Servers were already running; closing this window will not stop them.)"
  exit 0
fi

echo "Close this window or press Ctrl+C to stop."
echo ""
wait
