using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace StoryViewer.Patches;

/// <summary>
/// 启动链诊断(2026-09-23)。
/// <para>
/// 背景:离线模式下 catalog 已能成功加载(本地假服务器供给 + Addressables 自身缓存命中),
/// 但游戏到达 Title 场景后停在加载画面:帧数持续上涨、无任何 bundle 请求、无报错。
/// 需要定位「catalog 加载完成之后,启动流程到底卡在哪一步」。
/// </para>
/// <para>
/// 做法:对「通用初始化(CommonInitializationService) → 标题场景(TopScene/TopView) → 主数据(MasterDataStore)」
/// 的每个步骤做入口打点(异步方法只记入口;布尔判定用 Postfix 记返回值)。
/// 日志格式:<c>[启动] HH:mm:ss.fff 步骤名</c>;最后一条"进入 Xxx"就是卡住的步骤。
/// </para>
/// <para>
/// 只在 <see cref="Plugin.OfflineApi"/> + <see cref="Plugin.DiagAssets"/> 同时打开时输出;
/// 每个 key 最多 8 条、总量 500 条,避免刷爆日志。
/// </para>
/// </summary>
internal static class StartupDiag
{
    /// <summary>日志总条数上限。</summary>
    internal const int MaxTotal = 500;

    /// <summary>单个 key 的日志条数上限(防止循环里刷屏)。</summary>
    internal const int MaxPerKey = 8;

    private static readonly Dictionary<string, int> Counts = new(StringComparer.Ordinal);
    private static readonly object Sync = new();
    private static int _total;

    /// <summary>记一条启动链诊断日志(带时间戳,便于与 LogOutput/Player.log 对时间线)。</summary>
    internal static void Log(string key, string message)
    {
        if (!AssetDiag.Diag)
            return;
        lock (Sync)
        {
            if (_total >= MaxTotal)
                return;
            Counts.TryGetValue(key, out int n);
            if (n >= MaxPerKey)
                return;
            Counts[key] = n + 1;
            _total++;
        }
        Plugin.Logger.LogInfo($"[启动] {DateTime.Now:HH:mm:ss.fff} {message}");
    }

    /// <summary>按名字解析方法(含私有/静态);解析失败返回 null,由 PatchManager 记录该类安装失败。</summary>
    internal static MethodBase Of(Type owner, string name) => AccessTools.Method(owner, name);

    /// <summary>按名字解析嵌套类型(如编译器生成的 <c>__c</c>)。</summary>
    internal static Type Inner(Type owner, string name) => AccessTools.Inner(owner, name);
}

// ───────────────────────── 通用初始化链(Project.CommonInitializationService) ─────────────────────────

/// <summary>OnBootAsync:整个启动流程的入口。</summary>
[HarmonyPatch]
internal static class Boot_OnBoot
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "OnBootAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OnBootAsync", "进入 CommonInitializationService.OnBootAsync");
}

/// <summary>OnRebootAsync:11:45 那轮出现过"重启式"二次请求,单独打点确认。</summary>
[HarmonyPatch]
internal static class Boot_OnReboot
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "OnRebootAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OnRebootAsync", "进入 CommonInitializationService.OnRebootAsync");
}

/// <summary>InitializeOrLoginDmmSdkAsync:DMM SDK 初始化/登录。</summary>
[HarmonyPatch]
internal static class Boot_InitOrLoginDmmSdk
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "InitializeOrLoginDmmSdkAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("InitOrLoginDmmSdk", "进入 InitializeOrLoginDmmSdkAsync");
}

/// <summary>CheckPermissionAsync:权限检查(Windows 上一般直接过)。</summary>
[HarmonyPatch]
internal static class Boot_CheckPermission
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "CheckPermissionAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("CheckPermission", "进入 CheckPermissionAsync");
}

/// <summary>OnNoticeFirstUpdateAsync:公告/首次更新检查(2 次 maintenance 请求就在这段)。</summary>
[HarmonyPatch]
internal static class Boot_OnNoticeFirstUpdate
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "OnNoticeFirstUpdateAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OnNoticeFirstUpdate", "进入 OnNoticeFirstUpdateAsync");
}

/// <summary>OnTitleInitializeAsync:标题初始化(返回 MaintenanceModel)。</summary>
[HarmonyPatch]
internal static class Boot_OnTitleInitialize
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "OnTitleInitializeAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OnTitleInitialize", "进入 OnTitleInitializeAsync");
}

/// <summary>OnLoginAsync:用假凭证登录(参数含 TermsAgree[])。</summary>
[HarmonyPatch]
internal static class Boot_OnLogin
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "OnLoginAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OnLogin", "进入 OnLoginAsync");
}

