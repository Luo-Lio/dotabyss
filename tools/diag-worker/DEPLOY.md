# ドットアビスX 诊断回传接收端(Cloudflare Worker + R2)部署文档

接收端作用:玩家点启动器的「收集日志」→ 生成诊断 zip → `upload_diagnostics` 以
`multipart/form-data`(文件字段 `file`=zip、文本字段 `summary`=诊断摘要纯文本,可选
`Authorization: Bearer <TOKEN>`)POST 到本 Worker → Worker 先把 zip 存进 R2(数据源),
再用**服务端令牌**在目标 GitHub 仓库自动开一个 Issue(标题带崩溃签名、正文贴摘要)。
与客户端 `tools/launcher/dotabyss_offline_core.py` 的上传契约一一对应。

> 安全要点:**GitHub 令牌只存 Worker secret,绝不下发给玩家**;玩家手里只有那条公开 URL。

> 免费额度足够用:Workers 免费版 10 万请求/天;R2 免费版 10GB 存储、读写请求不计流量费。

---

## 0. 前提
- 一个 Cloudflare 账号(免费注册)。
- 本机已装 Node(本项目机已确认有 `node`/`npx`)。`wrangler` 无需全局装,统一用 `npx wrangler`。
- 下面命令都在**本目录** `tools/diag-worker/` 下执行:
  ```powershell
  cd e:\agent\dmm\dotabyss\tools\diag-worker
  ```

## 1. 登录 Cloudflare(浏览器 OAuth,一次即可)
```powershell
npx wrangler login
```
浏览器会弹出授权页,用你的账号点 Allow。

## 2. 创建 R2 桶(名字要和 wrangler.toml 里一致:`dotabyss-diag`)
```powershell
npx wrangler r2 bucket create dotabyss-diag
```

## 3. 填 account_id
登录后可自动带出,或手动确认:
```powershell
npx wrangler whoami
```
把 `account_id` 填进本目录 `wrangler.toml` 的 `account_id = "..."`。
> 若不填,wrangler 会用它登录到的默认账号;多账号务必手填。
同时把 `[vars]` 里的 `GITHUB_REPO = "owner/name"` 改成**日志 Issue 要落到的仓库**。

## 4. 设置上传令牌(secret,别写进文件)
自己生成一串随机密钥当作玩家端与你服务端共享的口令(贴不进聊天记录,自己在终端里操作):
```powershell
npx wrangler secret put UPLOAD_TOKEN
```
回车后按提示输入一个长随机串(例如用 `python -c "import secrets;print(secrets.token_urlsafe(32))"` 现造)。
> 想省事也可以先不设 secret:Worker 在未配置 `UPLOAD_TOKEN` 时会放行匿名上传(靠 URL 隐蔽 + 64MB 上限兜底)。建议至少设上。

## 4b. 建 GitHub 令牌并注入(日志 Issue 用)
1. GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → New:
   - Repository access:Only select repositories → 选第3步 `GITHUB_REPO` 那个仓库;
   - Permissions → **Issues: Read and write**(仅此一项即可);
   - 生成后复制那串 `github_pat_...`(别发我、别贴进任何文件)。
2. 注入为 Worker secret(在 `tools/diag-worker` 目录):
   ```powershell
   npx wrangler secret put GITHUB_TOKEN
   ```
   按提示粘贴那串 PAT。
> 不设 `GITHUB_TOKEN`/`GITHUB_REPO` 时,Worker 仍能收包并**只存 R2**(响应里 `issueError` 会说明未开 Issue),不影响数据落地。

## 5. 部署
```powershell
npx wrangler deploy
```
成功后输出里会有:
```
https://dotabyss-diag-collector.<你的子域>.workers.dev
```
**这条 URL 就是客户端要打的端点**(可安全公开,不含密钥)。

## 6. 让客户端把包发到 Worker
`upload_diagnostics` 读取顺序:**环境变量优先 → 其次 `launcher.json`**。

方式 A|玩家零配置(随包分发,推荐):在游戏根 `launcher.json` 写:
```json
{
  "github_repo": "maintainer/dotabyss",
  "diag_upload_url": "https://dotabyss-diag-collector.<你的子域>.workers.dev/",
  "diag_upload_token": "与第4步相同的令牌"
}
```
(令牌若要随包,即为公开可见;不愿随包就把 token 字段留空,并在第4步也不设 secret。)

方式 B|自己临时用(不写进包):PowerShell 设环境变量后跑收集:
```powershell
$env:DOTABYSS_DIAG_UPLOAD_URL   = "https://dotabyss-diag-collector.<你的子域>.workers.dev/"
$env:DOTABYSS_DIAG_UPLOAD_TOKEN = "第4步的令牌"
```

## 7. 端到端自检(部署后立刻验一次)
用现成脚本打一个包并上传(拿你机器上的真实日志):
```powershell
cd e:\agent\dmm\dotabyss\tools\launcher
$env:DOTABYSS_DIAG_UPLOAD_URL   = "https://dotabyss-diag-collector.<你的子域>.workers.dev/"
$env:DOTABYSS_DIAG_UPLOAD_TOKEN = "第4步的令牌"
D:\Python\python.exe build_log_diag_zip.py ..\..\client\BepInEx\LogOutput.log ..\..\client\BepInEx\offline-api.log --upload
```
看到 `上传成功:已上传(HTTP 200)` 即通。

## 8. 收取玩家日志
每个包会**自动在目标仓库开一个 GitHub Issue**(标题带崩溃签名,正文有摘要与取回命令),直接去该仓库 Issues 页浏览即可。原始 zip 仍存在 R2,取回任一方式:
- Cloudflare 控制台 → R2 → 桶 `dotabyss-diag` → `diag/` 前缀,点下载。
- 命令行列目录 / 下载:
  ```powershell
  npx wrangler r2 object list dotabyss-diag/diag
  npx wrangler r2 object get dotabyss-diag/diag/<那个key> --file .\got.zip
  ```
拿到 zip 后,`diag/diag_summary.txt` 顶部就是「崩溃签名抽取」段(`aa/runtime.json` /
`TextDataProvider` / `BitConverter` / `InitializeAsync Failed`),`diag/logs/` 是原始日志。

## 9. 故障排查
| 现象 | 原因 / 处理 |
|---|---|
| 返回 401 | 令牌不符:客户端 token 与 secret 不一致,或没带 `Bearer`。核对第4步与 launcher.json/env 的 token。 |
| 返回 404/连不上 | URL 少 `/upload`? 本 Worker 任意路径都收,检查 URL 拼写与 workers.dev 是否已启用。 |
| 返回 413 | zip > 64MB,客户端已按上限截,一般不会触发;若触发说明单日志过大。 |
| 客户端 `skipped` | 没配 URL(env 与 launcher.json 都为空)→ 只留本地 zip,属预期。 |
| 存进去但打不开 zip | 多半是多字段/编码问题;本客户端是标准单 `file` 字段 multipart,`formData()` 直接可得。 |

## 10. 更新 / 回滚
改 `worker.js` 后重新:`npx wrangler deploy`。回滚看版本:
`npx wrangler deployments list` → `npx wrangler rollback`。

---
### 我能替你做到哪
- 沙箱内**没有你的 CF 凭据**,部署(`login`/`secret`/`deploy`)必须由你在自己终端完成;我也**不会索取令牌**。
- 部署完把第5步的 **URL 发我**(只发 URL),我来:把 URL 写进随包 `launcher.json` 的生成流程、补一个「从 R2 拉取并列出崩溃签名」的收取脚本、并把这套回传并入打包发布,做端到端验收。
