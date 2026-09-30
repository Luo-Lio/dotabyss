# GitHub 更新通道(离线版)

玩家启动器的「更新」按钮通过 GitHub Releases 获取增量更新。本文是维护者的发布流程。

---

## 1. 总体流程

```
启动器 → GET api.github.com/repos/<repo>/releases/latest
       → 读附件 version.json(版本号 + 基线 + 各资产 md5 + 文件清单)
       → 基线比对(不一致 → 「需重装」,拒绝增量)
       → 版本比对(相同 → 「已是最新」)
       → 按需执行:client_body → caches_added → catalog → stories → previews → DLL → 文档 → 启动器
       → 每步校验 md5 后落盘;全部成功才写 offline_version.json;换了启动器则自替换重启
```

- 仓库地址写在**包根** `launcher.json` 的 `github_repo`(例 `owner/name`);
  空值 = 更新功能提示"未配置仓库"。
- 网络:先直连,失败自动回退系统代理(有系统代理时直连用 20 秒短超时)。
- **基线(baseline)优先**:`离线包 offline_version.json` 的 `baseline` 与 Release 的不一致时,
  启动器直接拒绝并提示「需重装」——即使版本号巧合相同。

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

> 附件名是启动器的识别依据,大小写敏感;**缺哪个就跳过哪一步**,不会中止整个更新。
> 但**声明了内容却缺附件**会失败关闭(如 `version.json` 里有 `catalog_hash` 但没有
> `catalog_1.bin`),避免"版本号写了、内容没装"的半吊子状态。

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

- **同版本号 = 已是最新**:内容有改动也必须把 `version` 往后调(日期递增)。
- **`baseline` 一旦发布就不要改**,除非确实要让老玩家重装完整包(见 §7)。
- md5 任一不符 → 该步失败只打红字、**不写版本号**,可重试(已装部分保留)。
- 客户端本体清单**不含**插件目录、`_Data\Caches`、`app.info`、启动器 exe 与文档
  (它们各有自己的通道);启动器侧还有白名单/黑名单双重校验,拒绝越界路径。

## 4. 制作与上传(开发机)

```powershell
# 1. 在 client\ 里把该更新的都更新好(插件编译部署、stories.json/封面重导、必要时重新冻结启动器)

# 2. 若游戏本体或素材有更新:重打完整包(它同时产出 local_low_seed\ 与 catalog_seed\)
D:\Python\python.exe tools\launcher\build_full_pack.py --recopy --zip

# 3. 生成发布附件到 dist\release_<版本>\(素材增量用 --caches-since 指旧包目录)
D:\Python\python.exe tools\launcher\build_github_pack.py --version 20260925 --notes "新增 XX 剧情"
D:\Python\python.exe tools\launcher\build_github_pack.py --version 20260925 --notes "新增 XX 剧情" --caches-since "dist\ドットアビスX离线版(旧)"

# 4. 上传(需已登录 gh;标题/说明按需)
gh release create 20260925 --title "离线包 20260925" --notes "新增 XX 剧情" dist\release_20260925\*
```

上传后到 Release 页面确认附件都在、名字没被改写。

## 5. 发布前的自测(无需真实网络)

启动器带离线演练口(`docs\离线版实现说明_开发者必读.md` §4):

```powershell
# 假发布目录:把 release_<版本>\ 拷一份,另写 release.json(GitHub API 的返回体)
# 然后对"旧包目录"跑:
DotabyssOfflineLauncher.exe --game-dir <旧包目录> --release-dir <发布目录> --auto-update out.txt
```

期望结果(用新版启动器跑):

1. 首次:输出 `OK-RESTART`(或 `OK`,若本次不含启动器更新),日志逐条走
   `client_body → caches_added → catalog → stories → previews → DLL → 文档 → 启动器`;
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
