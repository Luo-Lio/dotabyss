using System;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using System.Reflection;
using StoryViewer.Patches;
using UnityEngine;

namespace StoryViewer;

/// <summary>
/// StoryViewer 插件入口:在复制的客户端里提供「剧情选择列表」,
/// 选中后用游戏自身的 Novel 场景与渲染管线播放任意剧情(mas_ / men_ / hmn_ / hmr_ / evs_ 等)。
/// </summary>
[BepInPlugin(Guid, "StoryViewer", Version)]
public class Plugin : BasePlugin
{
    /// <summary>插件唯一标识。</summary>
    public const string Guid = "dotabyss.storyviewer";

    /// <summary>插件版本(必须与 csproj 的 <Version> 保持一致,便于排查与诊断回传)。</summary>
    public const string Version = "0.7.26";

    /// <summary>共享日志器,供行为组件与播放器使用。</summary>
    internal static ManualLogSource Logger;

    /// <summary>游戏到达 Home 场景时自动打开列表(便于把客户端当「剧情播放器」用)。</summary>
    internal static ConfigEntry<bool> AutoOpen;

    /// <summary>切换列表显示的快捷键名(KeyCode 字符串,如 F7)。</summary>
    internal static ConfigEntry<string> ToggleKey;

    /// <summary>界面缩放倍率(0 = 自动:按屏幕高度约 85% 铺开,且不超出屏幕)。</summary>
    internal static ConfigEntry<float> UiScale;

    /// <summary>剧情中「跳到本段结尾」热键(KeyCode 字符串,默认 F8;直接执行游戏自身的跳过)。</summary>
    internal static ConfigEntry<string> SkipKey;

    /// <summary>剧情列表滚轮一格的距离(设计像素;0 = 自动:半行卡片)。</summary>
    internal static ConfigEntry<float> ScrollStep;

    /// <summary>播放时是否跳过 R18 段落(透传给游戏 TopParam.CreateParam)。</summary>
    internal static ConfigEntry<bool> SkipR18;

    /// <summary>R18 分段后篇(第 2/3 段)的「跳过」修复:给游戏没写跳过落点的段补上落点。</summary>
    internal static ConfigEntry<bool> FixR18Skip;

    /// <summary>跳过流程诊断日志(落点注入结果、引擎 Jump/LabelExists/cleanskip 走向)。</summary>
    internal static ConfigEntry<bool> SkipDebug;

    /// <summary>离线启动:注入假 DMM 凭证,跳过启动参数校验(直接双击 exe 时使用)。</summary>
    internal static ConfigEntry<bool> OfflineAuth;

    /// <summary>离线启动时把 API 根地址改到这里(留空 = 不改)。</summary>
    internal static ConfigEntry<string> ApiBase;

    /// <summary>离线模式:启用本地假 API 服务器,把游戏 API 根地址指到本机。</summary>
    internal static ConfigEntry<bool> OfflineApi;

    /// <summary>本地假 API 服务器的监听端口。</summary>
    internal static ConfigEntry<int> OfflineApiPort;

    /// <summary>离线时把资源服务器(Addressables catalog/bundle)也指到本地假服务器。</summary>
    internal static ConfigEntry<bool> RedirectAssetServer;

    /// <summary>用本地缓存(Caches)直接应答 bundle 下载请求。</summary>
    internal static ConfigEntry<bool> ServeCachedBundles;

    /// <summary>指定使用的本地 catalog 文件名(留空 = 取最近写入的一份)。</summary>
    internal static ConfigEntry<string> CatalogFile;

    /// <summary>记录 Addressables 资产管线诊断日志。</summary>
    internal static ConfigEntry<bool> DiagAssets;

    /// <summary>DMM SDK 初始化失败时改判为成功(离线模式:不需要 DMM 账号功能)。</summary>
    internal static ConfigEntry<bool> ForceDmmSdkSuccess;

    /// <summary>离线模式:跳过请求体加密(在线对照/抓包时必须关掉,否则真实服务器解不开正文)。</summary>
    internal static ConfigEntry<bool> SkipRequestEncryption;

    /// <summary>抓包转发:把发往本机假服务器的请求转发到真实上游,并记录完整请求/响应。</summary>
    internal static ConfigEntry<bool> CaptureForward;

    /// <summary>抓包转发的上游基地址(留空 = 用捕获到的原始 API 根地址)。</summary>
    internal static ConfigEntry<string> CaptureUpstream;

    /// <summary>离线时由插件自己注册 Addressables 内容 catalog(补上游戏没走到的资源初始化)。</summary>
    internal static ConfigEntry<bool> BootstrapAssets;

