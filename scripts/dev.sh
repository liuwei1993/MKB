#!/usr/bin/env bash
# 本地同时启动后端 (http://127.0.0.1:8000) 与前端 (http://127.0.0.1:6173)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 前端 /api 代理读 API_PORT（见 frontend/vite.config.ts）。
API_HOST=127.0.0.1
API_PORT=8000
WEB_HOST=127.0.0.1
WEB_PORT=6173
PORT_SCAN_LIMIT=30

log() { printf '\n==> %s\n' "$*"; }

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少命令: $1" >&2; exit 1; }; }
need python3
need npm
need lsof

port_open() {
  python3 -c 'import socket,sys
s=socket.socket(); s.settimeout(0.3)
try:
    sys.exit(0 if s.connect_ex((sys.argv[1], int(sys.argv[2]))) == 0 else 1)
finally:
    s.close()' "$1" "$2"
}

# 监听该 TCP 端口的 PID 列表（空格分隔）。
port_pids() {
  local port="$1"
  lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u | tr '\n' ' '
}

proc_cmdline() {
  tr '\0' ' ' <"/proc/${1}/cmdline" 2>/dev/null || true
}

proc_cwd() {
  readlink "/proc/${1}/cwd" 2>/dev/null || true
}

# 是否为本仓库的后端 / 前端开发进程。
is_our_proc() {
  local pid="$1" kind="$2"  # api | web
  local cmd cwd
  cmd="$(proc_cmdline "$pid")"
  cwd="$(proc_cwd "$pid")"

  case "$kind" in
    api)
      [[ "$cmd" == *'backend.app.main:app'* ]] && return 0
      [[ "$cwd" == "$ROOT" || "$cwd" == "$ROOT"/* ]] && [[ "$cmd" == *uvicorn* ]] && return 0
      ;;
    web)
      [[ "$cwd" == "$ROOT"/frontend || "$cwd" == "$ROOT"/frontend/* ]] && return 0
      [[ "$cmd" == *"$ROOT/frontend"* ]] && return 0
      ;;
  esac
  return 1
}

kill_pids() {
  local pid child
  for pid in "$@"; do
    [[ -n "$pid" ]] || continue
    # 先停子进程（uvicorn --reload / vite 常见父子结构）
    while read -r child; do
      [[ -n "$child" ]] || continue
      kill "$child" 2>/dev/null || true
    done < <(pgrep -P "$pid" 2>/dev/null || true)
    kill "$pid" 2>/dev/null || true
  done
  sleep 0.4
  for pid in "$@"; do
    [[ -n "$pid" ]] || continue
    if [[ -d "/proc/$pid" ]]; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    while read -r child; do
      [[ -n "$child" ]] || continue
      if [[ -d "/proc/$child" ]]; then
        kill -9 "$child" 2>/dev/null || true
      fi
    done < <(pgrep -P "$pid" 2>/dev/null || true)
  done
}

find_free_port() {
  local host="$1" start="$2"
  python3 -c 'import socket,sys
host, start, limit = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
for port in range(start, start + limit):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
    except OSError:
        continue
    finally:
        s.close()
    print(port)
    raise SystemExit(0)
raise SystemExit("no free port")' "$host" "$start" "$PORT_SCAN_LIMIT"
}

# 若端口空闲直接返回；若为本应用占用则杀掉后复用；否则换空闲端口。
# 通过 nameref 写回最终端口。
ensure_port() {
  local host="$1" kind="$2"
  local -n port_ref="$3"
  local preferred="${port_ref}"
  local pids pid ours=() foreign=0

  if ! port_open "$host" "$preferred"; then
    return 0
  fi

  # shellcheck disable=SC2207
  pids=($(port_pids "$preferred"))
  if [[ ${#pids[@]} -eq 0 ]]; then
    log "端口 ${preferred} 已被占用，但无法识别进程，改用空闲端口"
    port_ref="$(find_free_port "$host" "$((preferred + 1))")"
    log "改用端口 ${port_ref}"
    return 0
  fi

  for pid in "${pids[@]}"; do
    if is_our_proc "$pid" "$kind"; then
      ours+=("$pid")
    else
      foreign=1
    fi
  done

  if [[ "$foreign" -eq 0 && ${#ours[@]} -gt 0 ]]; then
    log "端口 ${preferred} 由本应用占用（PID: ${ours[*]}），结束旧进程后重启"
    kill_pids "${ours[@]}"
    if port_open "$host" "$preferred"; then
      echo "结束旧进程后端口 ${preferred} 仍被占用" >&2
      exit 1
    fi
    port_ref="$preferred"
    return 0
  fi

  log "端口 ${preferred} 被其他进程占用（PID: ${pids[*]}），改用空闲端口"
  port_ref="$(find_free_port "$host" "$((preferred + 1))")"
  log "改用端口 ${port_ref}"
}

if [[ ! -x .venv/bin/uvicorn ]]; then
  log "创建虚拟环境并安装后端依赖"
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements.txt
fi

if [[ ! -d frontend/node_modules ]]; then
  log "安装前端依赖"
  (cd frontend && npm install)
fi

if [[ ! -f .env ]]; then
  echo "缺少 .env，请先: cp .env.example .env" >&2
  exit 1
fi

ensure_port "$API_HOST" api API_PORT
ensure_port "$WEB_HOST" web WEB_PORT

backend_pid=""
frontend_pid=""
stopped=0

cleanup() {
  if [[ "$stopped" -eq 1 ]]; then
    return
  fi
  stopped=1
  if [[ -n "$backend_pid" ]]; then
    kill -- "-${backend_pid}" 2>/dev/null || kill "$backend_pid" 2>/dev/null || true
  fi
  if [[ -n "$frontend_pid" ]]; then
    kill -- "-${frontend_pid}" 2>/dev/null || kill "$frontend_pid" 2>/dev/null || true
  fi
  [[ -n "$backend_pid" ]] && wait "$backend_pid" 2>/dev/null || true
  [[ -n "$frontend_pid" ]] && wait "$frontend_pid" 2>/dev/null || true
}

on_signal() {
  cleanup
  exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

# 后台任务各自成进程组，退出时能一并停掉 uvicorn --reload 和 vite 子进程
set -m

log "启动后端 http://${API_HOST}:${API_PORT}"
.venv/bin/uvicorn backend.app.main:app --reload --host "$API_HOST" --port "$API_PORT" &
backend_pid=$!

log "启动前端 http://${WEB_HOST}:${WEB_PORT}"
(cd frontend && exec env API_PORT="$API_PORT" npm run dev -- --host "$WEB_HOST" --port "$WEB_PORT") &
frontend_pid=$!

log "浏览器打开 http://${WEB_HOST}:${WEB_PORT}    Ctrl+C 停止"

status=0
if ! wait -n "$backend_pid" "$frontend_pid"; then
  status=$?
fi
exit "$status"
