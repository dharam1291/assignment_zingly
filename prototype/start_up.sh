#!/usr/bin/env bash
# Zingly prototype: one script to set up Python, run every server and run the demo flows.
# Run ./start_up.sh --help for every command and option.
#
# If a port is already in use, whatever listens on it is stopped gracefully (SIGTERM, then
# SIGKILL after a grace period) before the new server starts. Works with bash 3.2+.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
RUN="$ROOT/.run"
PY_BIN="$VENV/bin/python"
GRACE_SECONDS="${GRACE_SECONDS:-10}"

PSS_PORT="${PSS_PORT:-9001}"
MCP_PORT="${MCP_PORT:-8100}"
VOICE_AGENT_PORT="${VOICE_AGENT_PORT:-8080}"
GENESYS_PORT="${GENESYS_PORT:-8090}"

export ZINGLY_TENANTS_CONFIG="${ZINGLY_TENANTS_CONFIG:-$ROOT/config/tenants.yml}"
export GENESYS_SIM_CONFIG="${GENESYS_SIM_CONFIG:-$ROOT/sims/northbound/genesys.yml}"
export ZINGLY_TRACE_FILE="${ZINGLY_TRACE_FILE:-$RUN/traces.jsonl}"

PACKAGES=(
  libs/core libs/channel libs/ai_router libs/agents libs/auth libs/policy libs/saved_copy libs/mcp libs/handover
  services/mcp_server services/voice_agent sims/southbound sims/northbound
)

# name | port | module:app | health path   (start order: southbound -> MCP -> voice agent -> northbound)
SERVICES=(
  "pss|$PSS_PORT|mock_pss.app:app|/stats"
  "mcp|$MCP_PORT|mcp_server.app:app|/health"
  "voice_agent|$VOICE_AGENT_PORT|voice_agent.app:app|/health"
  "genesys|$GENESYS_PORT|genesys_sim.server:app|/health"
)

c_green=$'\033[32m'; c_yellow=$'\033[33m'; c_red=$'\033[31m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
[[ -t 1 ]] || { c_green=""; c_yellow=""; c_red=""; c_dim=""; c_off=""; }
info() { echo "${c_green}▸${c_off} $*"; }
warn() { echo "${c_yellow}!${c_off} $*"; }
die()  { echo "${c_red}✗${c_off} $*" >&2; exit 1; }

# ------------------------------------------------------------------ python setup
find_python() {
  for cand in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cand" >/dev/null 2>&1 &&
       "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      command -v "$cand"; return 0
    fi
  done
  return 1
}

setup_python() {
  local force="${1:-}"
  if [[ ! -x "$PY_BIN" ]]; then
    local py; py="$(find_python)" || die "Python 3.11+ is required (none found on PATH)."
    info "Creating virtual environment with $("$py" --version 2>&1) at .venv"
    "$py" -m venv "$VENV"
  fi
  local stamp="$VENV/.zingly-install" want
  want="$(cat "${PACKAGES[@]/%//pyproject.toml}" | cksum | cut -d' ' -f1)"
  if [[ "$force" == "force" || ! -f "$stamp" || "$(cat "$stamp")" != "$want" ]]; then
    info "Installing ${#PACKAGES[@]} packages (editable) + pytest"
    "$PY_BIN" -m pip install -q --upgrade pip
    local args=(); for p in "${PACKAGES[@]}"; do args+=(-e "$p"); done
    "$PY_BIN" -m pip install -q "${args[@]}" pytest
    echo "$want" > "$stamp"
  else
    info "Python environment up to date ${c_dim}($("$PY_BIN" --version))${c_off}"
  fi
}

# ------------------------------------------------------------------ ports and processes
pids_on_port() {
  local port="$1"
  {
    if command -v lsof >/dev/null 2>&1; then
      lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    elif command -v fuser >/dev/null 2>&1; then
      fuser -n tcp "$port" 2>/dev/null | tr -s ' ' '\n' || true
    elif command -v ss >/dev/null 2>&1; then
      ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 || true
    elif [[ -d /proc/net ]]; then
      # Linux without lsof/fuser/ss: map the listening socket inode to a pid via /proc.
      local py; py="$(find_python)" || return 0
      "$py" - "$port" <<'PY'
import os, sys
port = int(sys.argv[1]); inodes = set()
for table in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        for line in open(table).readlines()[1:]:
            f = line.split()
            if int(f[1].rsplit(":", 1)[1], 16) == port and f[3] == "0A":
                inodes.add(f[9])
    except OSError:
        pass
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            link = os.readlink(f"/proc/{pid}/fd/{fd}")
            if link.startswith("socket:[") and link[8:-1] in inodes:
                print(pid); break
    except OSError:
        pass
PY
    fi
  } | grep -E '^[0-9]+$' | sort -u || true   # no listener is not an error (set -e + pipefail)
}

alive() { kill -0 "$1" 2>/dev/null; }

# PIDs are plain numbers, so they travel as space-separated strings: no arrays, no mapfile.
# That keeps the script working on bash 3.2 (the macOS default) as well as bash 4/5.
stop_pids() {   # graceful: SIGTERM, wait, then SIGKILL.  $1 = label, $2 = "pid pid ..."
  local label="$1" pids left="" p i
  pids="$(echo $2)"   # trim and collapse spaces
  [[ -z "$pids" ]] && return 0
  info "Stopping $label (pid $pids): SIGTERM"
  kill -TERM $pids 2>/dev/null || true
  for ((i = 0; i < GRACE_SECONDS * 4; i++)); do
    left=""; for p in $pids; do alive "$p" && left="$left $p"; done
    [[ -z "$left" ]] && return 0
    sleep 0.25
  done
  warn "$label did not exit within ${GRACE_SECONDS}s: SIGKILL$left"
  kill -KILL $left 2>/dev/null || true
}

free_port() {
  local name="$1" port="$2" pids
  pids="$(pids_on_port "$port" | tr '\n' ' ')"
  if [[ -n "${pids// /}" ]]; then
    warn "Port $port ($name) is in use"
    stop_pids "port $port" "$pids"
  fi
  pids="$(pids_on_port "$port" | tr '\n' ' ')"
  [[ -z "${pids// /}" ]] || die "Port $port is still in use by pid $pids"
}

wait_healthy() {
  local name="$1" url="$2" pid="$3"
  for ((i = 0; i < 120; i++)); do
    if "$PY_BIN" -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=1)" "$url" 2>/dev/null; then
      return 0
    fi
    alive "$pid" || { tail -n 30 "$RUN/$name.log" >&2; die "$name exited during start-up (log: .run/$name.log)"; }
    sleep 0.25
  done
  die "$name did not become healthy at $url (log: .run/$name.log)"
}

