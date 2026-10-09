#!/usr/bin/env bash
# 一键构建并发布 MKB 到 lw@COMPANY_HOST:/data1/mkb （端口 9400）
set -euo pipefail

REMOTE="${REMOTE:-lw@COMPANY_HOST}"
REMOTE_DIR="${REMOTE_DIR:-/data1/mkb}"
OLD_REMOTE_DIR="${OLD_REMOTE_DIR:-~/mkb}"
PORT="${PORT:-9400}"
HEALTH_URL="http://${REMOTE#*@}:${PORT}/api/health"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { printf '\n==> %s\n' "$*"; }

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少命令: $1" >&2; exit 1; }; }
need rsync
need ssh
need npm

# --- 确保远端目录存在且可写（/data1 通常需 root 建目录，用 docker 规避 sudo）---
ensure_remote_dir() {
  log "检查远端目录 ${REMOTE}:${REMOTE_DIR}"
  if ssh "$REMOTE" "test -d '$REMOTE_DIR' && test -w '$REMOTE_DIR'"; then
    return 0
  fi
  log "创建 ${REMOTE_DIR}（docker 挂载 /data1）"
  local uid gid
  uid="$(ssh "$REMOTE" 'id -u')"
  gid="$(ssh "$REMOTE" 'id -g')"
  ssh "$REMOTE" "docker run --rm -v /data1:/data1 alpine:3.20 sh -c \
    'mkdir -p ${REMOTE_DIR} && chown ${uid}:${gid} ${REMOTE_DIR} && chmod 755 ${REMOTE_DIR}'"
  ssh "$REMOTE" "test -w '$REMOTE_DIR'" || {
    echo "无法写入 ${REMOTE}:${REMOTE_DIR}，请手动: sudo mkdir -p ${REMOTE_DIR} && sudo chown \$(whoami) ${REMOTE_DIR}" >&2
    exit 1
  }
}

# --- 构建前端 ---
build_frontend() {
  log "构建前端"
  (cd frontend && npm run build)
  test -f frontend/dist/index.html || { echo "frontend/dist 构建失败" >&2; exit 1; }
}

# --- 同步代码（含 .env 与 dist，排除本地虚拟环境/依赖）---
sync_code() {
  log "同步到 ${REMOTE}:${REMOTE_DIR}"
  test -f .env || { echo "缺少 .env，请先配置密钥" >&2; exit 1; }
  rsync -az --delete \
    --exclude '.venv/' \
    --exclude 'venv/' \
    --exclude 'frontend/node_modules/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    --exclude '.pytest_cache/' \
    --exclude '.mypy_cache/' \
    --exclude '.DS_Store' \
    "$ROOT/" "${REMOTE}:${REMOTE_DIR}/"
}

# --- 停掉旧目录上的同名容器（若仍在 ~/mkb）---
stop_old_stack() {
  log "清理旧部署目录 ${OLD_REMOTE_DIR}（若存在）"
  ssh "$REMOTE" "bash -lc '
    set -e
    old=\"${OLD_REMOTE_DIR}\"
    old=\${old/#\\~/\$HOME}
    if [[ -f \"\$old/docker-compose.yml\" ]]; then
      (cd \"\$old\" && docker compose down --remove-orphans) || true
    fi
  '"
}

# --- 远端 compose 启动 ---
compose_up() {
  log "docker compose up -d --build"
  ssh "$REMOTE" "bash -lc '
    set -e
    cd \"${REMOTE_DIR}\"
    test -f .env
    test -d frontend/dist
    docker compose up -d --build
    docker compose ps
  '"
}

# --- 健康检查 ---
health_check() {
  log "健康检查 ${HEALTH_URL}"
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS --connect-timeout 3 "$HEALTH_URL" >/tmp/mkb-health.json 2>/dev/null; then
      cat /tmp/mkb-health.json
      echo
      log "发布成功 → http://${REMOTE#*@}:${PORT}/"
      return 0
    fi
    sleep 2
  done
  echo "健康检查失败，查看日志: ssh ${REMOTE} 'cd ${REMOTE_DIR} && docker compose logs --tail 80'" >&2
  exit 1
}

ensure_remote_dir
build_frontend
sync_code
stop_old_stack
compose_up
health_check
