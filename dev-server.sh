#!/usr/bin/env bash
# dev-server.sh - Development server manager for Cotrade
# Ensures only one server runs at a time, with proper cleanup

set -euo pipefail

PORT="${1:-3000}"
HOST="${2:-127.0.0.1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}[dev-server]${NC} $*"; }
success() { echo -e "${GREEN}[dev-server]${NC} $*"; }
warn() { echo -e "${YELLOW}[dev-server]${NC} $*"; }
error() { echo -e "${RED}[dev-server]${NC} $*"; }

# Kill any existing Cotrade servers
cleanup() {
    log "Cleaning up existing Cotrade servers..."
    pkill -f "run.py server" 2>/dev/null || true
    pkill -f "python.*run.py" 2>/dev/null || true
    # Also kill any processes on our target port
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti:"$PORT" | xargs kill -9 2>/dev/null || true
    elif command -v fuser >/dev/null 2>&1; then
        fuser -k "$PORT"/tcp 2>/dev/null || true
    fi
    sleep 1
}

# Check if port is free
check_port() {
    if command -v nc >/dev/null 2>&1; then
        nc -z localhost "$PORT" 2>/dev/null && return 1 || return 0
    elif command -v ss >/dev/null 2>&1; then
        ss -ltn | grep -q ":$PORT " && return 1 || return 0
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn | grep -q ":$PORT " && return 1 || return 0
    else
        # Can't check, assume it's free
        return 0
    fi
}

# Start the server
start_server() {
    log "Starting Cotrade server on $HOST:$PORT..."
    python3 run.py server --port "$PORT" --host "$HOST" &
    SERVER_PID=$!

    # Wait for server to be ready
    local max_wait=30
    local waited=0
    while [ $waited -lt $max_wait ]; do
        if curl -sf "http://$HOST:$PORT/health" >/dev/null 2>&1; then
            success "Server ready at http://$HOST:$PORT"
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done

    error "Server failed to start within ${max_wait}s"
    kill $SERVER_PID 2>/dev/null || true
    return 1
}

# Main
case "${1:-start}" in
    start)
        cleanup
        if ! check_port; then
            warn "Port $PORT is in use, cleaning up..."
            cleanup
            sleep 1
        fi
        start_server
        # Keep script running to maintain the server
        wait $SERVER_PID
        ;;
    stop)
        cleanup
        success "Server stopped"
        ;;
    restart)
        cleanup
        sleep 1
        exec "$0" start "$PORT" "$HOST"
        ;;
    status)
        if curl -sf "http://$HOST:$PORT/health" >/dev/null 2>&1; then
            success "Server is running on $HOST:$PORT"
        else
            warn "Server is not running on $HOST:$PORT"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status} [PORT] [HOST]"
        echo "  Default PORT: 3000, HOST: 127.0.0.1"
        exit 1
        ;;
esac