#!/usr/bin/env bash
# 诊断接收端一键部署(server 侧运行)。密钥在本机运行时生成,不写进任何仓库文件。
set -uo pipefail
NODE="$(command -v node)"
PORT="${PORT:-41787}"
ENVF=/etc/dotabyss-diag.env

# 1) 生成或沿用 密钥/隐身路径
if [ -f "$ENVF" ] && grep -q '^SECRET_PATH=' "$ENVF" && grep -q '^TOKEN=' "$ENVF"; then
  echo "沿用已有 SECRET_PATH/TOKEN"
else
  SP="/ingest/$(openssl rand -hex 6)"
  TOK="$(openssl rand -hex 24)"
  umask 077
  cat >"$ENVF" <<EOF
HOST=0.0.0.0
PORT=$PORT
SECRET_PATH=$SP
TOKEN=$TOK
STORE_DIR=/srv/diag-inbox
RATE_MAX=6
RATE_WINDOW_MS=60000
MAX_CONC=4
EOF
  echo "已生成新密钥与隐身路径"
fi
chmod 600 "$ENVF"

# 2) 独立低权用户 + 存储目录
id -u diagbox >/dev/null 2>&1 || useradd -r -s /sbin/nologin diagbox
mkdir -p /srv/diag-inbox
chown -R diagbox:diagbox /srv/diag-inbox

# 3) systemd 单元(降权、只放开写 /srv/diag-inbox)
cat >/etc/systemd/system/dotabyss-diag.service <<EOF
[Unit]
Description=dotabyss diag receiver
After=network.target

[Service]
EnvironmentFile=$ENVF
ExecStart=$NODE /opt/dotabyss-diag/diag_server.js
Restart=always
RestartSec=3
User=diagbox
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ReadWritePaths=/srv/diag-inbox

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now dotabyss-diag
sleep 1
echo "== 服务状态 =="
systemctl is-active dotabyss-diag
ss -ltnp 2>/dev/null | grep ":$PORT" || echo "(端口未监听?!)"

# 4) 本机自测:错误路径应 404,正确路径+令牌应 200 且落盘
set +e
SPv="$(grep '^SECRET_PATH=' "$ENVF" | cut -d= -f2-)"
TOKv="$(grep '^TOKEN=' "$ENVF" | cut -d= -f2-)"
c404=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/nope")
c200=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $TOKv" -F "file=@/etc/hostname" "http://127.0.0.1:$PORT$SPv")
echo "== 自测 HTTP 码: 错误路径=$c404(应404) 正确路径=$c200(应200) =="
echo "== 收件目录 =="
find /srv/diag-inbox -type f | tail -3

echo "== 供打包 launcher.json 的对外信息 =="
echo "PORT=$PORT"
echo "SECRET_PATH=$SPv"
echo "TOKEN=$TOKv"