    /// <summary>离线时旁路教学模式门禁(教学状态来自服务器,离线为空会导致播放空引用)。</summary>
    internal static ConfigEntry<bool> SkipTutorial;

    /// <summary>把游戏错误弹窗的内容(错误码/标题/正文)写进日志,便于离线排查。</summary>
    internal static ConfigEntry<bool> ErrorPopupLog;

    /// <summary>离线时跳过游戏错误弹窗(非致命错误弹窗会挡住剧情播放;内容仍写日志)。</summary>
    internal static ConfigEntry<bool> SuppressErrorPopups;

    /// <summary>离线时跳过剧情前的「数据下载」确认弹窗(资源都在本地,无需下载)。</summary>
    internal static ConfigEntry<bool> SkipNovelDownloadPopup;

    /// <summary>游戏原本的 API 根地址(重定向到本机前的值,抓包转发用它做上游)。</summary>
    internal static string OriginalApiBase;

    /// <summary>本地假 API 服务器实例(未启用或启动失败时为 null)。</summary>
    internal static OfflineApiServer ApiServer;

    /// <summary>原版资料室·主线回想是否全开放(忽略通关进度)。</summary>
    internal static ConfigEntry<bool> UnlockMainStory;

    /// <summary>原版资料室·活动回想是否全开放(忽略活动期限)。</summary>
    internal static ConfigEntry<bool> UnlockEventStory;

    /// <summary>角色详情剧情列表是否全显示(忽略亲密度/开放条件)。</summary>
    internal static ConfigEntry<bool> UnlockCharacterStory;

    /// <summary>底部导航是否只留「主页」「任务」。</summary>
    internal static ConfigEntry<bool> HideFooter;

    /// <summary>主页是否隐藏任务/礼物箱/通行证/SP任务/月卡/推荐/建筑按钮。</summary>
    internal static ConfigEntry<bool> HideHomeButtons;

    /// <summary>菜单弹窗是否隐藏好友/道具/VIP/签到等入口。</summary>
    internal static ConfigEntry<bool> HideMenuPopup;

    /// <summary>任务选择页是否隐藏奈落/灾厄/训练所/连合入口。</summary>
    internal static ConfigEntry<bool> HideQuestSelect;

    /// <summary>是否拦截被隐藏功能的场景跳转(横幅等残留入口兜底)。</summary>
    internal static ConfigEntry<bool> BlockScenes;

    /// <summary>是否记录解锁/屏蔽补丁的命中日志(排查用)。</summary>
    internal static ConfigEntry<bool> DebugLog;