start_all() {
  mkdir -p "$RUN"
  for spec in "${SERVICES[@]}"; do
    IFS='|' read -r name port app health <<<"$spec"
    free_port "$name" "$port"
    ZINGLY_SERVICE="$name" nohup "$VENV/bin/uvicorn" "$app" --host 127.0.0.1 --port "$port" \
      --log-level warning >"$RUN/$name.log" 2>&1 &
    local pid=$!
    echo "$pid" >"$RUN/$name.pid"
    wait_healthy "$name" "http://127.0.0.1:$port$health" "$pid"
    info "$(printf '%-12s' "$name") http://127.0.0.1:$port ${c_dim}(pid $pid)${c_off}"
  done
}

stop_all() {   # $1 = "own" to stop only processes this script started (pid files)
  local scope="${1:-all}" idx
  for ((idx = ${#SERVICES[@]} - 1; idx >= 0; idx--)); do   # reverse order: northbound first
    IFS='|' read -r name port _ _ <<<"${SERVICES[$idx]}"
    local pids="" p
    if [[ -f "$RUN/$name.pid" ]]; then
      p="$(cat "$RUN/$name.pid")"; alive "$p" && pids="$p"
      rm -f "$RUN/$name.pid"
    fi
    [[ "$scope" == "own" ]] || pids="$pids $(pids_on_port "$port" | tr '\n' ' ')"
    pids="$(printf '%s\n' $pids | sort -u | tr '\n' ' ')"
    [[ -n "${pids// /}" ]] && stop_pids "$name" "$pids"
  done
  [[ "$scope" == "own" ]] || info "All services stopped"
}

status() {
  for spec in "${SERVICES[@]}"; do
    IFS='|' read -r name port _ health <<<"$spec"
    local pids; pids="$(pids_on_port "$port" | tr '\n' ' ')"
    if [[ -n "$pids" ]]; then echo "${c_green}●${c_off} $(printf '%-12s' "$name") :$port  pid $pids"
    else echo "${c_red}○${c_off} $(printf '%-12s' "$name") :$port  not running"; fi
  done
}

usage() {
  cat <<EOF
${c_green}Zingly prototype${c_off} · set up Python, run the four servers, run the demonstration flows

${c_green}Usage${c_off}
  ./start_up.sh [command] [options]

${c_green}Commands${c_off}
  start                 Set up Python if needed and start all servers (the default command)
  restart               Stop everything this script started, then start again
  stop                  Stop all servers: SIGTERM, then SIGKILL after ${GRACE_SECONDS}s
  status                Show which servers are running, on which port
  flows [args]          Run the demonstration flows against the running servers
                        no args: all 14 flows; or names/numbers, e.g. flows 01 08 --trace
                        (args go to scripts/run_flow.py: --list --trace --record)
  test                  Run the automated test suite (pytest)
  logs [name]           Follow a server log: pss | mcp | voice_agent | genesys (default voice_agent)
  -h, --help            Show this help

${c_green}Options${c_off} (for start / restart)
  --clean-traces        Empty .run/traces.jsonl first, so traces show only the new run
  --skip-install        Do not check or install Python packages (faster restarts)
  --reinstall           Reinstall every package even if nothing changed

${c_green}Typical sequences${c_off}
  ./start_up.sh                                   first run: venv, install, start
  ./start_up.sh restart --clean-traces            fresh servers and an empty trace file
  ./start_up.sh flows                             all 14 flows, PASS/FAIL summary
  ./start_up.sh flows 08 --trace                  one flow with the trace of every turn
  ./start_up.sh flows --list                      list the flows
  ./start_up.sh status
  ./start_up.sh stop

${c_green}Other tools${c_off} (servers must be running)
  .venv/bin/python -m genesys_sim --trace         interactive call in the terminal
  .venv/bin/python scripts/spike.py               load spike: protection off vs on
  .venv/bin/python scripts/trace.py --last 3      read recent traces
  http://127.0.0.1:$GENESYS_PORT                           softphone + agent desktop in a browser

${c_green}Ports${c_off} (override with environment variables)
  PSS_PORT=$PSS_PORT  MCP_PORT=$MCP_PORT  VOICE_AGENT_PORT=$VOICE_AGENT_PORT  GENESYS_PORT=$GENESYS_PORT
EOF
}

banner() {
  cat <<EOF

${c_green}All services are up.${c_off}
  Genesys softphone + agent desktop  http://127.0.0.1:$GENESYS_PORT
  Voice agent gateway                http://127.0.0.1:$VOICE_AGENT_PORT/docs
  MCP server (Streamable HTTP)       http://127.0.0.1:$MCP_PORT/atlantica/mcp   ·   /nordica/mcp
  Airline PSS (mock, 5 req/s)        http://127.0.0.1:$PSS_PORT/stats
  Traces (JSON lines)                .run/traces.jsonl

Try:
  ./start_up.sh flows                                     # run all 14 demonstration flows
  ./start_up.sh flows happy_rebooking --trace             # one flow, with the trace of every turn
  .venv/bin/python -m genesys_sim --trace                 # interactive call
  .venv/bin/python scripts/spike.py                       # load spike: unprotected vs protected
  ./start_up.sh restart --clean-traces                    # fresh start, empty trace file
  ./start_up.sh --help                                    # every command
EOF
}

# ------------------------------------------------------------------ main
cmd="start"; skip_install=""; clean_traces=""; reinstall=""; log_name=""; flow_args=""
for arg in "$@"; do
  if [[ "$cmd" == "flows" ]]; then   # everything after "flows" belongs to run_flow.py
    case "$arg" in -h|--help) ;; *) flow_args="$flow_args $arg"; continue ;; esac
  fi
  case "$arg" in
    start|stop|restart|status|test|logs|flows) cmd="$arg" ;;
    --skip-install) skip_install=1 ;;
    --clean-traces) clean_traces=1 ;;
    --reinstall) reinstall=1 ;;
    pss|mcp|voice_agent|genesys) log_name="$arg" ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $arg (try ./start_up.sh --help)" ;;
  esac
done

case "$cmd" in
  stop) stop_all ;;
  status) status ;;
  logs) tail -n 50 -f "$RUN/${log_name:-voice_agent}.log" ;;
  flows)
    [[ -x "$PY_BIN" ]] || die "Environment not installed; run ./start_up.sh first"
    # flow_args is a plain word list on purpose (bash 3.2: no arrays under set -u)
    # shellcheck disable=SC2086
    if [[ -z "${flow_args// /}" ]]; then "$PY_BIN" scripts/run_flow.py --all
    else "$PY_BIN" scripts/run_flow.py $flow_args; fi ;;
  test)
    [[ -n "$skip_install" ]] || setup_python
    "$PY_BIN" -m pytest ;;
  start|restart)
    [[ -n "$skip_install" ]] || setup_python ${reinstall:+force}
    [[ -x "$VENV/bin/uvicorn" ]] || die "Environment not installed; run without --skip-install"
    stop_all own   # our previous run; anything else on a port is reported and stopped by free_port
    if [[ -n "$clean_traces" ]]; then rm -f "$ZINGLY_TRACE_FILE"; info "Trace file cleared"; fi
    start_all
    banner ;;
esac
