using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using Project;
using Project.Title;

namespace StoryViewer.Patches;

// 启动链异步追踪(2026-09-23,v0.6.7):
// 「[启动] 进入 Xxx」只能说明某方法被调用过,看不出它是"正在执行"还是"停在某个 await 上"。
// 这里对关键 async 状态机的 MoveNext 打点:
//   - Prefix 记「进入」时的 <>1__state:本次 MoveNext 是从第几个 await 恢复的(-1 = 首次执行);
//   - Postfix 记「暂停」时的 <>1__state:MoveNext 返回后停在哪个 await 上(值越大 = 越靠后的 await)。
// 于是"卡住"的那一步会表现为:最后一次「暂停 state=N」之后再没有「进入」。
//
// 只在 [Offline] DiagAssets=true 时安装(PatchManager 读取各类的 Enabled 属性)。
// 日志带 [追踪] 前缀,与 [启动] 打点互为补充。

/// <summary>异步状态机追踪的公共实现(读 <c>&lt;&gt;1__state</c> 并做去重/限流)。</summary>
internal static class AsyncTrace
{
    /// <summary>日志总条数上限(避免长时间运行时刷爆日志)。</summary>
    private const int MaxLines = 600;

    private static readonly Dictionary<string, int> Seen = new(StringComparer.Ordinal);
    private static readonly Dictionary<Type, PropertyInfo> StateProps = new();
    private static readonly object Sync = new();
    private static int _lines;

    /// <summary>记一次状态机迁移(同一 名称/阶段/state 组合只记一次)。</summary>
    internal static void Step(object instance, string name, string phase)
    {
        if (!Plugin.DiagAssets.Value)
            return;

        int state = ReadState(instance);
        lock (Sync)
        {
            if (_lines >= MaxLines)
                return;
            string key = $"{name}|{phase}|{state}";
            if (Seen.ContainsKey(key))
                return;
            Seen[key] = 1;
            _lines++;
        }
        Plugin.Logger?.LogInfo($"[追踪] {DateTime.Now:HH:mm:ss.fff} {name} {phase} state={state}");
    }

    /// <summary>
    /// 读取状态机的等待对象(<c>&lt;&gt;u__1</c> 等属性)并记录其类型与关键内部字段。
    /// <para>
    /// 用途:离线档停在某个 await 上时,状态机里会留下等待对象;
    /// 把它的类型/内部 source 打出来,就能知道"到底在等谁"。
    /// 只读、异常全吞,失败不影响游戏。
    /// </para>
    /// </summary>
    internal static void ProbeAwaiter(object instance, string name)
    {
        if (!Plugin.DiagAssets.Value)
            return;

        try
        {
            var type = instance.GetType();
            bool found = false;
            foreach (string propName in new[] { "__u__1", "__u__2", "__u__3", "__u__4", "__u__5" })
            {
                var prop = AccessTools.Property(type, propName);
                if (prop == null)
                    continue;
                found = true;
                string desc;
                try
                {
                    object v = prop.GetValue(instance);
                    desc = v == null ? "(null)" : Describe(v);
                }
                catch (Exception e)
                {
                    desc = $"<读取异常 {e.GetType().Name}>";
                }
                Plugin.Logger?.LogInfo($"[追踪] {name} 等待对象 {propName}: {desc}");
            }
            if (!found)
                Plugin.Logger?.LogInfo($"[追踪] {name} 没有 __u__N 等待对象属性");
        }
        catch (Exception e)
        {
            Plugin.Logger?.LogWarning($"[追踪] {name} 等待对象探测失败: {e.Message}");
        }
    }

    /// <summary>描述等待对象:类型 + ToString + 常见内部成员(source/task/status)。</summary>
    private static string Describe(object v)
    {
        try
        {
            var t = v.GetType();
            var sb = new System.Text.StringBuilder(t.FullName);
            try
            {
                sb.Append(" ToString=").Append(v);
            }
            catch
            {
                // ToString 不可用就跳过
            }
            foreach (string n in new[] { "source", "Source", "task", "Task", "IsCompleted", "Status" })
            {
                var prop = AccessTools.Property(t, n);
                if (prop != null)
                {
                    try
                    {
                        sb.Append(' ').Append(n).Append('=').Append(prop.GetValue(v));
                    }
                    catch
                    {
                        // 单个成员失败忽略
                    }
                    continue;
                }
                var field = AccessTools.Field(t, n);
                if (field != null)
                {
                    try
                    {
                        sb.Append(' ').Append(n).Append('=').Append(field.GetValue(v));
                    }
                    catch
                    {
                        // 单个成员失败忽略
                    }
                }
            }
            return sb.ToString();
        }
        catch (Exception e)
        {
            return $"<{e.GetType().Name}>";
        }
    }

    /// <summary>读取状态机的 <c>&lt;&gt;1__state</c>(interop 里暴露为属性,读不到返回 int.MinValue)。</summary>
    private static int ReadState(object instance)
    {
        try
        {
            var type = instance.GetType();
            PropertyInfo prop;
            lock (Sync)
            {
                if (!StateProps.TryGetValue(type, out prop))
                {
                    prop = AccessTools.Property(type, "__1__state");
                    StateProps[type] = prop;
                }
            }
            return prop?.GetValue(instance) is int s ? s : int.MinValue;
        }
        catch
        {
            return int.MinValue;
        }
    }
}

// ───────────────────────── 通用初始化链(Project.CommonInitializationService) ─────────────────────────

