#!/usr/bin/env bash
# 本地同时启动后端 (http://127.0.0.1:8000) 与前端 (http://127.0.0.1:5173)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 与 frontend/vite.config.ts 的 /api 代理一致，不能单独改后端端口。
API_HOST=127.0.0.1
API_PORT=8000
WEB_HOST=127.0.0.1
WEB_PORT=5173

log() { printf '\n==> %s\n' "$*"; }

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少命令: $1" >&2; exit 1; }; }
need python3
need npm

port_open() {
  python3 -c 'import socket,sys
s=socket.socket(); s.settimeout(0.3)
try:
    sys.exit(0 if s.connect_ex((sys.argv[1], int(sys.argv[2]))) == 0 else 1)
finally:
    s.close()' "$1" "$2"
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

if port_open "$API_HOST" "$API_PORT"; then
  echo "端口 ${API_PORT} 已被占用（${API_HOST}）" >&2
  exit 1
fi
if port_open "$WEB_HOST" "$WEB_PORT"; then
  echo "端口 ${WEB_PORT} 已被占用（${WEB_HOST}）" >&2
  exit 1
fi

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
(cd frontend && exec npm run dev -- --host "$WEB_HOST" --port "$WEB_PORT") &
frontend_pid=$!

log "浏览器打开 http://${WEB_HOST}:${WEB_PORT}    Ctrl+C 停止"

status=0
if ! wait -n "$backend_pid" "$frontend_pid"; then
  status=$?
fi
exit "$status"
