#!/usr/bin/env bash
# Zingly prototype: one script to set up Python and run every server.
#
#   ./start_up.sh               set up (if needed) and start everything
#   ./start_up.sh stop          stop everything (graceful, then forced)
#   ./start_up.sh restart       stop + start
#   ./start_up.sh status        what is running, on which port
#   ./start_up.sh test          run the automated test suite
#   ./start_up.sh logs [name]   tail logs (pss | mcp | voice_agent | genesys)
#
# Options: --skip-install  --clean-traces  --reinstall
# Ports (override with env): PSS_PORT=9001 MCP_PORT=8100 VOICE_AGENT_PORT=8080 GENESYS_PORT=8090
#
# If a port is already in use, whatever listens on it is stopped gracefully (SIGTERM, then
# SIGKILL after a grace period) before the new server starts.

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
  } | grep -E '^[0-9]+$' | sort -u
}

alive() { kill -0 "$1" 2>/dev/null; }

stop_pids() {   # graceful: SIGTERM, wait, then SIGKILL
  local label="$1"; shift
  local pids=("$@") left=()
  [[ ${#pids[@]} -eq 0 ]] && return 0
  info "Stopping $label (pid ${pids[*]}): SIGTERM"
  kill -TERM "${pids[@]}" 2>/dev/null || true
  for ((i = 0; i < GRACE_SECONDS * 4; i++)); do
    left=(); for p in "${pids[@]}"; do alive "$p" && left+=("$p"); done
    [[ ${#left[@]} -eq 0 ]] && return 0
    sleep 0.25
  done
  warn "$label did not exit within ${GRACE_SECONDS}s: SIGKILL ${left[*]}"
  kill -KILL "${left[@]}" 2>/dev/null || true
}

free_port() {
  local name="$1" port="$2" pids=()
  mapfile -t pids < <(pids_on_port "$port")
  if [[ ${#pids[@]} -gt 0 ]]; then
    warn "Port $port ($name) is in use"
    stop_pids "port $port" "${pids[@]}"
  fi
  mapfile -t pids < <(pids_on_port "$port")
  [[ ${#pids[@]} -eq 0 ]] || die "Port $port is still in use by pid ${pids[*]}"
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
    local pids=()
    if [[ -f "$RUN/$name.pid" ]]; then
      local p; p="$(cat "$RUN/$name.pid")"; alive "$p" && pids+=("$p")
      rm -f "$RUN/$name.pid"
    fi
    [[ "$scope" == "own" ]] || mapfile -t -O "${#pids[@]}" pids < <(pids_on_port "$port")
    [[ ${#pids[@]} -gt 0 ]] && stop_pids "$name" $(printf '%s\n' "${pids[@]}" | sort -u)
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

banner() {
  cat <<EOF

${c_green}All services are up.${c_off}
  Genesys softphone + agent desktop  http://127.0.0.1:$GENESYS_PORT
  Voice agent gateway                http://127.0.0.1:$VOICE_AGENT_PORT/docs
  MCP server (Streamable HTTP)       http://127.0.0.1:$MCP_PORT/atlantica/mcp   ·   /nordica/mcp
  Airline PSS (mock, 5 req/s)        http://127.0.0.1:$PSS_PORT/stats
  Traces (JSON lines)                .run/traces.jsonl

Try:
  .venv/bin/python scripts/run_flow.py --list            # demonstration flows
  .venv/bin/python scripts/run_flow.py happy_rebooking   # one flow, with its trace
  .venv/bin/python -m genesys_sim --trace                # interactive call
  .venv/bin/python scripts/spike.py                      # load spike: unprotected vs protected
  ./start_up.sh stop
EOF
}

# ------------------------------------------------------------------ main
cmd="start"; skip_install=""; clean_traces=""; reinstall=""
for arg in "$@"; do
  case "$arg" in
    start|stop|restart|status|test|logs) cmd="$arg" ;;
    --skip-install) skip_install=1 ;;
    --clean-traces) clean_traces=1 ;;
    --reinstall) reinstall=1 ;;
    pss|mcp|voice_agent|genesys) log_name="$arg" ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

case "$cmd" in
  stop) stop_all ;;
  status) status ;;
  logs) tail -n 50 -f "$RUN/${log_name:-voice_agent}.log" ;;
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
