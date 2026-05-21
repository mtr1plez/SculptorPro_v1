#!/bin/bash

# SculptorPro Launcher Script
# This script starts the backend server and launches the Electron UI

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   SculptorPro - Starting Application${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"

# Create log directory
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Log files
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

# PID files to track processes
BACKEND_PID=""
FRONTEND_PID=""

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Shutting down SculptorPro...${NC}"
    
    # Kill backend process
    if [ -n "$BACKEND_PID" ]; then
        echo -e "${YELLOW}Stopping backend server (PID: $BACKEND_PID)...${NC}"
        kill $BACKEND_PID 2>/dev/null || true
        wait $BACKEND_PID 2>/dev/null || true
    fi
    
    # Kill frontend process
    if [ -n "$FRONTEND_PID" ]; then
        echo -e "${YELLOW}Stopping Electron UI (PID: $FRONTEND_PID)...${NC}"
        kill $FRONTEND_PID 2>/dev/null || true
        wait $FRONTEND_PID 2>/dev/null || true
    fi
    
    # Clean up any remaining processes on port 8000
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    
    echo -e "${GREEN}Cleanup complete. Goodbye!${NC}"
    exit 0
}

# Set up trap to call cleanup on script exit
trap cleanup EXIT INT TERM

has_required_modules() {
    local python_bin="$1"
    "$python_bin" - <<'PY' >/dev/null 2>&1
import importlib
for mod in ("uvicorn", "fastapi", "multipart"):
    importlib.import_module(mod)
PY
}

# Prefer the local venv only if it can actually run the backend.
if [ -x "$SCRIPT_DIR/.venv/bin/python" ] && has_required_modules "$SCRIPT_DIR/.venv/bin/python"; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

# Check if Python is available
if ! command -v "$PYTHON_BIN" &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed or not in PATH${NC}"
    exit 1
fi

# Check if Node.js is available
if ! command -v node &> /dev/null; then
    echo -e "${RED}Error: Node.js is not installed or not in PATH${NC}"
    exit 1
fi

# Check if npm is available
if ! command -v npm &> /dev/null; then
    echo -e "${RED}Error: npm is not installed or not in PATH${NC}"
    exit 1
fi

echo -e "${GREEN}✓ All prerequisites found${NC}"
echo -e "${BLUE}Using Python: ${PYTHON_BIN}${NC}"

# Start the backend server
echo -e "\n${BLUE}Starting backend server...${NC}"
PYTHONPATH=. "$PYTHON_BIN" -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --reload > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}✓ Backend server started (PID: $BACKEND_PID)${NC}"
echo -e "${BLUE}  Log file: $BACKEND_LOG${NC}"

# Wait for backend to be ready
echo -e "\n${BLUE}Waiting for backend to be ready...${NC}"
MAX_ATTEMPTS=30
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -s http://localhost:8000/status > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Backend is ready!${NC}"
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    echo -n "."
    sleep 1
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo -e "\n${RED}Error: Backend failed to start within 30 seconds${NC}"
    echo -e "${RED}Check the log file: $BACKEND_LOG${NC}"
    exit 1
fi

# Start the Electron UI
echo -e "\n${BLUE}Starting Electron UI...${NC}"
cd ui

# Check if node_modules exists, if not, install dependencies
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing UI dependencies (first run)...${NC}"
    npm install
fi

# Start Electron with Vite dev server
echo -e "${GREEN}Launching Electron with Vite dev server...${NC}"
npm run dev:electron > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

echo -e "${GREEN}✓ Electron UI started (PID: $FRONTEND_PID)${NC}"
echo -e "${BLUE}  Log file: $FRONTEND_LOG${NC}"

echo -e "\n${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}   SculptorPro is now running!${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop the application${NC}\n"

# Wait for Electron to exit
wait $FRONTEND_PID