    /// <summary>插件加载:注册配置、挂载 UI 行为、安装输入隔离补丁。</summary>
    public override void Load()
    {
        Logger = Log;
        // 只记个数不记内容:启动参数里带 DMM 登录凭证,不进日志。
        Log.LogInfo($"[启动环境] 命令行参数个数={Environment.GetCommandLineArgs().Length}(只为 1 说明是直接双击 exe 启动,缺 DMM 凭证)");
        AutoOpen = Config.Bind("General", "AutoOpen", true,
            "进入 Home 场景时自动打开剧情列表");
        ToggleKey = Config.Bind("General", "ToggleKey", "F7",
            "打开/关闭剧情列表的快捷键(KeyCode 名称,如 F7)");
        UiScale = Config.Bind("General", "UiScale", 0f,
            "界面缩放倍率(0 = 自动:按屏幕高度约 85% 铺开且不超屏;填 0.5~4.0 手动指定,重启游戏后生效)");
        SkipKey = Config.Bind("General", "SkipKey", "F8",
            "剧情中「跳到本段结尾」的快捷键(KeyCode 名称,如 F8):直接执行游戏自身的跳过,不经过按钮与确认弹窗;重启游戏后生效");
        ScrollStep = Config.Bind("General", "ScrollStep", 0f,
            "剧情列表滚轮每格的滚动距离(设计像素、1080p 基准,实际会乘界面缩放;0 = 自动:半行卡片);重启游戏后生效");
        SkipR18 = Config.Bind("General", "SkipR18", false,
            "播放剧情时跳过 R18 段(游戏自身的跳过开关)");
        FixR18Skip = Config.Bind("General", "FixR18Skip", true,
            "修复 R18 分段后篇(第 2/3 段)按「跳过」无反应:游戏只给第 1 段写了跳过落点,这里给后篇补上");
        OfflineAuth = Config.Bind("Offline", "OfflineAuth", false,
            "注入假 DMM 凭证(offline 启动,不登录账号)");
        ApiBase = Config.Bind("Offline", "ApiBase", "",
            "离线启动时把 API 根地址改到这里(留空 = 保持官方地址)");
        OfflineApi = Config.Bind("Offline", "OfflineApi", false,
            "启用本地假 API 服务器(离线模式:把游戏 API 指到本机,响应见 offline-api.log 与 offline_api 目录)");
        OfflineApiPort = Config.Bind("Offline", "ApiPort", 18923,
            "本地假 API 服务器监听端口");
        RedirectAssetServer = Config.Bind("Offline", "RedirectAssetServer", true,
            "离线时把资源服务器地址(Addressables catalog/bundle)也指到本地假服务器");
        ServeCachedBundles = Config.Bind("Offline", "ServeCachedBundles", true,
            "用本地 Caches 缓存应答 bundle 下载请求(catalog 一律用本地自带缓存)");
        CatalogFile = Config.Bind("Offline", "CatalogFile", "",
            "指定使用的本地 catalog 文件名(留空 = 用最近写入的一份)");
        DiagAssets = Config.Bind("Offline", "DiagAssets", false,
            "安装诊断补丁(启动阶段/异步状态机追踪日志、资产管线快照)。默认关闭:这些补丁会给 il2cpp 值类型状态机打钩子,数量多且没必要");
        ForceDmmSdkSuccess = Config.Bind("Offline", "ForceDmmSdkSuccess", false,
            "DMM SDK 初始化失败时改判为成功(离线模式:跳过 DMM 账号初始化,避免「初期化に失敗しました」卡死)");
        SkipRequestEncryption = Config.Bind("Offline", "SkipRequestEncryption", true,
            "离线模式:跳过请求体加密(在线对照/抓包时必须关掉,否则真实服务器解不开正文)");
        CaptureForward = Config.Bind("Offline", "CaptureForward", false,
            "把发往本机假服务器的请求转发到真实上游并抓包(需要能连通官方服务器);结果见 BepInEx\\capture");
        CaptureUpstream = Config.Bind("Offline", "CaptureUpstream", "",
            "抓包转发的上游基地址(留空 = 用游戏原本的 API 根地址)");
        BootstrapAssets = Config.Bind("Offline", "BootstrapAssets", true,
            "离线模式:自己把 Addressables 内容 catalog 注册上(游戏启动流程没走到时也能加载剧情资源)");
        SkipTutorial = Config.Bind("Offline", "SkipTutorial", true,
            "离线模式:旁路教学模式门禁(教学状态来自服务器,离线为空会导致播放时空引用)");
        SuppressErrorPopups = Config.Bind("Offline", "SuppressErrorPopups", true,
            "离线模式:跳过游戏错误弹窗(避免非致命错误挡住剧情播放;内容仍写日志)");
        SkipNovelDownloadPopup = Config.Bind("Offline", "SkipNovelDownloadPopup", true,
            "离线模式:跳过剧情前的「数据下载」确认弹窗(资源都在本地,无需下载)");
        ErrorPopupLog = Config.Bind("Debug", "ErrorPopupLog", true,
            "把游戏错误弹窗的内容(errorCode/title/message)写进日志,便于离线排查");

        UnlockMainStory = Config.Bind("Unlock", "MainStory", true,
            "资料室·主线回想全开放(忽略通关进度)");
        UnlockEventStory = Config.Bind("Unlock", "EventStory", true,
            "资料室·活动回想全开放(忽略活动期限)");
        UnlockCharacterStory = Config.Bind("Unlock", "CharacterStory", true,
            "角色详情剧情列表全显示(忽略亲密度/开放条件)");
        HideFooter = Config.Bind("Hide", "Footer", true,
            "底部导航只留「主页」「任务」(隐藏派对/商店/抽卡/酒馆/探索)");
        HideHomeButtons = Config.Bind("Hide", "HomeButtons", true,
            "主页隐藏任务/礼物箱/通行证/SP任务/月卡/推荐/建筑(保留公告与R18剧情入口)");
        HideMenuPopup = Config.Bind("Hide", "MenuPopup", true,
            "菜单弹窗隐藏好友/道具/VIP/自动分解/签到/数据联动/序列码/客服(保留图书馆/设置/标题/帮助/下载/退出)");
        HideQuestSelect = Config.Bind("Hide", "QuestSelect", true,
            "任务选择页隐藏奈落/灾厄/训练所/连合(保留主线/支线剧情)");
        BlockScenes = Config.Bind("Hide", "BlockScenes", true,
            "拦截被隐藏功能的场景跳转(横幅等残留入口兜底)");
        DebugLog = Config.Bind("Debug", "LogPatches", true,
            "记录解锁/屏蔽补丁的命中日志(排查用)");
        SkipDebug = Config.Bind("Debug", "SkipDebug", true,
            "记录跳过流程诊断日志(落点注入、引擎 Jump/LabelExists/cleanskip 执行轨迹);排查完可关");

        AddComponent<ViewerBehaviour>();
        InstallUnobservedExceptionHook();
        DeployRuntimeConfigIfNeeded();
        if (OfflineApi.Value)
        {
            ApiServer = new OfflineApiServer(OfflineApiPort.Value);
            ApiServer.Start();
            EnableOfflineMode();
        }
        PatchManager.Install();

        // 版本自检:Plugin.Version 常量必须与程序集版本(csproj <Version>)一致。
        // 升版本时若只改了 csproj 忘了改这个常量,日志/顶栏/诊断回传的 plugin_version 会错报。
        try
        {
            string asmVer = typeof(Plugin).Assembly
                .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
                .InformationalVersion ?? "";
            int plus = asmVer.IndexOf('+');
            if (plus >= 0) asmVer = asmVer.Substring(0, plus);
            if (!string.IsNullOrEmpty(asmVer) && asmVer != Version)
                Log.LogWarning($"[版本自检] Plugin.Version 常量={Version} 与程序集版本={asmVer} 不一致:升版本时忘了同步常量,诊断回传的 plugin_version 会错报!");
        }
        catch { /* 自检失败不影响加载 */ }

        Log.LogInfo($"StoryViewer {Version} 加载完成:按 {ToggleKey.Value} 打开剧情列表,剧情中按 {SkipKey.Value} 跳到本段结尾");
    }