/// <summary>OnDataInitializeAsync:主数据初始化(卡主数据的嫌疑点之一)。</summary>
[HarmonyPatch]
internal static class Boot_OnDataInitialize
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "OnDataInitializeAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OnDataInitialize", "进入 OnDataInitializeAsync");
}

/// <summary>InitializeAssetLoaderAsync:资产层初始化(实机已确认走到 catalog 下载并成功)。</summary>
[HarmonyPatch]
internal static class Boot_InitAssetLoader
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "InitializeAssetLoaderAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("InitAssetLoader", "进入 InitializeAssetLoaderAsync");
}

/// <summary>CalcReleasePlatformAssetVersion:计算要用的资产版本(记返回值,确认不是空/异常值)。</summary>
[HarmonyPatch]
internal static class Boot_CalcReleaseAssetVersion
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.CommonInitializationService), "CalcReleasePlatformAssetVersion");

    [HarmonyPostfix]
    private static void Postfix(ref string __result) =>
        StartupDiag.Log("CalcReleaseAssetVersion", $"CalcReleasePlatformAssetVersion → '{__result}'");
}

// ───────────────────────── 标题场景链(Project.Title.TopScene) ─────────────────────────

/// <summary>OnInitializeImplAsync:标题场景初始化的主流程。</summary>
[HarmonyPatch]
internal static class Title_OnInitializeImpl
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "OnInitializeImplAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OnInitializeImpl", "进入 TopScene.OnInitializeImplAsync");
}

/// <summary>OnEnteredImplAsync:标题场景"已进入"回调(PlayIn/加载演出一般在这里)。</summary>
[HarmonyPatch]
internal static class Title_OnEnteredImpl
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "OnEnteredImplAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OnEnteredImpl", "进入 TopScene.OnEnteredImplAsync");
}

/// <summary>CheckTermsVersion:规约版本比对(用服务器返回的 TermsFetch 数据)。</summary>
[HarmonyPatch]
internal static class Title_CheckTermsVersion
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "CheckTermsVersion");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("CheckTermsVersion", "进入 TopScene.CheckTermsVersion");
}

/// <summary>GetCurrentSchedule:取当前日程(标题背景/公告用)。</summary>
[HarmonyPatch]
internal static class Title_GetCurrentSchedule
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "GetCurrentSchedule");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("GetCurrentSchedule", "进入 TopScene.GetCurrentSchedule");
}

/// <summary>ConfirmTermsAgreementsPopups:等待用户确认规约弹窗(返回 bool,可能永久等待)。</summary>
[HarmonyPatch]
internal static class Title_ConfirmTermsPopups
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "ConfirmTermsAgreementsPopups");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("ConfirmTermsPopups", "进入 ConfirmTermsAgreementsPopups(等待规约确认)");
}

/// <summary>TryShowTermsAgreementPopupAsync:尝试弹规约同意弹窗。</summary>
[HarmonyPatch]
internal static class Title_TryShowTermsPopup
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "TryShowTermsAgreementPopupAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TryShowTermsPopup", "进入 TryShowTermsAgreementPopupAsync");
}

/// <summary>ShowTermsAgreePopup:新用户规约弹窗(内部可能等用户点击)。</summary>
[HarmonyPatch]
internal static class Title_ShowTermsAgreePopup
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "ShowTermsAgreePopup");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("ShowTermsAgreePopup", "进入 ShowTermsAgreePopup");
}

/// <summary>ShowTermsAgreePopupForExistingUser:老用户规约弹窗。</summary>
[HarmonyPatch]
internal static class Title_ShowTermsAgreePopupExisting
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "ShowTermsAgreePopupForExistingUser");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("ShowTermsAgreeForExisting", "进入 ShowTermsAgreePopupForExistingUser");
}

/// <summary>LoadTitleBGScheduleAsync:加载标题背景日程(需要远端数据)。</summary>
[HarmonyPatch]
internal static class Title_LoadTitleBGSchedule
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "LoadTitleBGScheduleAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("LoadTitleBGSchedule", "进入 LoadTitleBGScheduleAsync");
}

/// <summary>LoadVoiceAsync:标题语音加载(资产管线)。</summary>
[HarmonyPatch]
internal static class Title_LoadVoice
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "LoadVoiceAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("LoadVoice", "进入 LoadVoiceAsync");
}

