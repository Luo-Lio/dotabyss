# dotabyss(ドットアビスX)CG 离线导出工具

从本机已缓存的 Unity Addressables bundle 里导出角色 / 剧情 CG 与动态素材,生成可离线浏览的单文件图库。

- **只读**:不修改游戏文件、不注入、不联网;所有素材来自游戏自己的 bundle 缓存。
- **当前范围**:图像(立绘 / cut-in / 背景 / 剧情缩略图 / 图标)、动态素材(Live2D 模型与动作、Spine 骨架)、
  剧情索引(主线/个人/角色/酒馆/支线,按角色聚合)、**剧情离线播放**(脚本 → 事件流,见下)。
- 产物默认写入 `output/`(已 gitignore)。

## 离线版(整包)与启动器

本项目同时维护**可直接游玩的离线整包**:游戏本体 + BepInEx + StoryViewer 插件 + 图形启动器
(约 8 GB,唯一事实源在 `client/`,已 gitignore)。玩家向文档在 `tools/launcher/player_docs/`,
打包时复制到包根;维护流程见 `docs/` 下的开发者文档。

```powershell
# 冻结启动器到 client\(PyInstaller onefile + 冒烟自检)
pwsh -File tools\launcher\freeze_launcher.ps1

# 构建完整包(排除开发产物 + 校验 + 离线身份 + catalog 种子;--zip 出压缩包;--repo owner/name 写更新仓库)
& D:\Python\python.exe tools\launcher\build_full_pack.py --zip

# 构建 GitHub 更新附件(含客户端本体/素材增量/catalog,见 docs\GitHub更新流程.md)
& D:\Python\python.exe tools\launcher\build_github_pack.py --version 20260925
& D:\Python\python.exe tools\launcher\build_github_pack.py --version 20260925 --caches-since "dist\旧包目录"

# 启动器/打包脚本的单元测试(106 + 24 + 11 项)
& D:\Python\python.exe tools\launcher\test_offline_core.py
& D:\Python\python.exe tools\launcher\test_launcher_update.py
& D:\Python\python.exe tools\launcher\test_pack_tools.py
```

- 离线包要点:身份隔离(`app.info` 产品名 `*_offline`,存档与在线版完全分开)、
  包内 `catalog_seed\`(新机器首启的关键)、`baseline` 基线门禁(基线不符必须重装完整包)、
  更新通道覆盖客户端本体与素材增量。
- 开发者文档:[`docs/离线版实现说明_开发者必读.md`](docs/离线版实现说明_开发者必读.md)、
  [`docs/GitHub更新流程.md`](docs/GitHub更新流程.md)、
  [`docs/日常更新流程.md`](docs/日常更新流程.md)(游戏更新后"同步→打包→发布"的逐步操作手册)。

## 用法

```powershell
# 1. 导出全部已缓存资源(增量:已存在的产物会跳过)
& D:\Python\python.exe -m tools.export

# 2. 只看缓存里各类资源的数量,不导出
& D:\Python\python.exe -m tools.export --inventory

# 3. 重新导出(覆盖);--skip-dynamic 跳过动态素材,--skip-scripts 跳过剧情脚本
& D:\Python\python.exe -m tools.export --force --only charastand
& D:\Python\python.exe -m tools.export --dynamic-limit 3

# 4. 只刷新剧情索引 + 剧情脚本(快,不重扫图像)
& D:\Python\python.exe -m tools.export --only stories --skip-dynamic

# 5. 生成/刷新单文件图库
& D:\Python\python.exe -m tools.gallery

# 6. 校验产物与当前缓存是否一致(含剧情脚本)
& D:\Python\python.exe -m tools.verify
```

依赖:Python 3.13 + `UnityPy`、`Pillow`、`msgpack`。游戏装在别处时用 `--game-dir` 或环境变量
`DOTABYSS_GAME_DIR` / `DOTABYSS_OUT_DIR` 覆盖。

## 目录

```
tools/
  paths.py       路径发现(游戏目录 / 缓存 / 用户数据 / 输出)
  catalog.py     Addressables catalog 解析(bundle 名 ↔ md5 ↔ 缓存目录名)
  masterdata.py  master data(msgpack)读取与角色/皮肤/背景名称映射
  story.py       剧情索引(剧情表 → 角色 / 系列 / 条目,数量随数据)
  scenario.py    剧情脚本解析(命令式 .txt → 离线播放事件流 + 脚本 JS)
  uilayout.py    Unity UI 预制体布局求解(RectTransform 锚点/层级)
  extract.py     图像类导出(立绘合成 / cut-in / 背景 / 剧情图 / 图标)
  dynamic.py     动态素材导出(Live2D moc3+动作+纹理 / Spine skel+atlas+png)
  export.py      CLI:扫描缓存 → 导出 → 写 manifest.json
  gallery.py     manifest.json → 单文件离线图库 gallery.html
  verify.py      产物一致性校验
  launcher/      离线启动器与打包:dotabyss_launcher.py / dotabyss_offline_core.py /
                 dotabyss_pack_tools.py、freeze_launcher.ps1、build_full_pack.py、
                 build_github_pack.py、check_health.bat、player_docs/(玩家文档)、单元测试
  client-mod/    StoryViewer 插件的源码与编译/部署脚本
