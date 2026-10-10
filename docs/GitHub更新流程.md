# GitHub 更新通道(离线版)

玩家启动器的「更新」按钮通过 GitHub Releases 获取增量更新。本文是维护者的发布流程。

---

## 1. 总体流程

```
启动器 → GET github.com/<repo>/releases/latest/download/version.json(CDN 直链,不走 REST API)
       → 读附件 version.json(版本号 + 基线 + 各资产 md5 + 文件清单)
       → 基线比对(不一致 → 「需重装」,拒绝增量)
       → 版本比对 + 本地产物核对(全部匹配且相同 → 「已是最新」)
       → 按需执行:client_body → caches_added → master_data → catalog → stories → previews → DLL → 文档 → 启动器
       → 每步校验 md5 后落盘;全部成功才写 offline_version.json;换了启动器则自替换重启
```

- 仓库地址写在**包根** `launcher.json` 的 `github_repo`(例 `owner/name`);
  空值 = 更新功能提示"未配置仓库"。
- **版本检查走 GitHub CDN,不访问 REST API**:清单固定取
  `https://github.com/<repo>/releases/latest/download/version.json`,附件 URL 由固定名拼成
  `.../releases/latest/download/<附件名>`;因此不受匿名 `api.github.com` 每 IP 60 次/小时的限流影响
  (共享出口不会再被 `HTTP 403 rate limit exceeded` 挡住)。`releases/latest` 不含 prerelease/draft
  —— 本项目发布均为正式版,这是有意的边界。
- 网络:先直连,失败自动回退系统代理(有系统代理时直连用 20 秒短超时)。
- **基线(baseline)优先**:`离线包 offline_version.json` 的 `baseline` 与 Release 的不一致时,
  启动器直接拒绝并提示「需重装」——即使版本号巧合相同。
- **本体(`GameAssembly.dll`)更新是最大风险面**:它同时换掉 IL2CPP interop(旧插件可能整体失效)
  与游戏侧的开机初始化/授权链路(2026-10-05 的 Win10 黑屏就是这么来的)。本体更新后必须
  **按新 interop 重编译插件 + 在 Windows 10 上验收**,清单见 `日常更新流程.md` §7。

## 2. 每个 Release 的附件(名字必须完全一致)

