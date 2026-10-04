#!/usr/bin/env bash
# 诊断收件汇总(在 server 上运行)。用法: bash diag_fetch.sh [YYYY-MM-DD]  默认今天。
# 列出该日收件、抽取每个 summary 的崩溃签名行、给出计数与占用。
set -uo pipefail
DAY="${1:-$(date +%F)}"
DIR="/srv/diag-inbox/$DAY"
if [ ! -d "$DIR" ]; then
  echo "无 $DAY 收件:$DIR"
  echo "现有日期:"; ls -1 /srv/diag-inbox 2>/dev/null || echo "(空)"
  exit 0
fi
echo "== $DAY 收件 =="
ls -la "$DIR"
echo
echo "== 崩溃签名汇总(命中关键字的行) =="
for s in "$DIR"/*.summary.txt; do
  [ -e "$s" ] || continue
  echo "---- $(basename "$s" .summary.txt) ----"
  grep -aiE "runtime\.json|TextDataProvider|Player Content|Unable to load runtime|asset is null|BitConverter|Value cannot be null|CriSound|LoadBuiltinSound|InitializeAsync|InitializeServicesAsync|Exception|Traceback|失败|错误" "$s" | head -20
done
echo
zcount=$(ls "$DIR"/*.zip 2>/dev/null | wc -l)
fcount=$(find "$DIR" -type f | wc -l)
usage=$(du -sh "$DIR" 2>/dev/null | cut -f1)
echo "== 计数: zip=$zcount 总文件=$fcount 占用=$usage =="
echo "拉回本地: scp -r server:$DIR ./inbox-$DAY"
