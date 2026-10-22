#!/usr/bin/env bash
# 一键构建并发布 MKB
#   ./scripts/deploy.sh         公司机（地址见 .server-info，端口 9400，docker）
#   ./scripts/deploy.sh harry   个人机（地址见 .server-info，端口 9001，systemd + nginx）
set -euo pipefail

TARGET="${1:-}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .server-info ]]; then
  echo "缺少 .server-info，请复制 .server-info.example 并填写机器地址" >&2
  exit 1
fi
# shellcheck disable=SC1091
source .server-info

log() { printf '\n==> %s\n' "$*"; }

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少命令: $1" >&2; exit 1; }; }
need rsync
need ssh
need npm

if [[ "$TARGET" == "harry" ]]; then
  # 个人服务器。本机 ssh config 把该 IP 指到 52000，实际 sshd 在 22。
  REMOTE="${HARRY_REMOTE:?.server-info 未设置 HARRY_REMOTE}"
  SSH_PORT=22
  REMOTE_DIR="/opt/mkb"
  PORT=9001
  API_PORT=9101
  ENV_FILE=".env-prod"
  LOG_HINT="ssh -p ${SSH_PORT} ${REMOTE} 'journalctl -u mkb -n 80 --no-pager'"
elif [[ -n "$TARGET" ]]; then
  echo "未知部署目标: ${TARGET}" >&2
  echo "用法: $0 [harry]" >&2
  exit 1
else
  REMOTE="${REMOTE:-${COMPANY_REMOTE:?.server-info 未设置 COMPANY_REMOTE}}"
  REMOTE_DIR="${REMOTE_DIR:-/data1/mkb}"
  OLD_REMOTE_DIR="${OLD_REMOTE_DIR:-~/mkb}"
  PORT="${PORT:-9400}"
  LOG_HINT="ssh ${REMOTE} 'cd ${REMOTE_DIR} && docker compose logs --tail 80'"
fi

HEALTH_URL="http://${REMOTE#*@}:${PORT}/api/health"

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
    --exclude '.env-prod' \
    --exclude '.server-info' \
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
  echo "健康检查失败，查看日志: ${LOG_HINT}" >&2
  exit 1
}

ssh_harry() {
  ssh -p "$SSH_PORT" -o BatchMode=yes -o IdentitiesOnly=yes "$REMOTE" "$@"
}

# 个人机内存约 1.6GB 且未装 Docker，用本机 venv + nginx。
deploy_harry() {
  log "个人服务器 ${REMOTE}:${REMOTE_DIR} 端口 ${PORT}"
  test -f "$ENV_FILE" || { echo "缺少 ${ENV_FILE}，请先配置密钥" >&2; exit 1; }
  build_frontend

  log "同步到 ${REMOTE}:${REMOTE_DIR}"
  ssh_harry "mkdir -p '${REMOTE_DIR}'"
  rsync -az --delete \
    -e "ssh -p ${SSH_PORT} -o BatchMode=yes -o IdentitiesOnly=yes" \
    --exclude '.venv/' \
    --exclude 'venv/' \
    --exclude 'frontend/node_modules/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    --exclude '.pytest_cache/' \
    --exclude '.mypy_cache/' \
    --exclude '.DS_Store' \
    --exclude '.env' \
    --exclude '.env-prod' \
    --exclude '.server-info' \
    "$ROOT/" "${REMOTE}:${REMOTE_DIR}/"

  log "写入远端环境变量（${ENV_FILE}）"
  scp -P "$SSH_PORT" -o BatchMode=yes -o IdentitiesOnly=yes \
    "$ENV_FILE" "${REMOTE}:${REMOTE_DIR}/.env"
  ssh_harry "chmod 600 '${REMOTE_DIR}/.env'"

  log "安装依赖并重启服务"
  ssh_harry "REMOTE_DIR=${REMOTE_DIR} API_PORT=${API_PORT} PORT=${PORT} bash -s" <<'EOF'
set -euo pipefail
cd "$REMOTE_DIR"
test -f .env
test -d frontend/dist
if [[ ! -x .venv/bin/pip ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --no-cache-dir \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com \
  -r backend/requirements.txt

if ! id -u mkb >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin mkb
fi
chown -R mkb:mkb "$REMOTE_DIR"

cat > /etc/systemd/system/mkb.service << UNIT
[Unit]
Description=MKB PubMed Q&A
After=network.target

[Service]
Type=simple
User=mkb
Group=mkb
WorkingDirectory=${REMOTE_DIR}
EnvironmentFile=${REMOTE_DIR}/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=${REMOTE_DIR}/.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port ${API_PORT}
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/nginx/conf.d/mkb.conf << NGINX
server {
    listen ${PORT};
    server_name _;
    client_max_body_size 20m;

    root ${REMOTE_DIR}/frontend/dist;
    index index.html;

    location /assets/ {
        try_files \$uri =404;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location = /index.html {
        add_header Cache-Control "no-cache";
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:${API_PORT}/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        gzip off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
NGINX

nginx -t
systemctl daemon-reload
systemctl enable mkb.service
systemctl restart mkb.service
systemctl reload nginx
EOF

  health_check
}

if [[ "$TARGET" == "harry" ]]; then
  deploy_harry
else
  ensure_remote_dir
  build_frontend
  sync_code
  stop_old_stack
  compose_up
  health_check
fi