/// <summary>PlayBgmAsync:标题 BGM 播放(资产管线)。</summary>
[HarmonyPatch]
internal static class Title_PlayBgm
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "PlayBgmAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("PlayBgm", "进入 PlayBgmAsync");
}

/// <summary>ATTPermissionCheck:追踪权限检查(iOS 语义,Windows 应直接过)。</summary>
[HarmonyPatch]
internal static class Title_AttPermissionCheck
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "ATTPermissionCheck");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("AttPermissionCheck", "进入 ATTPermissionCheck");
}

/// <summary>ChangeToTitleLoadingScene:切到"标题加载"场景(就是用户看到的加载画面的嫌疑来源)。</summary>
[HarmonyPatch]
internal static class Title_ChangeToTitleLoadingScene
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "ChangeToTitleLoadingScene");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("ChangeToTitleLoadingScene", "进入 ChangeToTitleLoadingScene(切标题加载场景)");
}

/// <summary>TryChangeToTitleLoadingSceneAsync:按需切标题加载场景。</summary>
[HarmonyPatch]
internal static class Title_TryChangeToTitleLoadingScene
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "TryChangeToTitleLoadingSceneAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TryChangeToTitleLoadingScene", "进入 TryChangeToTitleLoadingSceneAsync");
}

/// <summary>ChangeToHomeSceneAsync:标题 → 主页的切换(卡点的最终出口)。</summary>
[HarmonyPatch]
internal static class Title_ChangeToHomeScene
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "ChangeToHomeSceneAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("ChangeToHomeScene", "进入 ChangeToHomeSceneAsync(开始切主页)");
}

/// <summary>OpenUpdateNamePopupAsync:改名弹窗(等用户输入)。</summary>
[HarmonyPatch]
internal static class Title_OpenUpdateNamePopup
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "OpenUpdateNamePopupAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OpenUpdateNamePopup", "进入 OpenUpdateNamePopupAsync");
}

/// <summary>NotifyDmmSdkBootFailureIfNeededAsync:DMM SDK 启动失败提示。</summary>
[HarmonyPatch]
internal static class Title_NotifyDmmSdkBootFailure
{
    /// <summary>只在「强制忽略 DMM SDK 失败」时安装。</summary>
    public static bool Enabled => Plugin.ForceDmmSdkSuccess.Value;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "NotifyDmmSdkBootFailureIfNeededAsync");

    [HarmonyPrefix]
    private static bool Prefix(ref Cysharp.Threading.Tasks.UniTask __result)
    {
        StartupDiag.Log("NotifyDmmSdkBootFailure", "进入 NotifyDmmSdkBootFailureIfNeededAsync");
        DmmSdkState.Log("弹窗判定时");
        if (Plugin.ForceDmmSdkSuccess.Value)
        {
            // 离线档必须跳过:游戏的 HasDmmSdkBootFailure 是原生字段(属性 getter 会被 AOT 内联,
            // 打 getter 的补丁根本不会被调用),这个弹窗会盖在游戏界面最上层挡住所有点击
            // (2026-09-23 22:24 轮:F7 选剧情后 Novel 场景已在后面正常加载,却被它挡住"数据下载"确认框)。
            StartupDiag.Log("NotifyDmmSdkBootFailureSkipped", "离线模式:跳过 DMM SDK 失败弹窗");
            __result = Cysharp.Threading.Tasks.UniTask.CompletedTask;
            return false;
        }
        return true;
    }
}

/// <summary>规约弹窗判定 b__30_0:true = 该条规约需要弹窗确认。</summary>
[HarmonyPatch]
internal static class Title_PredConfirmPopup
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Project.Title.TopScene), "_ConfirmTermsAgreementsPopups_b__30_0");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result) =>
        StartupDiag.Log("PredConfirmPopup", $"规约弹窗判定 b__30_0 → {__result}");
}

/// <summary>规约展示判定 b__35_0:true = 需要展示规约同意。</summary>
[HarmonyPatch]
internal static class Title_PredTryShowTerms
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Project.Title.TopScene), "_TryShowTermsAgreementPopupAsync_b__35_0");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result) =>
        StartupDiag.Log("PredTryShowTerms", $"规约展示判定 b__35_0 → {__result}");
}

/// <summary>规约版本过滤 b__37_2(重载:STermsVersionsEntity)。</summary>
[HarmonyPatch]
internal static class Title_PredTerms2
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(StartupDiag.Inner(typeof(Project.Title.TopScene), "__c"), "_CheckTermsVersion_b__37_2");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result) =>
        StartupDiag.Log("PredTerms2", $"规约版本过滤 b__37_2 → {__result}");
}