output/          产物(gitignore)
  manifest.json    全部条目 + 剧情索引 + 剧情脚本 + 动态素材 + 引用型/失败记录
  gallery.html     图库(内嵌裁剪后的数据,图片按相对路径引用)
  charastand/<ID>.png           立绘合成整图(剧情播放用;「素材」视图里不列)
  charastand/faces/<ID>/<表情>.png  表情差分图层
  cutin|bg|story|icon/<ID>.png
  emo/<名字>.png               情绪符号图标(sdemo,剧情播放用;「素材」视图里不列)
  stories/<剧情key>.js          剧情事件流(可 <script src> 直接加载,file:// 可用)
  live2d/<模型id>/<模型id>.moc3          Live2D 模型(标准 moc3)
  live2d/<模型id>/texture_NN.png         绘制序纹理(编号即 Cubism 的 texture 索引)
  live2d/<模型id>/motions/<动作>.motion3.json  演出动作(标准 Cubism 动作格式)
  live2d/<模型id>/model3.json            最小 model3.json(纹理/动作引用)
  spine/<boss>/<boss>.skel|.atlas|.png  Spine 4.1 骨架三件套
```

## 图库的三种视图

`gallery.html` 是单文件、零依赖、可 `file://` 直接打开的图录:

- **素材** —— cut-in / 背景 / 剧情图 / 图标;分类是**开关**(可多选),另有「仅角色相关」筛选。
  (立绘与情绪符号按需求不在此视图列出;数据仍保留在 `manifest.json`、`charastand/`、`emo/`,供剧情播放使用。)
- **剧情** —— 按角色聚合并按系列分组,条目数完全取自 master data(新增/解锁的剧情会自动出现);
  带 `▶ 播放` 标记的条目可点开离线播放(键鼠:←/→ 或空格翻页、Esc 退出、`自动` 连播、`角色` 开关)。
- **动态** —— Live2D 模型与 Spine 骨架一览:模型 id、剧情键、角色、moc3 大小、动作数、纹理数,
  并可查看动作列表。Live2D 卡片封面用同角色立绘,详情里展示的是模型图集(非渲染效果)。

## 剧情播放(离线,实测)

数据源:catalog 组 `r18-only-novel` 里的 `<key>_<key>.txt_<md5>.bundle`(TextAsset),脚本是
**逗号分隔、逐行一条命令**的纯文本;`tools/scenario.py` 把它编译成紧凑事件流 `stories/<key>.js`
(挂到 `window.STORY[key]`),播放器只还原「背景 + 角色 + 文本 + 表情 + 情绪符号」,其余命令(动效/音频/镜头/震屏/
遮罩/时间轴…)忽略——它们不影响这些要素的最终状态。角色位置与显隐用 CSS 过渡播放(入场淡入、走位平移)。

| 解析项 | 命令(实测) | 处理 |
| --- | --- | --- |
| 对白 | `message` / `dotmessage` / `l2dmessage` | 说话人 + 文本(+角色槽/对象名) |
| 旁白 | `messageTextCenter` / `messageTextUnder` | 居中 / 底部旁白 |
| 背景 | `bg` / `subimage,UI/BG/Novel/...` | 切 `bg/<id>.png` |
| 载入角色 | `charaload`(载入即可见)/ `objectload,...,CHARA,...`(默认隐藏) | 槽位 + 立绘 id + 名字 |
| 显隐 | `objectshow` / `objecthide` / `charashow*` / `charahide`(含 `async*`,共 8 种写法) | 显示 / 隐藏(播放器用淡入淡出过渡) |
| 位置 | `charamove,...,X,<x>` / `dotmove`(像素舞台) | 归一成舞台百分比(见下) |
| 缩放/表情 | `charascale` / `charaface`(含 `async*`) | 倍率 / `FaceXxx`、`EyeClose` |
| 情绪符号 | `charaemo`(含 `async*`) / `emodelete` | 漫画式符号(`Anger`/`Flower`/`Exclamation`…),`STOP` 只演一段、`CONT` 持续到被替换 |
| 清场 | `cleanall` | 清空台上角色 |
| 跳转 | `:<标签>` + `labeljump` | 解析期直接跳(带步数上限防环) |

- **坐标归一**:立绘剧情 `charamove` 的 X 是相对中心的像素(设计稿宽 1920)→ `50 + x/19.2` %;
  像素剧情 `dotmove` 的 X 是 0..20 的舞台单位(10 居中,负数为台外)→ `x*5` %。
- **表情差分**:立绘图集会**紧致裁剪**掉透明边(`m_Rect` ≠ `textureRect`),表情层必须先按
  `textureRectOffset` 还原到设计尺寸再叠加,否则五官会被拉伸错位——`extract.untrim_image()` 负责这件事。
- **前篇/后篇**:脚本 key 末位是段(`...11` 前篇 / `...12` 后篇),播放时自动连播并插入「―― 後篇 ――」;
  索引只收录前篇 key,后篇沿用其元数据。
- **已知限制**:
  - 像素剧情(主线大量使用)的背景是**运行时 3D 舞台**(`dotbgload` 载入 stage prefab 渲染),离线不可复现:
    播放器显示舞台底色 + 左上角提示;同场景里的 `bg,abg*` 正常显示(另有 `abg18200a` 之类 20×20 纯黑占位图,
    播放器会自动忽略以免整屏死黑)。
  - 无立绘的单位(如主人公的像素骨架 `300101000`)离线无法渲染,播放器跳过该角色,其余角色正常。
  - **个人剧情/角色剧情/支线没有 Live2D**:全 catalog 的 Live2D 素材(10387 条)都挂在酒馆剧情 `hmr_` 上,
    `men_`/`hmn_`/`evs_` 脚本里 `l2dmessage` 出现 0 次——游戏里这些剧情本来就是「立绘 + 表情差分 + 情绪符号」,
    不存在我们漏导的动态素材。Live2D 剧情(`hmr_l2d*`,203 条)只有文本与背景,模型不渲染(见下)。
  - 情绪符号取的是游戏原生图标(23 个),游戏里的逐帧动画与角色反应动作(`charareaction` 的 Jump 等)未播放。

## 剧情索引(实测)

| 系列 | key 前缀 | 表 | 每角色数量(实测) | 说明 |
| --- | --- | --- | --- | --- |
| 主线剧情 | `mas_` | `m_novel_mains`(+`m_novel_prologues`/`m_novel_others`) | 全 118 话 | 按章节(砂嵐/氷河/火山/闇/廃墟/光/煉獄/遺跡の階層)排序,含序章 |
| 个人剧情 | `men_` | `m_novel_homes` | 2~3 | 「〇〇の日常そのN」 |
| 角色剧情 | `hmn_` | `m_novel_characters` | 3 | 全年龄角色剧情,解锁条件 絆Lv 1/5/15 |
| 酒馆剧情 | `hmr_` | `m_novel_characters` | 2~4 | 娼館/酒場剧情;4 = 含衣装剧情(`m_novel_character_skins`) |
| 支线剧情 | `evs_` | `m_novel_side_stories`(+`m_novel_events`) | — | 活动支线 |

- 「酒場」是「娼館」的全年龄表记(metadata 里为「酒場(娼館の全年齢表記)ボタン」),故酒馆剧情 = `hmr_` 系列。
- 每个数字段末位是「段」(如 `hmr_10010100011` 第一话前篇 / `...12` 后篇);Live2D 模型按去掉末位的组键关联到剧情。
- 剧情缩略图资产名为 `story_s_<组键>`(仅酒馆剧情有),导出后自动回填为剧情封面。
- **不写死数量**:角色有几个个人剧情、几个酒馆剧情由表数据决定,后续版本新增会自动体现。

## 动态素材(实测)

| 类别 | 位置 | 形态 | 导出格式 |
| --- | --- | --- | --- |
| Live2D 模型 | `mainchara_<剧情key>_l2d_<id>_l2d_<id>.asset` | MonoBehaviour `_bytes`(头 4 字节 `MOC3`) | 原样导出 `.moc3` |
| Live2D 动作 | `..._l2d_<id>_(add)animations_<动作>.fade.asset` | `ParameterIds[]` + `ParameterCurves[]`(Unity AnimationCurve 关键帧) | 转成标准 `.motion3.json`(线性段) |
| Live2D 纹理 | `..._l2d_<id>_l2d_<id>.prefab` | 预制体内的 Texture2D(编号 = 绘制序) | `texture_NN.png`,并生成最小 `model3.json` |
| Spine 骨架 | `spine/boss/<boss>/spinesd_skeletondata.asset` | 内含 TextAsset `SpineSD.skel`(二进制,实测 4.1.23) | `<boss>.skel` |
| Spine 图集 | `..._spinesd.atlas.txt` / `..._spinesd_atlas.asset` | 文本 atlas + Texture2D | `<boss>.atlas`(首页图像名改写为 `<boss>.png`)+ `<boss>.png` |
| 影片 | `r18-only-movie-cri` | 本地只有 ~2.5KB 存根,实片走 CRI 流式 | 只登记状态,不导出 |

导出的是**通用格式**,但因 Live2D/Spine 运行时(官方 Cubism Core / spine-webgl)有各自的许可与分发条款,
本仓库不内置运行时;`gallery.html` 对这些动态素材只做「编目与预览」,不播放(剧情播放只还原文本/背景/立绘)。

## 更新素材

游戏更新或游戏内继续下载后,重跑一次 `tools.export` 即可:它按「bundle 名 + md5」判定,
已导出的跳过,新增/变更的才重新解包;`tools.verify` 可核对产物与缓存是否一致。
游戏正在批量下载时,`verify` 会把「导出之后才落盘的 bundle」单列为**滞后**,重跑 `export` 即收敛。

## 后续

- [ ] Live2D/Spine 离线播放器(需引入官方运行时;格式已就绪)—— 接上后像素剧情的角色与背景可一并还原。
- [ ] 取一次 CDN 前缀,支持导出未缓存内容与影片实片(需要抓一次请求或跑一次探针插件)。
