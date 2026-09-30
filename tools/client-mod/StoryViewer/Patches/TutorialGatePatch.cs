using System.Reflection;
using HarmonyLib;
using Project.Tutorial;

namespace StoryViewer.Patches;

// 教学模式门禁旁路(2026-09-23,v0.7.1)。
//
// 实机证据(22:20/22:21 两轮):剧情资源 bundle 已经能从本地缓存正常加载(命中 2 / 缺失 0),
// 但 NovelSceneTransitionUtility.ChangeSceneAsync 内部要查"序章教学是否完成":
//     TutorialManager.get_IsPrologueTutorialCompleted() → GetPrologueState() → NullReferenceException
// 离线档教学状态来自服务器、从未到达,`_prologueState` 为空,于是每次播放都在这里中止。
//
// 这里把"教学是否完成/是否在教学中/是否有教学在跑"这类门禁统一改成
// 「教学已完成、不在教学中」——对"离线剧情播放器"来说本来就是期望行为
// (否则游戏会先给你放序章教学流程)。
//
// 只在 [Offline] SkipTutorial=true(默认)时安装:PatchManager 读取各类的 Enabled 属性。

/// <summary>序章教学是否完成 → 强制 true(跳过 GetPrologueState,避免空引用)。</summary>
[HarmonyPatch]
internal static class TutorialGate_PrologueCompleted
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.SkipTutorial.Value;

    /// <summary>定位 TutorialManager.IsPrologueTutorialCompleted 的 getter。</summary>
    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(TutorialManager), "get_IsPrologueTutorialCompleted");

    /// <summary>直接给出 true,不调用原方法(原方法会取空的 _prologueState)。</summary>
    [HarmonyPrefix]
    private static bool Prefix(ref bool __result)
    {
        __result = true;
        PatchLog.Once("教学门禁: IsPrologueTutorialCompleted → true");
        return false;
    }
}

/// <summary>是否处于序章教学中 → 强制 false。</summary>
[HarmonyPatch]
internal static class TutorialGate_InPrologue
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.SkipTutorial.Value;

    /// <summary>定位 TutorialManager.IsInPrologue 的 getter。</summary>
    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(TutorialManager), "get_IsInPrologue");

    /// <summary>直接给出 false。</summary>
    [HarmonyPrefix]
    private static bool Prefix(ref bool __result)
    {
        __result = false;
        PatchLog.Once("教学门禁: IsInPrologue → false");
        return false;
    }
}

/// <summary>序章教学是否已结束 → 强制 true。</summary>
[HarmonyPatch]
internal static class TutorialGate_IsPrologueCompleted
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.SkipTutorial.Value;

    /// <summary>定位 TutorialManager.IsPrologueCompleted()。</summary>
    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(TutorialManager), "IsPrologueCompleted");

    /// <summary>直接给出 true。</summary>
    [HarmonyPrefix]
    private static bool Prefix(ref bool __result)
    {
        __result = true;
        PatchLog.Once("教学门禁: IsPrologueCompleted → true");
        return false;
    }
}

/// <summary>是否有教学正在运行 → 强制 false(避免剧情被教学流程拦截)。</summary>
[HarmonyPatch]
internal static class TutorialGate_IsRunTutorial
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.SkipTutorial.Value;

    /// <summary>定位 TutorialManager.IsRunTutorial 的 getter。</summary>
    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(TutorialManager), "get_IsRunTutorial");

    /// <summary>直接给出 false。</summary>
    [HarmonyPrefix]
    private static bool Prefix(ref bool __result)
    {
        __result = false;
        PatchLog.Once("教学门禁: IsRunTutorial → false");
        return false;
    }
}

/// <summary>指定功能教学是否结束 → 强制 true。</summary>
[HarmonyPatch]
internal static class TutorialGate_IsEndFeatureTutorial
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.SkipTutorial.Value;

    /// <summary>定位 TutorialManager.IsEndFeatureTutorial(FeatureTutorialType)。</summary>
    [HarmonyTargetMethod]
    private static MethodBase Target() => StartupDiag.Of(typeof(TutorialManager), "IsEndFeatureTutorial");

    /// <summary>不声明参数、只改返回值:所有功能教学都视为已完成。</summary>
    [HarmonyPrefix]
    private static bool Prefix(ref bool __result)
    {
        __result = true;
        PatchLog.Once("教学门禁: IsEndFeatureTutorial → true");
        return false;
    }
}