/// <summary>规约版本过滤 b__37_3(TTermsVersionsEntity 重载一)。</summary>
[HarmonyPatch]
internal static class Title_PredTerms3
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(StartupDiag.Inner(typeof(Project.Title.TopScene), "__c"), "_CheckTermsVersion_b__37_3");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result) =>
        StartupDiag.Log("PredTerms3", $"规约版本过滤 b__37_3 → {__result}");
}

/// <summary>规约版本过滤 b__37_4(TTermsVersionsEntity 重载二)。</summary>
[HarmonyPatch]
internal static class Title_PredTerms4
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(StartupDiag.Inner(typeof(Project.Title.TopScene), "__c"), "_CheckTermsVersion_b__37_4");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result) =>
        StartupDiag.Log("PredTerms4", $"规约版本过滤 b__37_4 → {__result}");
}

/// <summary>日程过滤 b__42_0。</summary>
[HarmonyPatch]
internal static class Title_PredSchedule
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(StartupDiag.Inner(typeof(Project.Title.TopScene), "__c"), "_GetCurrentSchedule_b__42_0");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result) =>
        StartupDiag.Log("PredSchedule", $"日程过滤 b__42_0 → {__result}");
}

/// <summary>提示框弹窗(等用户点确定)。</summary>
[HarmonyPatch]
internal static class Title_OnShowHintBoxPopup
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopScene), "OnShowHintBoxPopupAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("OnShowHintBoxPopup", "进入 OnShowHintBoxPopupAsync(提示框弹窗)");
}

// ───────────────────────── 首盘批量下载弹窗(离线最可疑的等待点) ─────────────────────────

/// <summary>StartupBulkDownloadConfirmPopupController.OpenPopupAsync:启动时批量下载确认弹窗。</summary>
[HarmonyPatch]
internal static class StartupBulkDownload_OpenPopup
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Project.Download.BulkDownloadConfirmPopup.StartupBulkDownloadConfirmPopupController),
            "OpenPopupAsync");

    [HarmonyPrefix]
    private static void Prefix() =>
        StartupDiag.Log("StartupBulkDownloadOpen", "进入 StartupBulkDownloadConfirmPopup.OpenPopupAsync(首盘下载弹窗)");
}

/// <summary>StartupBulkDownloadConfirmPopupController.OnConfirm:用户/流程点了"确认下载"。</summary>
[HarmonyPatch]
internal static class StartupBulkDownload_OnConfirm
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Project.Download.BulkDownloadConfirmPopup.StartupBulkDownloadConfirmPopupController),
            "OnConfirm");

    [HarmonyPrefix]
    private static void Prefix() =>
        StartupDiag.Log("StartupBulkDownloadConfirm", "StartupBulkDownloadConfirmPopup.OnConfirm 被调用");
}

/// <summary>StartupBulkDownloadConfirmPopupController.OnCancel:弹窗被取消。</summary>
[HarmonyPatch]
internal static class StartupBulkDownload_OnCancel
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Project.Download.BulkDownloadConfirmPopup.StartupBulkDownloadConfirmPopupController),
            "OnCancel");

    [HarmonyPrefix]
    private static void Prefix() =>
        StartupDiag.Log("StartupBulkDownloadCancel", "StartupBulkDownloadConfirmPopup.OnCancel 被调用");
}

// ───────────────────────── 标题视图链(Project.Title.TopView) ─────────────────────────

/// <summary>TopView.InitializeAsync:标题 UI 初始化(userId 等参数)。</summary>
[HarmonyPatch]
internal static class TitleView_Initialize
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "InitializeAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewInitialize", "进入 TopView.InitializeAsync");
}

/// <summary>LoadBackgroundImageAsync:标题背景图加载(AssetBundle → 会走 TransformInternalId)。</summary>
[HarmonyPatch]
internal static class TitleView_LoadBackground
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "LoadBackgroundImageAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewLoadBackground", "进入 TopView.LoadBackgroundImageAsync");
}

/// <summary>LoadMovieAsync:标题开场视频加载。</summary>
[HarmonyPatch]
internal static class TitleView_LoadMovie
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "LoadMovieAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewLoadMovie", "进入 TopView.LoadMovieAsync");
}

/// <summary>ShowTitleAsync:展示标题(进入 Logo/标题 UI)。</summary>
[HarmonyPatch]
internal static class TitleView_ShowTitle
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "ShowTitleAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewShowTitle", "进入 TopView.ShowTitleAsync");
}

/// <summary>PlayInAsync:标题入场演出。</summary>
[HarmonyPatch]
internal static class TitleView_PlayIn
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "PlayInAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewPlayIn", "进入 TopView.PlayInAsync");
}

