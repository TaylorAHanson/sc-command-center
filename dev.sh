#!/bin/bash

# Development script to run both frontend and backend concurrently
# Usage: ./dev.sh

# Don't use set -e here because we want to handle errors manually
# set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to cleanup background processes on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down services...${NC}"
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    wait $FRONTEND_PID $BACKEND_PID 2>/dev/null || true
    echo -e "${GREEN}Services stopped.${NC}"
    exit 0
}

# Trap Ctrl+C and call cleanup
trap cleanup SIGINT SIGTERM

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  SCCC Development Environment          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}\n"

# Clean up old log files
echo -e "${CYAN}Cleaning up old log files...${NC}"
rm -f backend.log frontend.log
echo -e "${GREEN}✓ Log files cleared${NC}"

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    echo -e "${CYAN}Loading environment variables from .env...${NC}"
    set -a
    source ".env"
    set +a
    echo -e "${GREEN}✓ Environment variables loaded from .env${NC}"
fi

# Check and kill processes on ports 8001 and 5174
echo -e "${CYAN}Checking for processes on ports 8001 and 5174...${NC}"
BACKEND_PORT_PID=$(lsof -ti:8001 2>/dev/null || true)
FRONTEND_PORT_PID=$(lsof -ti:5174 2>/dev/null || true)

if [ ! -z "$BACKEND_PORT_PID" ]; then
    echo -e "${YELLOW}Killing process on port 8001 (PID: $BACKEND_PORT_PID)...${NC}"
    kill -9 $BACKEND_PORT_PID 2>/dev/null || true
    sleep 1
fi

if [ ! -z "$FRONTEND_PORT_PID" ]; then
    echo -e "${YELLOW}Killing process on port 5174 (PID: $FRONTEND_PORT_PID)...${NC}"
    kill -9 $FRONTEND_PORT_PID 2>/dev/null || true
    sleep 1
fi

if [ ! -z "$BACKEND_PORT_PID" ] || [ ! -z "$FRONTEND_PORT_PID" ]; then
    echo -e "${GREEN}✓ Ports cleared${NC}\n"
else
    echo -e "${GREEN}✓ Ports available${NC}\n"
fi

# Python environment: uv builds .venv from uv.lock with the interpreter named in
# .python-version (downloading it if it isn't installed), which is how the
# deployed App installs too. It is a no-op when nothing has changed, so there is
# no stale venv to detect. --locked refuses a lock that no longer matches
# pyproject.toml rather than quietly installing the old set; ./lock.sh fixes it.
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${RED}✗ uv is not installed: https://docs.astral.sh/uv/getting-started/installation/${NC}"
    exit 1
fi
echo -e "${CYAN}Syncing Python environment (.venv) from uv.lock...${NC}"
if ! uv sync --locked; then
    echo -e "${RED}✗ uv sync failed. If uv.lock is out of date, run ./lock.sh${NC}"
    exit 1
fi
VENV_DIR="$(cd "${UV_PROJECT_ENVIRONMENT:-.venv}" && pwd)"
echo -e "${GREEN}✓ Python environment ready${NC}\n"

# Start backend (Python FastAPI)
echo -e "${GREEN}→ Starting backend API...${NC}"
cd server
# Add timestamp to log file
echo "=== Backend started at $(date) ===" > ../backend.log
# Running from server directory, imports are relative, so we use main:app
PYTHONUNBUFFERED=1 "$VENV_DIR/bin/uvicorn" main:app --reload --port 8001 >> ../backend.log 2>&1 &
BACKEND_PID=$!
cd ..

# Wait a moment for backend to start
sleep 3

# Check if backend started successfully
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}✗ Backend failed to start. Check backend.log for details.${NC}"
    if [ -f "backend.log" ]; then
        echo -e "${RED}Last few lines of backend.log:${NC}"
        tail -n 10 backend.log
    fi
    exit 1
fi

# Ensure frontend dependencies are installed
if [ ! -d "node_modules" ] || [ ! -f "node_modules/.bin/vite" ] && [ ! -f "node_modules/.bin/vite.cmd" ]; then
    echo -e "${YELLOW}node_modules not found or vite missing. Running npm install...${NC}"
    npm install
    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ npm install failed${NC}"
        kill $BACKEND_PID 2>/dev/null || true
        exit 1
    fi
    echo -e "${GREEN}✓ npm dependencies installed${NC}"
fi

# Start frontend (Vite)
echo -e "${GREEN}→ Starting frontend...${NC}"
# Add timestamp to log file
echo "=== Frontend started at $(date) ===" > frontend.log
npm run dev >> frontend.log 2>&1 &
FRONTEND_PID=$!

# Wait a moment for frontend to start
sleep 3

# Check if frontend started successfully
if ! kill -0 $FRONTEND_PID 2>/dev/null; then
    echo -e "${RED}✗ Frontend failed to start. Check frontend.log for details.${NC}"
    if [ -f "frontend.log" ]; then
        echo -e "${RED}Last few lines of frontend.log:${NC}"
        tail -n 10 frontend.log
    fi
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

echo -e "\n${GREEN}✓ Development environment is running!${NC}\n"
echo -e "${CYAN}Frontend:${NC}  ${BLUE}http://localhost:5174${NC}"
echo -e "${CYAN}Backend API:${NC} ${BLUE}http://localhost:8001${NC}"
echo -e "${CYAN}API Docs:${NC}   ${BLUE}http://localhost:8001/docs${NC}"
echo -e "\n${YELLOW}Press Ctrl+C to stop all services${NC}\n"
echo -e "${CYAN}────────────────────────────────────────────${NC}\n"
echo -e "${CYAN}Logs are being written to:${NC}"
echo -e "  ${BLUE}backend.log${NC} - Backend API logs"
echo -e "  ${GREEN}frontend.log${NC} - Frontend dev server logs"
echo -e "\n${CYAN}To view logs in real-time, open another terminal and run:${NC}"
echo -e "  ${BLUE}tail -f backend.log${NC}"
echo -e "  ${GREEN}tail -f frontend.log${NC}"
echo -e "\n${CYAN}Or view both:${NC}"
echo -e "  ${YELLOW}tail -f backend.log frontend.log${NC}\n"

# Keep script running and wait for processes
wait $FRONTEND_PID $BACKEND_PID