/// <summary>OnBootAsync 状态机追踪。</summary>
[HarmonyPatch(typeof(CommonInitializationService._OnBootAsync_d__6), "MoveNext")]
internal static class Trace_OnBoot
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(CommonInitializationService._OnBootAsync_d__6 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnBoot", "进入");

    [HarmonyPostfix]
    private static void After(CommonInitializationService._OnBootAsync_d__6 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnBoot", "暂停");
}

/// <summary>InitializeOrLoginDmmSdkAsync 状态机追踪(判断 SDK 登录是否真的完成)。</summary>
[HarmonyPatch(typeof(CommonInitializationService._InitializeOrLoginDmmSdkAsync_d__8), "MoveNext")]
internal static class Trace_InitOrLoginDmmSdk
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(CommonInitializationService._InitializeOrLoginDmmSdkAsync_d__8 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.InitOrLoginDmmSdk", "进入");

    [HarmonyPostfix]
    private static void After(CommonInitializationService._InitializeOrLoginDmmSdkAsync_d__8 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.InitOrLoginDmmSdk", "暂停");
}

/// <summary>OnNoticeFirstUpdateAsync 状态机追踪。</summary>
[HarmonyPatch(typeof(CommonInitializationService._OnNoticeFirstUpdateAsync_d__13), "MoveNext")]
internal static class Trace_OnNoticeFirstUpdate
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(CommonInitializationService._OnNoticeFirstUpdateAsync_d__13 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnNoticeFirstUpdate", "进入");

    [HarmonyPostfix]
    private static void After(CommonInitializationService._OnNoticeFirstUpdateAsync_d__13 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnNoticeFirstUpdate", "暂停");
}

/// <summary>OnTitleInitializeAsync 状态机追踪(当前卡点的起点)。</summary>
[HarmonyPatch(typeof(CommonInitializationService._OnTitleInitializeAsync_d__14), "MoveNext")]
internal static class Trace_OnTitleInitialize
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(CommonInitializationService._OnTitleInitializeAsync_d__14 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnTitleInitialize", "进入");

    [HarmonyPostfix]
    private static void After(CommonInitializationService._OnTitleInitializeAsync_d__14 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnTitleInitialize", "暂停");
}

/// <summary>OnLoginAsync 状态机追踪(离线运行时它是否被调用是关键信号)。</summary>
[HarmonyPatch(typeof(CommonInitializationService._OnLoginAsync_d__15), "MoveNext")]
internal static class Trace_OnLogin
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(CommonInitializationService._OnLoginAsync_d__15 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnLogin", "进入");

    [HarmonyPostfix]
    private static void After(CommonInitializationService._OnLoginAsync_d__15 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnLogin", "暂停");
}

/// <summary>InitializeAssetLoaderAsync 状态机追踪(catalog/资源加载器初始化)。</summary>
[HarmonyPatch(typeof(CommonInitializationService._InitializeAssetLoaderAsync_d__17), "MoveNext")]
internal static class Trace_InitAssetLoader
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(CommonInitializationService._InitializeAssetLoaderAsync_d__17 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.InitAssetLoader", "进入");

    [HarmonyPostfix]
    private static void After(CommonInitializationService._InitializeAssetLoaderAsync_d__17 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.InitAssetLoader", "暂停");
}

// ───────────────────────── 标题场景链(Project.Title.TopScene / TopView) ─────────────────────────

/// <summary>TopScene.OnInitializeImplAsync 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._OnInitializeImplAsync_d__19), "MoveNext")]
internal static class Trace_TopSceneInitializeImpl
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._OnInitializeImplAsync_d__19 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.OnInitializeImpl", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._OnInitializeImplAsync_d__19 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.OnInitializeImpl", "暂停");
}

/// <summary>TopScene.OnEnteredImplAsync 状态机追踪(离线卡点就在它之前)。</summary>
[HarmonyPatch(typeof(TopScene._OnEnteredImplAsync_d__21), "MoveNext")]
internal static class Trace_TopSceneEnteredImpl
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._OnEnteredImplAsync_d__21 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.OnEnteredImpl", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._OnEnteredImplAsync_d__21 __instance)
    {
        AsyncTrace.Step(__instance, "TopScene.OnEnteredImpl", "暂停");
        // 这里就是离线档的卡点:把等待对象打出来,确认它到底在等谁。
        AsyncTrace.ProbeAwaiter(__instance, "TopScene.OnEnteredImpl");
        // 卡在这里说明游戏自己不会去初始化资源系统了 —— 让插件补上,
        // 否则 F7 播放剧情会以「アセットの読み込みに失敗しました」告终。
        AssetBootstrap.Want("标题流程停在 OnEnteredImpl");
    }
}

/// <summary>TopScene.ChangeToHomeSceneAsync 状态机追踪(标题之后应当进入 Home)。</summary>
[HarmonyPatch(typeof(TopScene._ChangeToHomeSceneAsync_d__27), "MoveNext")]
internal static class Trace_ChangeToHome
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._ChangeToHomeSceneAsync_d__27 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ChangeToHome", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._ChangeToHomeSceneAsync_d__27 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ChangeToHome", "暂停");
}

/// <summary>TopView.InitializeAsync 状态机追踪(标题视图初始化,含背景/影片加载)。</summary>
[HarmonyPatch(typeof(TopView._InitializeAsync_d__44), "MoveNext")]
internal static class Trace_TopViewInitialize
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._InitializeAsync_d__44 __instance) =>
        AsyncTrace.Step(__instance, "TopView.Initialize", "进入");

    [HarmonyPostfix]
    private static void After(TopView._InitializeAsync_d__44 __instance) =>
        AsyncTrace.Step(__instance, "TopView.Initialize", "暂停");
}