/// <summary>WaitUntilPopupClosedAsync:等待弹窗关闭(死等用户操作的嫌疑点)。</summary>
[HarmonyPatch]
internal static class TitleView_WaitUntilPopupClosed
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "WaitUntilPopupClosedAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewWaitPopupClosed", "进入 TopView.WaitUntilPopupClosedAsync");
}

/// <summary>WaitWithPopupCheckAsync:带弹窗检查的等待循环。</summary>
[HarmonyPatch]
internal static class TitleView_WaitWithPopupCheck
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "WaitWithPopupCheckAsync");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewWaitWithPopupCheck", "进入 TopView.WaitWithPopupCheckAsync");
}

/// <summary>PlayMovie:开始播片(同步入口)。</summary>
[HarmonyPatch]
internal static class TitleView_PlayMovie
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "PlayMovie");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewPlayMovie", "进入 TopView.PlayMovie");
}

/// <summary>MovieOnFinished:播片结束回调。</summary>
[HarmonyPatch]
internal static class TitleView_MovieOnFinished
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "MovieOnFinished");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewMovieOnFinished", "进入 TopView.MovieOnFinished");
}

/// <summary>CheckMovieLoop:播片循环检查(协程式循环,卡住时最后一条就是它)。</summary>
[HarmonyPatch]
internal static class TitleView_CheckMovieLoop
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "CheckMovieLoop");

    [HarmonyPrefix]
    private static void Prefix() => StartupDiag.Log("TopViewCheckMovieLoop", "进入 TopView.CheckMovieLoop");
}

/// <summary>播片循环判定 b__46_0:true = 继续等待播片结束。</summary>
[HarmonyPatch]
internal static class TitleView_PredCheckMovieLoop
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Title.TopView), "_CheckMovieLoop_b__46_0");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result) =>
        StartupDiag.Log("TopViewPredMovieLoop", $"播片循环判定 b__46_0 → {__result}");
}

/// <summary>播片加载判定 b__51_0:true = 需要等待(加载中)。</summary>
[HarmonyPatch]
internal static class TitleView_PredLoadMovie
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(StartupDiag.Inner(typeof(Project.Title.TopView), "__c"), "_LoadMovieAsync_b__51_0");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result) =>
        StartupDiag.Log("TopViewPredLoadMovie", $"播片加载判定 b__51_0 → {__result}");
}

// ───────────────────────── 主数据链(Project.Master.MasterDataStore / Absf 磁盘缓存) ─────────────────────────

/// <summary>MasterDataStore.DownloadFirstAsync:主数据首次下载(离线卡点的另一个嫌疑点)。</summary>
[HarmonyPatch]
internal static class Master_DataStoreDownloadFirst
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(Project.Master.MasterDataStore), "DownloadFirstAsync");

    [HarmonyPrefix]
    private static void Prefix() =>
        StartupDiag.Log("MasterDownloadFirst", "进入 MasterDataStore.DownloadFirstAsync");
}

/// <summary>MasterDataStore.TryPersistFirstDownloadDiskCacheAsync:把首下结果写入磁盘缓存。</summary>
[HarmonyPatch]
internal static class Master_DataStorePersistCache
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Project.Master.MasterDataStore), "TryPersistFirstDownloadDiskCacheAsync");

    [HarmonyPrefix]
    private static void Prefix() =>
        StartupDiag.Log("MasterPersistCache", "进入 MasterDataStore.TryPersistFirstDownloadDiskCacheAsync");
}

/// <summary>MasterFirstDownloadDiskCache.TryReadAsync:主数据磁盘缓存读取(命中就不需要下载)。</summary>
[HarmonyPatch]
internal static class Master_DiskCacheTryRead
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Absf.Master.Default.MasterFirstDownloadDiskCache), "TryReadAsync");

    [HarmonyPrefix]
    private static void Prefix() =>
        StartupDiag.Log("MasterDiskRead", "进入 MasterFirstDownloadDiskCache.TryReadAsync");
}

/// <summary>MasterFirstDownloadDiskCache.WriteAsync:主数据磁盘缓存写入。</summary>
[HarmonyPatch]
internal static class Master_DiskCacheWrite
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Absf.Master.Default.MasterFirstDownloadDiskCache), "WriteAsync");

    [HarmonyPrefix]
    private static void Prefix() =>
        StartupDiag.Log("MasterDiskWrite", "进入 MasterFirstDownloadDiskCache.WriteAsync");
}
