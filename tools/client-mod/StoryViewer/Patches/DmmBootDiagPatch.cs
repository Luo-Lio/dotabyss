using System;
using System.Reflection;
using HarmonyLib;

namespace StoryViewer.Patches;

/// <summary>
/// DMM 平台层启动诊断(2026-09-23)。
/// <para>
/// 背景:14:36 那轮游戏在 <c>NotifyDmmSdkBootFailureIfNeededAsync</c> 之后弹出
/// 「初期化に失敗しました。アプリケーションを再起動してください。」,整轮没有任何 API 请求。
/// 该分支对应"<c>HasDmmSdkBootFailure == true</c>",即 DMM SDK 初始化失败;
/// 而启动脚本注释写明:不带 DMM 启动参数直接运行 exe 时,就是先在
/// <c>DmmGamesSdk.PlayerInitialize</c> 处初始化失败。
/// </para>
/// <para>
/// 这里对 SDK 初始化链做打点,确认失败发生在哪一步、以及当时的命令行参数个数
/// (只记个数,不记内容 —— 启动参数含登录凭证)。
/// </para>
/// 只在 <see cref="Plugin.OfflineApi"/> + <see cref="Plugin.DiagAssets"/> 同时打开时输出。
/// </summary>
[HarmonyPatch]
internal static class Dmm_Initialize
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;
    /// <summary>DmmGamesSdk.Initialize(settings, callback):SDK 总初始化入口。</summary>
    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Dmm.Games.Sdk.DmmGamesSdk), "Initialize");

    [HarmonyPrefix]
    private static void Prefix()
    {
        int argc = Environment.GetCommandLineArgs().Length;
        StartupDiag.Log("DmmSdkInitialize",
            $"进入 DmmGamesSdk.Initialize(命令行参数个数={argc},本机 SDK 初始化入口)");
    }
}

/// <summary>
/// DMM SDK 登录态探针(2026-09-23)。
/// <para>
/// 21:55 / 22:04 两轮"真实凭证 + VPN"仍在 SDK 这步失败。SDK 自己把结果放在
/// <c>Dmm.Games.Sdk.DmmGamesSdk.IsInitialized</c> / <c>OpenId</c> / <c>AccessToken</c>
/// 三个静态属性里,这里在关键节点读取状态(只记长度,不记内容),
/// 用来判断"原生 SDK 到底有没有登录成功",还是"成功了但游戏没用上"。
/// </para>
/// </summary>
internal static class DmmSdkState
{
    /// <summary>记录一次 SDK 登录态快照(读取失败不影响流程)。</summary>
    internal static void Log(string tag)
    {
        try
        {
            var t = typeof(Dmm.Games.Sdk.DmmGamesSdk);
            bool initialized = false;
            var p = AccessTools.Property(t, "IsInitialized");
            if (p?.GetValue(null) is bool b)
                initialized = b;
            StartupDiag.Log("DmmSdkState",
                $"{tag}: IsInitialized={initialized} OpenId长度={StrLen(t, "OpenId")} AccessToken长度={StrLen(t, "AccessToken")}");
        }
        catch (Exception e)
        {
            StartupDiag.Log("DmmSdkStateEx", $"{tag}: 读取失败 {e.GetType().Name}: {e.Message}");
        }
    }

    /// <summary>读字符串属性长度(空/取不到记 -1;不记内容,凭证不外泄)。</summary>
    private static int StrLen(Type t, string prop)
    {
        var p = AccessTools.Property(t, prop);
        return p?.GetValue(null) is string s ? s.Length : -1;
    }
}

/// <summary>DmmGamesSdk.PlayerInitialize(settings, callback):玩家初始化(缺启动参数时在这里失败)。</summary>
[HarmonyPatch]
internal static class Dmm_PlayerInitialize
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Dmm.Games.Sdk.DmmGamesSdk), "PlayerInitialize");

    [HarmonyPrefix]
    private static void Prefix()
    {
        int argc = Environment.GetCommandLineArgs().Length;
        StartupDiag.Log("DmmSdkPlayerInitialize", $"进入 DmmGamesSdk.PlayerInitialize(命令行参数个数={argc})");
    }

    /// <summary>返回后再读一次登录态:此时原生层刚处理完凭证。</summary>
    [HarmonyPostfix]
    private static void Postfix() => DmmSdkState.Log("PlayerInitialize 返回后");
}

/// <summary>DmmGamesSdk.IsInitialized:SDK 最终是否初始化成功。</summary>
[HarmonyPatch]
internal static class Dmm_IsInitialized
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Dmm.Games.Sdk.DmmGamesSdk), "get_IsInitialized");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result) =>
        StartupDiag.Log("DmmSdkIsInitialized", $"DmmGamesSdk.IsInitialized = {__result}");
}

/// <summary>Absf.DmmPlatforms.DmmSdk.Initialize:游戏自己的 SDK 包装层(成功/失败回调在这里分流)。</summary>
[HarmonyPatch]
internal static class DmmPlatform_Initialize
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Absf.DmmPlatforms.DmmSdk), "Initialize");

    [HarmonyPrefix]
    private static void Prefix() =>
        StartupDiag.Log("DmmPlatformInitialize", "进入 Absf.DmmPlatforms.DmmSdk.Initialize(游戏 SDK 包装层)");
}

/// <summary>
/// CommonInitializationService.HasDmmSdkBootFailure:启动失败标记是否被置位。
/// <para>
/// 注意:此前版本对 <c>Absf.DmmPlatforms.DmmSdk.Log(string)</c> 打过点,原生调用时收到非法字符串指针,
/// 触发过 CLR fatal error 白屏闪退(0x80131506),已删除该类补丁 —— SDK 层不要再声明 string 参数。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class Boot_HasDmmSdkBootFailure
{
    /// <summary>只在「强制忽略 DMM SDK 失败」时安装。</summary>
    public static bool Enabled => Plugin.ForceDmmSdkSuccess.Value;

    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Project.CommonInitializationService), "get_HasDmmSdkBootFailure");

    [HarmonyPostfix]
    private static void Postfix(ref bool __result)
    {
        bool original = __result;
        DmmSdkState.Log("读 HasDmmSdkBootFailure 时");
        if (Plugin.ForceDmmSdkSuccess.Value && __result)
        {
            __result = false;
            StartupDiag.Log("HasDmmSdkBootFailureForced",
                "HasDmmSdkBootFailure 原为 true,按配置强制改为 false(跳过 SDK 启动失败弹窗)");
        }
        else
        {
            StartupDiag.Log("HasDmmSdkBootFailure", $"HasDmmSdkBootFailure = {original}");
        }
    }
}