    /// <summary>
    /// 把 UniTask 的"未观察异常"回调接到插件日志上。
    /// <para>
    /// 离线排查用:若某个 async 流程内部抛异常被吞掉,表现往往是"流程停住但没有任何报错",
    /// 这里能把异常内容和堆栈打到 LogOutput.log,定位卡点根因。
    /// </para>
    /// 安装失败不影响插件其它功能。
    /// </summary>
    private void InstallUnobservedExceptionHook()
    {
        try
        {
            var il2cppHandler =
                Il2CppInterop.Runtime.DelegateSupport.ConvertDelegate<Il2CppSystem.Action<Il2CppSystem.Exception>>(
                    new Action<Il2CppSystem.Exception>(e =>
                    {
                        // 钩子自身绝不能抛:一旦抛出会反过来破坏调用它的任务链。
                        try
                        {
                            string msg = e?.Message;
                            if (NoteHomeCosmeticMasterData(msg)) return;
                            string stack = e?.StackTrace;
                            Log.LogError($"[未观察异常] {msg}\n{stack}");
                        }
                        catch
                        {
                            Log.LogError("[未观察异常] 异常对象无法读取详细信息");
                        }
                    }));
            var add = typeof(Cysharp.Threading.Tasks.UniTaskScheduler).GetMethod(
                "add_UnobservedTaskException",
                System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static);
            if (add == null)
            {
                Log.LogWarning("[未观察异常] 钩子未安装:找不到 UniTaskScheduler.add_UnobservedTaskException");
            }
            else
            {
                add.Invoke(null, new object[] { il2cppHandler });
                Log.LogInfo("[未观察异常] UniTask 钩子已安装");
            }
        }
        catch (Exception e)
        {
            Log.LogWarning($"[未观察异常] UniTask 钩子安装失败: {e.Message}");
        }

        try
        {
            System.Threading.Tasks.TaskScheduler.UnobservedTaskException += (_, e) =>
                Log.LogError($"[未观察异常/托管] {e.Exception.GetType().Name}: {e.Exception.Message}\n{e.Exception.StackTrace}");
        }
        catch (Exception e)
        {
            Log.LogWarning($"[未观察异常] 托管钩子安装失败: {e.Message}");
        }
    }

    /// <summary>
    /// 打开游戏自带的「跳过版本检查」静态开关,并记录离线所需的运行时版本信息
    /// (假 API 的响应信封要用它填 versions,避免客户端对 null 数组做 Contains 崩溃)。
    /// </summary>
    private void EnableOfflineMode()
    {
        // 在线对照/抓包轮(SkipRequestEncryption=false)不动这个开关:让真实版本校验照常跑,
        // 这样能看出"上游是否要求更新客户端"这类真实差异。
        if (Plugin.SkipRequestEncryption.Value)
        {
            try
            {
                Absf.Api.ApiManager.SkipCheckVersion = "1";
                Log.LogInfo("离线模式:已打开 SkipCheckVersion");
            }
            catch (Exception e)
            {
                Log.LogWarning($"离线模式:SkipCheckVersion 设置失败: {e.Message}");
            }
        }
        else
        {
            Log.LogInfo("在线对照模式:保留游戏自身的版本校验(SkipCheckVersion 未设置)");
        }
        try
        {
            Log.LogInfo(
                "离线模式版本信息: app=" + Absf.RuntimeConfig.GetAppVersionCode() +
                " bundle=" + Absf.RuntimeConfig.GetBundleVersion() +
                " product=" + Absf.RuntimeConfig.GetProductName() +
                " env=" + Absf.RuntimeConfig.GetEnvironment());
        }
        catch (Exception e)
        {
            Log.LogWarning($"离线模式:版本信息读取失败: {e.Message}");
        }
    }

