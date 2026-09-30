using System;
using System.Collections.Generic;
using System.Reflection;
using Absf.Novel;
using HarmonyLib;
using Project.Novel;

// ---------------------------------------------------------------------------
// 0.7.14 移除四个诊断补丁(曾造成致命崩溃):NovelSkipDiagCleanSkipPatch /
// NovelSkipDiagLabelJumpPatch / NovelSkipDiagFastPlayStartPatch /
// NovelSkipDiagFastPlayCheckPatch —— 它们 detour 了 NovelCmd*.OnCommandStartASync。
// 崩溃证据(2026-09-24 02:37,用户实机,0.7.13):BepInEx\ErrorLog.log 记录
//   "Fatal error. System.AccessViolationException" 于
//   Il2CppInterop.Runtime.IL2CPP.il2cpp_object_get_class(IntPtr) ←
//   Il2CppObjectPool.Get<T>(IntPtr) ← DynamicClass.(il2cpp -> managed) OnCommandStartASync
// 同一会话 LogOutput.log 另有该方法的 NullReferenceException(参数 args 为 null 时
// 也会进入被替换的方法体)。这类命令由引擎在快速播放中逐条调用
// (fastplaycheck 单次会话被调用 1341 次),参数为空/失效时封送层即崩,
// 属「高频 + IL2CPP 对象参数」的高危 detour,结论取得后不再保留。
// 保留的诊断只涉及低频或纯值类型入口(字符串/bool/无参),见下方各类。
// ---------------------------------------------------------------------------

namespace StoryViewer.Patches;

/// <summary>
/// R18 分段后篇的「跳过」修复:剧本 csv 进入引擎命令表(InitCsv)时补上跳过落点,
/// 使第 2 段(R18 场景)、第 3 段(尾声)也能用「跳过」(游戏只给第 1 段写了落点)。
/// 变换逻辑见 <see cref="SkipPointInjector"/>;开关:General/FixR18Skip。
/// </summary>
[HarmonyPatch]
internal static class NovelSkipPointPatch
{
    /// <summary>关闭该配置时整个补丁不安装(纯文本处理,无风险,默认开启)。</summary>
    public static bool Enabled => Plugin.FixR18Skip.Value;

    /// <summary>定位 Absf.Novel.NovelScriptCommands.InitCsv(string csv)。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(NovelScriptCommands), "InitCsv");

    /// <summary>
    /// 改写入参 csv 后交回原方法解析。
    /// 自身出错时按原样放行——跳过修复绝不能破坏剧本加载。
    /// </summary>
    [HarmonyPrefix]
    private static void Prefix(ref string csv)
    {
        try
        {
            string patched = SkipPointInjector.Inject(csv, out string report);
            if (ReferenceEquals(patched, csv))
            {
                if (Plugin.SkipDebug.Value)
                    Plugin.Logger.LogInfo($"[跳过修复] 未改动({report}): {Preview(csv)}");
                return;
            }
            Plugin.Logger.LogInfo(
                $"[跳过修复] 已注入跳过落点(长度 {csv?.Length}→{patched.Length};{report}): {Preview(csv)}");
            csv = patched;
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"[跳过修复] 注入失败,按原样播放: {e.Message}");
        }
    }

    /// <summary>日志预览:开头片段 + 总行数,足以区分「整体一条 csv」与「逐段传入」两种情况。</summary>
    private static string Preview(string csv)
    {
        if (string.IsNullOrEmpty(csv))
            return "<空>";
        string head = csv.Length > 160 ? csv.Substring(0, 160) : csv;
        head = head.Replace("\r\n", "\\n").Replace("\n", "\\n").Replace("\r", "\\n");
        int lines = 1;
        foreach (char c in csv)
        {
            if (c == '\n')
                lines++;
        }
        return $"头部=\"{(head.Length > 0 && head[0] == '\uFEFF' ? head.Substring(1) : head)}\" 共{lines}行";
    }
}

/// <summary>
/// 跳过流程诊断(默认开启,排查完可在配置里关闭):
/// 记录剧本命令表上的 Jump / LabelExists 走向,用于确认「跳过」到底按哪个标签、往哪个方向跳。
/// </summary>
[HarmonyPatch]
internal static class NovelSkipDiagJumpPatch
{
    /// <summary>开关:Debug/SkipDebug。</summary>
    public static bool Enabled => Plugin.SkipDebug.Value;

    /// <summary>定位 NovelScriptCommands.Jump(string name, bool after)。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(NovelScriptCommands), "Jump");