| 附件名 | 内容 | 落到玩家端 | 大小量级 |
| --- | --- | --- | --- |
| `version.json` | 更新清单(见 §3) | 只读,不落盘 | 几 KB |
| `StoryViewer.dll` | 插件本体 | `BepInEx\plugins\StoryViewer\StoryViewer.dll` | 0.1 MB |
| `stories.json` | 剧情索引 | 同目录 `stories.json` | 0.6 MB |
| `previews.zip` | 全部剧情封面(1229 张) | 解压覆盖 `StoryViewer\previews\` | 24 MB |
| `player_docs.zip` | 玩家文档 + `check_health.bat` | 解压到游戏根(白名单文件) | 几 KB |
| `DotabyssOfflineLauncher.exe` | 启动器本体 | 游戏根(退出后自替换) | 11 MB |
| `catalog_1.bin` + `catalog_1.bin.hash` | 资源 catalog 与哈希 | 包内 `catalog_seed\` + 存档 LocalLow | 13 MB |
| `client_body.zip` | 客户端本体(相对完整包的差异文件集,清单在 `version.json`) | 游戏根(只装 md5 不同的文件) | 现包 180 MB |
| `caches_update.zip` | 素材增量(新角色/新剧情 bundle) | `_Data\Caches`(清单在 `version.json`) | 视内容,通常几十 MB |
| `master_data.zip` | 主数据缓存(`DownloadCache/*.dat`) | 包内 `local_low_seed\DownloadCache\` + 离线 LocalLow | 约 11 MB |

> 附件名是启动器的识别依据,大小写敏感;**缺哪个就跳过哪一步**,不会中止整个更新。
> 但**声明了内容却缺附件**会失败关闭(如 `version.json` 里有 `catalog_hash` 但没有
> `catalog_1.bin`);`version.json` 声明 `master_data_files` 时缺 `master_data.zip` 也会失败,
> 避免"版本号写了、内容没装"的半吊子状态。

## 3. `version.json` 字段

```json
{
  "version": "20260924",              // 离线包版本号(日期),比对用
  "baseline": "20260924",             // 基线(冻结):不一致 → 需重装
  "channel": "baseline",              // 更新通道
  "plugin_version": "0.7.17",         // 展示/记录用
  "notes": "本次更新说明",
  "plugin_md5": "…",                  // StoryViewer.dll
  "stories_md5": "…",                 // stories.json
  "launcher_md5": "…",                // DotabyssOfflineLauncher.exe
  "previews_zip_md5": "…",            // previews.zip
  "player_docs_zip_md5": "…",         // player_docs.zip
  "catalog_hash": "…",                // catalog 哈希文本(版本标识)
  "catalog_bin_md5": "…",             // catalog_1.bin
  "catalog_hash_md5": "…",            // catalog_1.bin.hash
  "master_data_url": "master_data.zip", // 主数据附件名
  "master_data_md5": "…",              // master_data.zip
  "master_data_files": {                 // DownloadCache/*.dat 清单
    "DownloadCache/<哈希>.dat": "…"
  },
  "client_body": {                    // 客户端本体清单
    "zip": "client_body.zip", "zip_md5": "…", "bytes": 123,
    "files": { "ドットアビスX_Data/Managed/Assembly-CSharp.dll": "…" }
  },
  "caches_added": {                   // 素材增量清单(没有该字段 = 无素材更新)
    "zip": "caches_update.zip", "zip_md5": "…", "bytes": 123,
    "files": { "ドットアビスX_Data/Caches/<名>/<哈希>/__data": "…" }
  }
}
```

- **同版本号且所有已声明产物均匹配 = 已是最新**:启动器会核对本地产物与种子;
  即使版本号相同,缺失或 MD5 不符仍会继续修复。内容有改动时仍必须把 `version` 往后调(日期递增)。
- **`baseline` 一旦发布就不要改**,除非确实要让老玩家重装完整包(见 §7)。
- md5 任一不符 → 该步失败只打红字、**不写版本号**,可重试(已装部分保留)。
- 客户端本体清单**不含**插件目录、`_Data\Caches`、`app.info`、启动器 exe 与文档
  (它们各有自己的通道);启动器侧还有白名单/黑名单双重校验,拒绝越界路径。

## 4. 制作与上传(开发机)

> 游戏更新后"同步 game→client → 导出/重建索引封面 → 出附件 → 演练 → 发布"的**逐步操作清单**见
> [`日常更新流程.md`](日常更新流程.md)(含同步命令、catalog 取源等易踩项)。本节只列完整包路线。

```powershell
# 1. 在 client\ 里把该更新的都更新好(插件编译部署、stories.json/封面重导、必要时重新冻结启动器)

# 2. 若游戏本体或素材有更新:重打完整包(它同时产出 local_low_seed\ 与 catalog_seed\)
#    ⚠️ 必须显式带 --repo:不带时它取「源包」的 github_repo,而本机 dist 包的该字段可能是空的
#    (20261002 复核时实测就是空),会把空仓库写进新完整包 → 新装玩家永远无法更新。
D:\Python\python.exe tools\launcher\build_full_pack.py --recopy --zip --repo Luo-Lio/dotabyss

# 3. 生成发布附件到 dist\release_<版本>\(素材增量用 --caches-since 指旧包目录)
D:\Python\python.exe tools\launcher\build_github_pack.py --version 20261008 --notes "基底更新到20261008(插件0.7.27):修复全新机器卡标题、新增离线更新包;老玩家建议重新下载完整包整包重装"
D:\Python\python.exe tools\launcher\build_github_pack.py --version 20261008 --notes "..." --caches-since "dist\ドットアビスX离线版(旧)"

# 4. 上传(需已登录 gh;标题/说明按需)
gh release create 20261008 --title "离线包 20261008" --notes "基底更新到20261008;老玩家建议重新下载完整包" dist\release_20261008\*

# 5. 离线更新包(给连不上 GitHub 的玩家:把同一套 release 资产原样打成一个 zip,从网盘/群等渠道发布)
D:\Python\python.exe tools\launcher\build_update_pack.py --release-dir dist\release_20261008 --version 20261008
#   → 产出 dist\ドットアビスX_更新包_20261008.zip(玩家用启动器「高级 ▾ → 离线更新包」本地导入)
```

上传后到 Release 页面确认附件都在、名字没被改写。

> 离线更新包与 GitHub Release 是同一次发布的同一套资产(只是 zip 化),内容/基线/各 md5 完全一致;
> 玩家走哪条通道结果相同。发布时记得两个渠道都放:能上 GitHub 的走「更新」,连不上的走「离线更新包」。

> 最近一次发布的现状(版本 20261011、插件 0.7.30、启动器 md5、基线)见 **§8**。

## 5. 发布前的自测(无需真实网络)

启动器带离线演练口(`docs\离线版实现说明_开发者必读.md` §4):

```powershell
# 假发布目录:把 release_<版本>\ 拷一份即可——不再需要 release.json
# (版本检查已改走 CDN,--release-dir 按 URL 末段文件名映射,version.json 与各附件名直接命中)
# 然后对"旧包目录"跑:
DotabyssOfflineLauncher.exe --game-dir <旧包目录> --release-dir <发布目录> --auto-update out.txt
```

期望结果(用新版启动器跑):

1. 首次:输出 `OK-RESTART`(或 `OK`,若本次不含启动器更新),日志逐条走
   `client_body → caches_added → master_data → catalog → stories → previews → DLL → 文档 → 启动器`;
2. 再跑一次:输出 `OK-UPTODATE`;
3. 把发布目录的 `baseline` 改掉再跑:`BLOCKED-BASELINE`,且包内版本文件不变;
4. 检查 `.new` 是否被替换、`app.info` 是否仍是 `*_offline`、`_Data\Caches` 是否新增了 bundle。

## 6. 回滚

- 玩家侧:删掉 `BepInEx\plugins\StoryViewer\offline_version.json` 后重新解压完整包即可回到基线;
- 维护侧:重发一个版本号更高、内容为旧版的 Release(或直接让玩家用旧完整包重装)。
  注意**不要**用同一个版本号重发——同版本号玩家不会下载。
- 若已经换过 `baseline`,回滚也必须让 `baseline` 与目标完整包一致,否则玩家会一直看到「需重装」。

## 7. 与完整包的关系

- 完整包(`build_full_pack.py`)与更新通道是两条互补路径:
  新玩家拿完整包;老玩家用更新按钮增量更新。
- 完整包的 `offline_version.json` 决定老玩家的"起点":`baseline` 必须与 Release 的一致;
  `version` 必须**小于等于**最新 Release 的版本号,否则更新按钮会显示"已是最新"。
- **同一代基线内**:更新通道可以更新插件、索引、封面、文档、启动器、**客户端本体
  (`client_body`)**与**素材增量(`caches_added` + catalog)**——后者用于新角色/新剧情。
- **换基线的情况**:游戏本体大版本变化、缓存结构变化、或需要重新整包分发时,
  用新的 `baseline` 重打完整包并在 Release 里同步该 `baseline`;老玩家会被要求重装。
- 附件大小:GitHub 单附件上限 2 GB。`client_body.zip` 现约 180 MB;
  `caches_update.zip` 一般几十 MB;**若单次素材增量超过 2 GB**,说明该走新完整包而不是增量。
- 完整包 zip 约 8 GB,**超过 GitHub Release 单附件上限**,走网盘/其他渠道分发;
  更新通道附件正常发 GitHub Release。

## 8. 当前发布(20261011)

> 记录于 2026-10-11。修复版:**内容与 20261010 相同,只修插件与启动器**;基线仍 `20260924`。
> 下次发布按 §4 执行,完成后把本节改写为新的「当前发布」块。

- **插件 0.7.30**:`BitConverter` 空字节兜底**回退为 3 个**已知崩溃族
  (`ToBoolean / ToInt16 / ToInt32`)。0.7.29 扩到 10 个重载后,对 `ToUInt32` 等目标装 Harmony
  detour 会与 `il2cpp_runtime_invoke` 无限互递归 → 栈溢出(0xc00000fd),**玩家打开剧情面板/
  播放剧情时游戏崩溃**;0.7.30 因此回退,启动自检行随之恢复为
  `[空字节兜底] BitConverter 保护已安装: N/3 目标`(详情见 `离线版实现说明_开发者必读.md` §2.4)。
- **启动器(重新冻结)**:`client\DotabyssOfflineLauncher.exe`,md5
  `98C9B604AD463C2B2DA43404C87179C7`,冒烟 `PASS`;诊断上传端点常量经 PyInstaller 归档 API
  复核仍在 exe 的 PYZ 内且非空。三项变化:
  1. **版本检查改走 GitHub CDN,不再访问 REST API**:取
     `https://github.com/<repo>/releases/latest/download/version.json`,附件 URL 由固定名拼成
     `.../releases/latest/download/<附件名>`;新增纯函数
     `dotabyss_offline_core.release_from_cdn_base(base_url)`。原因:匿名 `api.github.com` 每 IP
     60 次/小时,共享出口会被 `HTTP 403 rate limit exceeded` 挡住。副作用边界:`releases/latest`
     不含 prerelease/draft(本项目发布都是正式版)。**演练因此不再需要 `release.json`**(见 §5)。
  2. **新增下载进度显示**:大附件下载显示百分比/进度条(有 `Content-Length` 时确定态,否则不确定态)。
  3. **修自替换重启**:新脚本最长轮询约 60s 等文件解锁,**只有替换成功才 `start`**,失败会追加写入
     游戏根 `launcher-error.log`;并在关闭前/启动期给出可见的「正在重启」提示。旧脚本重试窗口过短
     且替换失败仍无条件 `start`,导致「离线更新后窗口关闭、不自动重开」。
- **发布物**:Release **20261011** 与离线更新包 `dist\ドットアビスX_更新包_20261011.zip`
  (同一次发布的同一套资产);老玩家直接点「更新」即可(插件与启动器都会更新)。

> 上一版 §8 的「窗口期注意」已随发布失效:本机 `client\` 启动器与 `dist\release_20261011\`
> 的 `launcher_md5` 一致(均为上面的 md5),dev 包可以放心点「更新」。
