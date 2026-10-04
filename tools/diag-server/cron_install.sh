#!/usr/bin/env bash
# 安装诊断收件定时清理(root crontab,幂等:只增删自己的标记块)。
set -euo pipefail
MARK="# dotabyss-diag-cleanup"
TMP="$(mktemp)"

# 保留原 crontab,剔除旧的 diag 清理块
crontab -l 2>/dev/null | grep -vF "$MARK" \
  | grep -v "find /srv/diag-inbox" \
  | grep -v "diag-disk.log" > "$TMP" || true

cat >>"$TMP" <<'EOF'
# dotabyss-diag-cleanup
0 3 * * * find /srv/diag-inbox -type f -mtime +30 -delete
0 3 * * * find /srv/diag-inbox -mindepth 1 -type d -empty -delete
*/30 * * * * df -P /srv/diag-inbox | awk 'NR==2{gsub("%","",$5); if($5>85) print strftime("%F %T"),"diag-inbox 使用率",$5"%"}' >> /var/log/diag-disk.log
EOF

crontab "$TMP"
rm -f "$TMP"

# 确保 crond 在跑
systemctl enable --now crond 2>/dev/null || true

echo "== 已安装 crontab 的 diag 块 =="
crontab -l | grep -A3 -F "$MARK"
echo "crond: $(systemctl is-active crond 2>/dev/null)"
