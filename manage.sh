#!/usr/bin/env bash
# manage.sh — Avocet label tool manager
# Usage: ./manage.sh <command> [args]
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[avocet]${NC} $*"; }
success() { echo -e "${GREEN}[avocet]${NC} $*"; }
warn()    { echo -e "${YELLOW}[avocet]${NC} $*"; }
error()   { echo -e "${RED}[avocet]${NC} $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE=".avocet.pid"
PORT_FILE=".avocet.port"
LOG_DIR="log"
LOG_FILE="${LOG_DIR}/label_tool.log"
DEFAULT_PORT=8503

CONDA_BASE="${CONDA_BASE:-/devl/miniconda3}"
ENV_UI="job-seeker"
ENV_BM="job-seeker-classifiers"
STREAMLIT="${CONDA_BASE}/envs/${ENV_UI}/bin/streamlit"
PYTHON_BM="${CONDA_BASE}/envs/${ENV_BM}/bin/python"
PYTHON_UI="${CONDA_BASE}/envs/${ENV_UI}/bin/python"

# ── Port helpers ──────────────────────────────────────────────────────────────

_port_in_use() {
    local port=$1
    # Try lsof first (macOS + most Linux); fall back to ss (systemd Linux)
    if command -v lsof &>/dev/null; then
        lsof -iTCP:"$port" -sTCP:LISTEN -t &>/dev/null
    elif command -v ss &>/dev/null; then
        ss -tlnH 2>/dev/null | awk '{print $4}' | grep -q ":${port}$"
    else
        # Last resort: attempt a connection
        (echo "" >/dev/tcp/127.0.0.1/"$port") 2>/dev/null
    fi
}

_find_free_port() {
    local port=${1:-$DEFAULT_PORT}
    while _port_in_use "$port"; do
        warn "Port ${port} is in use — trying $((port + 1))…"
        ((port++))
    done
    echo "$port"
}

# ── PID helpers ───────────────────────────────────────────────────────────────

_running_pid() {
    # Returns the PID if a live avocet process is running, empty string otherwise
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(<"$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        else
            rm -f "$PID_FILE" "$PORT_FILE"
        fi
    fi
    echo ""
}

_running_port() {
    [[ -f "$PORT_FILE" ]] && cat "$PORT_FILE" || echo "$DEFAULT_PORT"
}

# ── Usage ─────────────────────────────────────────────────────────────────────

usage() {
    echo ""
    echo -e "  ${BLUE}Avocet — Email Classifier Training Tool${NC}"
    echo -e "  ${YELLOW}Scrape → Store → Process${NC}"
    echo ""
    echo "  Usage: ./manage.sh <command> [args]"
    echo ""
    echo "  Label tool:"
    echo -e "    ${GREEN}start${NC}                    Start label tool UI (port collision-safe)"
    echo -e "    ${GREEN}stop${NC}                     Stop label tool UI"
    echo -e "    ${GREEN}restart${NC}                  Restart label tool UI"
    echo -e "    ${GREEN}status${NC}                   Show running state and port"
    echo -e "    ${GREEN}logs${NC}                     Tail label tool log output"
    echo -e "    ${GREEN}open${NC}                     Open label tool in browser"
    echo ""
    echo "  Benchmark:"
    echo -e "    ${GREEN}benchmark [args]${NC}         Run benchmark_classifier.py (args passed through)"
    echo -e "    ${GREEN}list-models${NC}              Shortcut: --list-models"
    echo -e "    ${GREEN}score [args]${NC}             Shortcut: --score [args]"
    echo -e "    ${GREEN}compare [args]${NC}           Shortcut: --compare [args]"
    echo ""
    echo "  Vue API:"
    echo -e "    ${GREEN}start-api${NC}                Build Vue SPA + start FastAPI on port 8503"
    echo -e "    ${GREEN}stop-api${NC}                 Stop FastAPI server"
    echo -e "    ${GREEN}restart-api${NC}              Stop + rebuild + restart FastAPI server"
    echo -e "    ${GREEN}open-api${NC}                 Open Vue UI in browser (http://localhost:8503)"
    echo ""
    echo "  Dev:"
    echo -e "    ${GREEN}test${NC}                     Run pytest suite"
    echo ""
    echo "  Port defaults to ${DEFAULT_PORT}; auto-increments if occupied."
    echo "  Conda envs: UI=${ENV_UI}  Benchmark=${ENV_BM}"
    echo ""
    echo "  Examples:"
    echo "    ./manage.sh start"
    echo "    ./manage.sh benchmark --list-models"
    echo "    ./manage.sh score --include-slow"
    echo "    ./manage.sh compare --limit 30"
    echo ""
}

# ── Commands ──────────────────────────────────────────────────────────────────

CMD="${1:-help}"
shift || true

case "$CMD" in

    start)
        pid=$(_running_pid)
        if [[ -n "$pid" ]]; then
            port=$(_running_port)
            warn "Already running (PID ${pid}) on port ${port} → http://localhost:${port}"
            exit 0
        fi

        if [[ ! -x "$STREAMLIT" ]]; then
            error "Streamlit not found at ${STREAMLIT}\nActivate env: conda run -n ${ENV_UI} ..."
        fi

        port=$(_find_free_port "$DEFAULT_PORT")
        mkdir -p "$LOG_DIR"

        info "Starting label tool on port ${port}…"
        nohup "$STREAMLIT" run app/label_tool.py \
            --server.port "$port" \
            --server.headless true \
            --server.fileWatcherType none \
            >"$LOG_FILE" 2>&1 &

        pid=$!
        echo "$pid"  > "$PID_FILE"
        echo "$port" > "$PORT_FILE"

        # Wait briefly and confirm the process survived
        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            success "Avocet label tool started → http://localhost:${port}  (PID ${pid})"
            success "Logs: ${LOG_FILE}"
        else
            rm -f "$PID_FILE" "$PORT_FILE"
            error "Process died immediately. Check ${LOG_FILE} for details."
        fi
        ;;

    stop)
        pid=$(_running_pid)
        if [[ -z "$pid" ]]; then
            warn "Not running."
            exit 0
        fi
        info "Stopping label tool (PID ${pid})…"
        kill "$pid"
        # Wait up to 5 s for clean exit
        for _ in $(seq 1 10); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$pid" 2>/dev/null; then
            warn "Process did not exit cleanly; sending SIGKILL…"
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$PID_FILE" "$PORT_FILE"
        success "Stopped."
        ;;

    restart)
        pid=$(_running_pid)
        if [[ -n "$pid" ]]; then
            info "Stopping existing process (PID ${pid})…"
            kill "$pid"
            for _ in $(seq 1 10); do
                kill -0 "$pid" 2>/dev/null || break
                sleep 0.5
            done
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
            rm -f "$PID_FILE" "$PORT_FILE"
        fi
        exec bash "$0" start
        ;;

    status)
        pid=$(_running_pid)
        if [[ -n "$pid" ]]; then
            port=$(_running_port)
            success "Running  — PID ${pid}  port ${port}  → http://localhost:${port}"
        else
            warn "Not running."
        fi
        ;;

    logs)
        if [[ ! -f "$LOG_FILE" ]]; then
            warn "No log file found at ${LOG_FILE}. Has the tool been started?"
            exit 0
        fi
        info "Tailing ${LOG_FILE} (Ctrl-C to stop)"
        tail -f "$LOG_FILE"
        ;;

    open)
        port=$(_running_port)
        pid=$(_running_pid)
        [[ -z "$pid" ]] && warn "Label tool does not appear to be running. Start with: ./manage.sh start"
        URL="http://localhost:${port}"
        info "Opening ${URL}"
        if command -v xdg-open &>/dev/null; then
            xdg-open "$URL"
        elif command -v open &>/dev/null; then
            open "$URL"
        else
            echo "$URL"
        fi
        ;;

    test)
        info "Running test suite…"
        PYTEST="${CONDA_BASE}/envs/${ENV_UI}/bin/pytest"
        if [[ ! -x "$PYTEST" ]]; then
            error "pytest not found in ${ENV_UI} env at ${PYTEST}"
        fi
        "$PYTEST" tests/ -v "$@"
        ;;

    benchmark)
        info "Running benchmark (${ENV_BM})…"
        if [[ ! -x "$PYTHON_BM" ]]; then
            error "Python not found in ${ENV_BM} env at ${PYTHON_BM}\n" \
                  "Create it with: conda env create -f environment.yml"
        fi
        "$PYTHON_BM" scripts/benchmark_classifier.py "$@"
        ;;

    list-models)
        exec "$0" benchmark --list-models
        ;;

    score)
        exec "$0" benchmark --score "$@"
        ;;

    compare)
        exec "$0" benchmark --compare "$@"
        ;;

    start-api)
        API_PID_FILE=".avocet-api.pid"
        API_PORT=8503
        if [[ -f "$API_PID_FILE" ]] && kill -0 "$(<"$API_PID_FILE")" 2>/dev/null; then
            warn "API already running (PID $(<"$API_PID_FILE")) → http://localhost:${API_PORT}"
            exit 0
        fi
        mkdir -p "$LOG_DIR"
        API_LOG="${LOG_DIR}/api.log"
        info "Building Vue SPA…"
        (cd web && npm run build) >> "$API_LOG" 2>&1
        info "Starting FastAPI on port ${API_PORT}…"
        nohup "$PYTHON_UI" -m uvicorn app.api:app \
            --host 0.0.0.0 --port "$API_PORT" \
            >> "$API_LOG" 2>&1 &
        echo $! > "$API_PID_FILE"
        # Poll until port is actually bound (up to 10 s), not just process alive
        for _i in $(seq 1 20); do
            sleep 0.5
            if (echo "" >/dev/tcp/127.0.0.1/"$API_PORT") 2>/dev/null; then
                success "Avocet API started → http://localhost:${API_PORT}  (PID $(<"$API_PID_FILE"))"
                break
            fi
            if ! kill -0 "$(<"$API_PID_FILE")" 2>/dev/null; then
                rm -f "$API_PID_FILE"
                error "API died during startup. Check ${API_LOG}"
            fi
        done
        if ! (echo "" >/dev/tcp/127.0.0.1/"$API_PORT") 2>/dev/null; then
            error "API did not bind to port ${API_PORT} within 10 s. Check ${API_LOG}"
        fi
        ;;

    stop-api)
        API_PID_FILE=".avocet-api.pid"
        if [[ ! -f "$API_PID_FILE" ]]; then
            warn "API not running."
            exit 0
        fi
        PID="$(<"$API_PID_FILE")"
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" && rm -f "$API_PID_FILE"
            success "API stopped (PID ${PID})."
        else
            warn "Stale PID file (process ${PID} not running). Cleaning up."
            rm -f "$API_PID_FILE"
        fi
        ;;

    restart-api)
        bash "$0" stop-api
        exec bash "$0" start-api
        ;;

    open-api)
        URL="http://localhost:8503"
        info "Opening ${URL}"
        if command -v xdg-open &>/dev/null; then
            xdg-open "$URL"
        elif command -v open &>/dev/null; then
            open "$URL"
        else
            echo "$URL"
        fi
        ;;

    help|--help|-h)
        usage
        ;;

    *)
        error "Unknown command: ${CMD}. Run './manage.sh help' for usage."
        ;;

esac