    /// <summary>是否已就地把首页建筑主数据缺失降级为友好提示(只播报一次)。</summary>
    private bool _homeCosmeticNoted;

    /// <summary>
    /// 0.7.26:离线固有 —— 首页建筑主数据(MBuildings)不可用的静音处理。
    /// <para>
    /// <c>TopScene.CreateBuildingModelListAsync → MasterDataStore.GetCache&lt;MBuildings&gt;()</c> 抛
    /// <c>MBuildings not found</c> 是离线版固有的:MasterDataStore 靠下载/清单管线把各表读进**内存**,
    /// 离线时这条管线不会填充 m_buildings——把磁盘 <c>DownloadCache\&lt;hash&gt;.dat</c> 补上也没用
    /// (新机模拟已验证:文件在、内容含 m_buildings,进 Home 仍 not found)。所以之前 0.7.24 的
    /// <c>SeedMasterDataIfNeeded</c> 前提就是错的,已移除。
    /// 关键点:这**只影响首页建筑渲染**,剧情播出不依赖它(报错照样进 Home、列表照开、剧情照播)。
    /// 因此这类未观察异常不再刷整页堆栈,只播报一次友好提示。返回 true 表示已就地处理、调用方无需再记。
    /// </para>
    /// </summary>
    private bool NoteHomeCosmeticMasterData(string msg)
    {
        if (string.IsNullOrEmpty(msg)) return false;
        if (!msg.Contains("MBuildings")) return false;
        if (!_homeCosmeticNoted)
        {
            _homeCosmeticNoted = true;
            Log.LogInfo("[首页建筑] 离线无主数据(MBuildings not found):仅影响首页建筑渲染,剧情播出不受影响(此提示只显示一次)。");
        }
        return true;
    }

    /// <summary>
    /// 0.7.22:部署 AbsfRuntimeConfig.dat(如果 persistentDataPath 下缺失)。
    /// <para>
    /// 全新安装的玩家从未成功联网启动过 → 游戏持久化目录里没有这个配置文件 →
    /// AppEngine.InitializeServicesAsync 走到 OnServiceRegistered 时读到 null → 崩溃。
    /// 本方法在插件加载早期(场景尚未开始)检测并补全,让引擎初始化能正常完成。
    /// </para>
    /// </summary>
    private void DeployRuntimeConfigIfNeeded()
    {
        try
        {
            string persistent = UnityEngine.Application.persistentDataPath;
            string target = System.IO.Path.Combine(persistent, "AbsfRuntimeConfig.dat");
            if (System.IO.File.Exists(target)) return;

            // 从嵌入资源释放
            var asm = typeof(Plugin).Assembly;
            string resName = null;
            foreach (var n in asm.GetManifestResourceNames())
            {
                if (n.EndsWith("AbsfRuntimeConfig.dat", StringComparison.OrdinalIgnoreCase))
                { resName = n; break; }
            }
            if (resName == null)
            {
                Log.LogWarning("[启动容错] 嵌入资源 AbsfRuntimeConfig.dat 未编入 DLL,无法补全");
                return;
            }
            using (var stream = asm.GetManifestResourceStream(resName))
            {
                System.IO.Directory.CreateDirectory(persistent);
                using (var fs = System.IO.File.Create(target))
                    stream.CopyTo(fs);
            }
            Log.LogInfo($"[启动容错] 已释放 AbsfRuntimeConfig.dat → {target} ({new System.IO.FileInfo(target).Length}B)");
        }
        catch (Exception e)
        {
            Log.LogWarning($"[启动容错] AbsfRuntimeConfig 部署失败: {e.GetType().Name}: {e.Message}");
        }
    }

    /// <summary>插件卸载:停止离线 API 服务器,避免占用端口。</summary>
    public override bool Unload()
    {
        ApiServer?.Dispose();
        ApiServer = null;
        return true;
    }
}
