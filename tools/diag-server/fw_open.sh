#!/usr/bin/env bash
# 在 local_fw 白名单里为目标端口加一条「限速放行」(可回滚,不改动其它规则)。
set -euo pipefail
PORT="${PORT:-41787}"
F=/etc/nftables.d/local_fw.nft

if grep -q "dport $PORT" "$F"; then
  echo "已存在 $PORT 放行规则,跳过"
else
  BK="$F.bak-diag-$(date +%Y%m%d%H%M%S)"
  cp -a "$F" "$BK"
  echo "备份: $BK"
  # 在 icmpv6 行后插入一条 tcp 端口限速放行(new 连接 8/min,burst 16)
  sed -i "/icmpv6 type echo-request accept/a\\        tcp dport $PORT ct state new limit rate 8/minute burst 16 packets accept" "$F"
  echo "已插入放行规则"
fi

echo "== 语法校验 =="
nft -c -f "$F" && echo "nft 语法 OK"
systemctl restart local-fw
echo "== 生效后的 input 链 =="
nft list chain inet local_fw input
echo "== 回滚方法(如需) =="
echo "cp <备份文件> $F && systemctl restart local-fw"
