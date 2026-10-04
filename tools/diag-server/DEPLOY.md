# ドットアビスX 诊断包接收端 —— server 自托管部署(已上线实装记录)

> 现网形态:**直连 `server`(腾讯云 RockyLinux)公网端口**,不绕 nginx。已于 2026-10 部署并
> 端到端验通(公网上传→落盘,zip md5 逐字节一致)。真实 IP/端口/令牌/隐身路径**只存服务器**
> `/etc/dotabyss-diag.env`(权限 600),**不写进本仓库**。本文只记机制与维护姿势。

## 架构一句话
玩家启动器 `upload_diagnostics` → `POST http://<服务器>:<端口>/<隐身路径>`(multipart:
文件字段 `file`=诊断 zip、文本字段 `summary`=摘要;头带 `Authorization: Bearer <TOKEN>`)
→ systemd 服务 `dotabyss-diag`(降权用户 `diagbox`)按日期落盘到 `/srv/diag-inbox/<日期>/`,
并附写 `*.summary.txt`。

## 组件与位置(服务器)
| 用途 | 路径 |
|---|---|
| 接收端程序 | `/opt/dotabyss-diag/diag_server.js`(零依赖 Node 18+,加固版) |
| 机密/配置 | `/etc/dotabyss-diag.env`(600;含 HOST/PORT/SECRET_PATH/TOKEN/STORE_DIR/限速项) |
| systemd 单元 | `/etc/systemd/system/dotabyss-diag.service`(`User=diagbox`、`ReadWritePaths=/srv/diag-inbox`) |
| 收件目录 | `/srv/diag-inbox/<YYYY-MM-DD>/` |
| 主机防火墙 | `/etc/nftables.d/local_fw.nft`(默认拒绝白名单;已加一条本端口限速放行) |
| 一键部署 | `/opt/dotabyss-diag/deploy.sh`(幂等:密钥存在则沿用) |

## 加固与防滥用(接收端 + 防火墙,双层)
- **隐身**:非 `SECRET_PATH` 的任何路径/方法一律 `404`;响应体不回显路径;无产品标识 → 端口扫描者只见 404。
- **鉴权**:`Bearer TOKEN` 不符 → 401。
- **应用限速**:按来源 IP 滑动窗口(默认 6 次/分钟)+ 并发上限(默认 4)→ 超限 429。
- **大小上限**:64MB(与客户端一致)→ 超限 413。
- **防火墙限速**:`local_fw` 对该端口 `ct state new limit rate 8/minute burst 16` → SYN 层再兜一层。
- **降权**:`diagbox` 系统用户、`NoNewPrivileges`、`ProtectSystem=full`,只允许写 `/srv/diag-inbox`。

## 公网可达性要点(踩坑记录)
- 该机入站由 `inet local_fw`(priority `filter - 10`,先于腾讯云 YunJing 的 accept 生效)**默认全拒**,
  只放行 VPN/内网/loopback/established。所以新端口**必须在 `local_fw.nft` 加白名单**,否则公网连不上。
- **腾讯云 CVM 安全组这台是全放行的**,加完 `local_fw` 规则后公网即通(已实测),无需再去控制台开端口。
- 运维机在 StarVPN 网内,`ssh server` 走的是 `192.168.188.1`(被白名单放过),不代表公网可连——验证公网要用**非 VPN 出口**打公网 IP。

## 常用运维命令(SSH `server`)
```bash
systemctl status dotabyss-diag          # 健康
journalctl -u dotabyss-diag -n 50 --no-pager   # 上传流水(含来源 IP)
ss -ltnp | grep :<端口>                  # 确认监听
find /srv/diag-inbox -type f | wc -l     # 收件计数
cat /srv/diag-inbox/<日期>/*.summary.txt # 直接看崩溃签名摘要(无需解压)
```
改端口/令牌/限速:编辑 `/etc/dotabyss-diag.env` 后 `systemctl restart dotabyss-diag`
(令牌一改,随包 `launcher.json` 也要重生成)。

## 定时清理(你要的)
```bash
# 保留 30 天(crontab -e)
0 3 * * * find /srv/diag-inbox -type f -mtime +30 -delete
# 磁盘水位告警
*/30 * * * * df -P /srv/diag-inbox | awk 'NR==2{gsub("%","",$5); if($5>85) print strftime("%F %T"),$0}' >> /var/log/diag-disk.log
```

## 回滚
```bash
# 关服务
systemctl disable --now dotabyss-diag
# 撤防火墙放行(用 deploy 时生成的备份)
ls /etc/nftables.d/local_fw.nft.bak-diag-*   # 取最新
cp <最新备份> /etc/nftables.d/local_fw.nft && systemctl restart local-fw
```

## 打进随包 launcher.json(不进 Git)
构建前设环境变量,`build_full_pack.py` 会把端点 **base64 编码**成 `diag_endpoint` 写入
生成的 `launcher.json`(明文键 `diag_upload_url` 仍兼容):
```powershell
$env:DOTABYSS_DIAG_UPLOAD_URL   = "http://<服务器>:<端口>/<隐身路径>"
$env:DOTABYSS_DIAG_UPLOAD_TOKEN = "<TOKEN>"
D:\Python\python.exe build_full_pack.py ... # 其余参数照旧
```
客户端 `_diag_upload_target` 解析顺序:环境变量 → 明文 `diag_upload_url`/`token` → 隐身 `diag_endpoint`。

## 与 Cloudflare Worker 版的关系
`tools/diag-worker/`(Worker+R2+GitHub Issue)保留为**备选**;两者收**同一 multipart 契约**,
客户端换 `diag_upload_url` 即切换。现网选择:走自建服务器、不开 GitHub Issue(你已定)。
手动 zip 兜底始终保留(未配端点/失败时 `run_diag` 自动打开目录并提示发网盘)。