    /// <summary>记录跳转目标、方向与跳转前所在行。</summary>
    [HarmonyPrefix]
    private static void Prefix(NovelScriptCommands __instance, string name, bool after)
    {
        Plugin.Logger.LogInfo($"[跳过诊断] Jump(\"{name}\", after={after}) 跳转前行={PlayLine(__instance)}");
    }

    /// <summary>记录跳转结果与跳转后所在行(判断是否真的跳了、跳向何处)。</summary>
    [HarmonyPostfix]
    private static void Postfix(NovelScriptCommands __instance, string name, bool __result)
    {
        Plugin.Logger.LogInfo($"[跳过诊断] Jump(\"{name}\") 返回={__result} 跳转后行={PlayLine(__instance)}");
    }

    /// <summary>读取当前播放行;il2cpp 调用失败时返回 -1,绝不让诊断抛异常。</summary>
    internal static int PlayLine(NovelScriptCommands commands)
    {
        try
        {
            return commands?.GetPlayLine() ?? -1;
        }
        catch
        {
            return -1;
        }
    }
}

/// <summary>
/// 跳过流程诊断:LabelExists 查询结果。引擎若用 LabelExists("SkipPoint") 判断「能否跳过」,
/// 这里能看到判定变化(只在结果变化时记录,避免每帧轮询刷屏)。
/// </summary>
[HarmonyPatch]
internal static class NovelSkipDiagLabelPatch
{
    /// <summary>开关:Debug/SkipDebug。</summary>
    public static bool Enabled => Plugin.SkipDebug.Value;

    private static readonly Dictionary<string, bool> LastResults = new Dictionary<string, bool>();

    /// <summary>定位 NovelScriptCommands.LabelExists(string label)。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(NovelScriptCommands), "LabelExists");

    /// <summary>记录标签查询结果的变化。</summary>
    [HarmonyPostfix]
    private static void Postfix(string label, bool __result)
    {
        lock (LastResults)
        {
            if (LastResults.TryGetValue(label, out bool last) && last == __result)
                return;
            LastResults[label] = __result;
        }
        Plugin.Logger.LogInfo($"[跳过诊断] LabelExists(\"{label}\") = {__result}");
    }
}

/// <summary>跳过流程诊断:TopScene 的跳过执行入口。</summary>
[HarmonyPatch]
internal static class NovelSkipDiagSkipExecPatch
{
    /// <summary>开关:Debug/SkipDebug。</summary>
    public static bool Enabled => Plugin.SkipDebug.Value;

    /// <summary>定位 TopScene.OnSkipExec(实际执行跳过的私有方法)。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(TopScene), "OnSkipExec");

    /// <summary>记录跳过执行时机。</summary>
    [HarmonyPrefix]
    private static void Prefix() => Plugin.Logger.LogInfo("[跳过诊断] TopScene.OnSkipExec 被调用(执行跳过)");
}

/// <summary>跳过流程诊断:TopScene 的跳过请求入口(按钮/弹窗回调)。</summary>
[HarmonyPatch]
internal static class NovelSkipDiagRequestPatch
{
    /// <summary>开关:Debug/SkipDebug。</summary>
    public static bool Enabled => Plugin.SkipDebug.Value;

    /// <summary>定位 TopScene.OnSkip(Action onClosed)。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(TopScene), "OnSkip");

    /// <summary>记录跳过请求(与 OnSkipExec 对照,可判断是否有中间弹窗)。</summary>
    [HarmonyPrefix]
    private static void Prefix() => Plugin.Logger.LogInfo("[跳过诊断] TopScene.OnSkip 被调用(收到跳过请求)");
}

/// <summary>
/// 跳过流程诊断:TopScene.TopParam.IsSkip 状态变化。
/// 该布尔是「跳过进行中」的运行时状态,开/关的时机能完整还原跳过流程。
/// </summary>
[HarmonyPatch]
internal static class NovelSkipDiagIsSkipPatch
{
    /// <summary>开关:Debug/SkipDebug。</summary>
    public static bool Enabled => Plugin.SkipDebug.Value;

    /// <summary>定位嵌套类型 TopScene.TopParam 的 IsSkip setter。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod()
    {
        Type nested = AccessTools.Inner(typeof(TopScene), "TopParam")
            ?? typeof(TopScene).GetNestedType("TopParam", BindingFlags.Public | BindingFlags.NonPublic);
        PropertyInfo prop = nested?.GetProperty("IsSkip",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
        return prop?.GetSetMethod(nonPublic: true);
    }

    /// <summary>记录 IsSkip 状态切换。</summary>
    [HarmonyPrefix]
    private static void Prefix(bool value) => Plugin.Logger.LogInfo($"[跳过诊断] TopParam.IsSkip ← {value}");
}
