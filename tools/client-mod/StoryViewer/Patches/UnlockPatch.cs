using HarmonyLib;
using Project.Interaction.AdventurerDetail;
using Project.Library.EventStory;
using Project.Library.MainStory;

namespace StoryViewer.Patches;

// 重要实现约定(勿简化):
// 原版界面「全解锁」的目标都是「读一个 bool、再决定是否显示/可点」的判定方法。
// 本文件统一用 Prefix + return false 直接给出 __result = true,**绝不调用被补丁方法自身**。
//
// 为什么必须跳过原方法:v0.6.5 实机中,LibraryMainStoryModel.get_IsOpen 的 Postfix 版补丁
// 一被调用就发生无限递归(栈溢出 → 进程崩溃),崩溃栈为
//   il2cpp_runtime_invoke → 补丁 thunk → DynamicClass.DMD<get_IsOpen> → il2cpp_runtime_invoke → …
// 即 HarmonyX 为该方法生成的「调用原方法」通道会重新打回补丁入口。跳过原方法后该通道不会被走到,
// 从结构上消除递归;而这些判定方法原本的取值逻辑也不是我们需要的(一律放开)。
//
// 安装开关:每个补丁类声明 public static bool Enabled(由 PatchManager 读取),
// 为 false 时整个补丁类不安装。配置在启动时生效(不热重载)。

/// <summary>资料室·主线回想:章节分组与条目的 IsOpen 一律放开。</summary>
[HarmonyPatch]
internal static class UnlockMainStoryPatch
{
    /// <summary>是否安装本补丁类(读配置,启动时判定)。</summary>
    public static bool Enabled => Plugin.UnlockMainStory.Value;

    /// <summary>主线回想条目 get_IsOpen → 恒为 true。</summary>
    [HarmonyPatch(typeof(LibraryMainStoryNovelModel), "get_IsOpen")]
    [HarmonyPrefix]
    private static bool NovelOpen(ref bool __result)
    {
        __result = true;
        PatchLog.Once("资料室主线条目 IsOpen → true");
        return false;
    }

    /// <summary>主线章节分组 get_IsOpen → 恒为 true。</summary>
    [HarmonyPatch(typeof(LibraryMainStoryModel), "get_IsOpen")]
    [HarmonyPrefix]
    private static bool ChapterOpen(ref bool __result)
    {
        __result = true;
        PatchLog.Once("资料室主线章节 IsOpen → true");
        return false;
    }
}

/// <summary>资料室·活动回想:活动期限不再拦截显示。</summary>
[HarmonyPatch]
internal static class UnlockEventStoryPatch
{
    /// <summary>是否安装本补丁类(读配置,启动时判定)。</summary>
    public static bool Enabled => Plugin.UnlockEventStory.Value;

    /// <summary>活动回想条目 get_IsOpen → 恒为 true。</summary>
    [HarmonyPatch(typeof(LibraryEventNovelModel), "get_IsOpen")]
    [HarmonyPrefix]
    private static bool NovelOpen(ref bool __result)
    {
        __result = true;
        PatchLog.Once("资料室活动条目 IsOpen → true");
        return false;
    }
}

/// <summary>
/// 角色详情(交流)的剧情列表:SubService 编译器生成类里的 bool 谓词
/// (列表过滤器)统一恒为 true(含衣装/R18),即全部显示。
/// </summary>
[HarmonyPatch]
internal static class UnlockCharacterStoryPatch
{
    /// <summary>是否安装本补丁类(读配置,启动时判定)。</summary>
    public static bool Enabled => Plugin.UnlockCharacterStory.Value;

    /// <summary>统一的「恒为 true」前缀实现:设置结果并跳过原方法。</summary>
    private static bool ForceTrue(ref bool __result, string tag)
    {
        __result = true;
        PatchLog.Once(tag);
        return false;
    }

    [HarmonyPatch(typeof(SubService.__c), "_UpdateView_b__101_5")]
    [HarmonyPrefix]
    private static bool CharFilter101_5(ref bool __result) =>
        ForceTrue(ref __result, "角色剧情过滤 b__101_5");

    [HarmonyPatch(typeof(SubService.__c), "_UpdateR18StoryLists_b__103_1")]
    [HarmonyPrefix]
    private static bool R18Filter103_1(ref bool __result) =>
        ForceTrue(ref __result, "R18列表过滤 b__103_1");

    [HarmonyPatch(typeof(SubService.__c), "_UpdateR18StoryLists_b__103_2")]
    [HarmonyPrefix]
    private static bool R18Filter103_2(ref bool __result) =>
        ForceTrue(ref __result, "R18列表过滤 b__103_2");

    [HarmonyPatch(typeof(SubService.__c), "_UpdateR18StoryLists_b__103_3")]
    [HarmonyPrefix]
    private static bool R18Filter103_3(ref bool __result) =>
        ForceTrue(ref __result, "R18列表过滤 b__103_3");

    [HarmonyPatch(typeof(SubService.__c), "_UpdateR18StoryLists_b__103_4")]
    [HarmonyPrefix]
    private static bool R18Filter103_4(ref bool __result) =>
        ForceTrue(ref __result, "R18列表过滤 b__103_4");

    [HarmonyPatch(typeof(SubService.__c), "_UpdateR18StoryLists_b__103_5")]
    [HarmonyPrefix]
    private static bool R18Filter103_5(ref bool __result) =>
        ForceTrue(ref __result, "R18列表过滤 b__103_5");

    [HarmonyPatch(typeof(SubService.__c), "_UpdateR18StoryLists_b__103_6")]
    [HarmonyPrefix]
    private static bool R18Filter103_6(ref bool __result) =>
        ForceTrue(ref __result, "R18列表过滤 b__103_6");

    [HarmonyPatch(typeof(SubService.__c__DisplayClass101_0), "_UpdateView_b__1")]
    [HarmonyPrefix]
    private static bool CharFilter1(ref bool __result) =>
        ForceTrue(ref __result, "角色剧情过滤 b__1");

    [HarmonyPatch(typeof(SubService.__c__DisplayClass101_0), "_UpdateView_b__2")]
    [HarmonyPrefix]
    private static bool CharFilter2(ref bool __result) =>
        ForceTrue(ref __result, "角色剧情过滤 b__2");

    [HarmonyPatch(typeof(SubService.__c__DisplayClass101_0), "_UpdateView_b__4")]
    [HarmonyPrefix]
    private static bool CharFilter4(ref bool __result) =>
        ForceTrue(ref __result, "角色剧情过滤 b__4");
}

// 注:原「点击路径诊断」(SubService.__c__DisplayClass95_0 的 b__0/2/4/6 Postfix)已移除:
// 它需要读取原方法的返回值,必然触发「调用原方法」通道,与本次栈溢出同源,待解锁链路稳定后再按需恢复。

/// <summary>补丁命中日志:同一标记只记录一次,避免列表刷新时刷屏。</summary>
internal static class PatchLog
{
    /// <summary>已记录过的标记集合。</summary>
    private static readonly System.Collections.Generic.HashSet<string> Seen = new();

    /// <summary>记录一次「解锁已生效」日志(受 Debug.LogPatches 控制)。</summary>
    internal static void Once(string tag)
    {
        if (Plugin.DebugLog?.Value != true || !Seen.Add(tag))
            return;
        Plugin.Logger?.LogInfo($"[解锁] {tag}(同类命中不再重复记录)");
    }
}
