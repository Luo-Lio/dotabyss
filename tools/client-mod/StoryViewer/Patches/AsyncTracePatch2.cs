using HarmonyLib;
using Project;
using Project.Title;

namespace StoryViewer.Patches;

// 启动链异步追踪(第二批,2026-09-23 v0.6.9):
// 离线档在 TopScene.OnEnteredImplAsync 的某个 await 停住(见 [追踪] 最后一条「暂停 state=-2」)。
// 这里把该状态机之后所有可能被 await 的子流程全部打点:哪个方法开始执行、停在哪个 await,
// 用排除法把"卡住的那一步"缩到单个方法。
// 只在 [Offline] DiagAssets=true 时安装(PatchManager 读取各类的 Enabled 属性)。

/// <summary>CommonInit.LoginDmmSdk 状态机追踪。</summary>
[HarmonyPatch(typeof(CommonInitializationService._LoginDmmSdkAsync_d__7), "MoveNext")]
internal static class Trace2_CommonInit_LoginDmmSdk
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(CommonInitializationService._LoginDmmSdkAsync_d__7 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.LoginDmmSdk", "进入");

    [HarmonyPostfix]
    private static void After(CommonInitializationService._LoginDmmSdkAsync_d__7 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.LoginDmmSdk", "暂停");
}

/// <summary>CommonInit.CheckPermission 状态机追踪。</summary>
[HarmonyPatch(typeof(CommonInitializationService._CheckPermissionAsync_d__12), "MoveNext")]
internal static class Trace2_CommonInit_CheckPermission
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(CommonInitializationService._CheckPermissionAsync_d__12 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.CheckPermission", "进入");

    [HarmonyPostfix]
    private static void After(CommonInitializationService._CheckPermissionAsync_d__12 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.CheckPermission", "暂停");
}

/// <summary>CommonInit.OnDataInitialize 状态机追踪。</summary>
[HarmonyPatch(typeof(CommonInitializationService._OnDataInitializeAsync_d__16), "MoveNext")]
internal static class Trace2_CommonInit_OnDataInitialize
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(CommonInitializationService._OnDataInitializeAsync_d__16 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnDataInitialize", "进入");

    [HarmonyPostfix]
    private static void After(CommonInitializationService._OnDataInitializeAsync_d__16 __instance) =>
        AsyncTrace.Step(__instance, "CommonInit.OnDataInitialize", "暂停");
}

/// <summary>TopScene.LoadVoice 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._LoadVoiceAsync_d__23), "MoveNext")]
internal static class Trace2_TopScene_LoadVoice
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._LoadVoiceAsync_d__23 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.LoadVoice", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._LoadVoiceAsync_d__23 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.LoadVoice", "暂停");
}

/// <summary>TopScene.PlayBgm 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._PlayBgmAsync_d__25), "MoveNext")]
internal static class Trace2_TopScene_PlayBgm
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._PlayBgmAsync_d__25 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.PlayBgm", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._PlayBgmAsync_d__25 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.PlayBgm", "暂停");
}

/// <summary>TopScene.ToTitleLoading 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._TryChangeToTitleLoadingSceneAsync_d__28), "MoveNext")]
internal static class Trace2_TopScene_ToTitleLoading
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._TryChangeToTitleLoadingSceneAsync_d__28 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ToTitleLoading", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._TryChangeToTitleLoadingSceneAsync_d__28 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ToTitleLoading", "暂停");
}

/// <summary>TopScene.ConfirmTerms 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._ConfirmTermsAgreementsPopups_d__30), "MoveNext")]
internal static class Trace2_TopScene_ConfirmTerms
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._ConfirmTermsAgreementsPopups_d__30 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ConfirmTerms", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._ConfirmTermsAgreementsPopups_d__30 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ConfirmTerms", "暂停");
}

/// <summary>TopScene.ShowTermsPopup 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._ShowTermsAgreePopup_d__32), "MoveNext")]
internal static class Trace2_TopScene_ShowTermsPopup
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._ShowTermsAgreePopup_d__32 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ShowTermsPopup", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._ShowTermsAgreePopup_d__32 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ShowTermsPopup", "暂停");
}

/// <summary>TopScene.ATTCheck 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._ATTPermissionCheck_d__33), "MoveNext")]
internal static class Trace2_TopScene_ATTCheck
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._ATTPermissionCheck_d__33 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ATTCheck", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._ATTPermissionCheck_d__33 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ATTCheck", "暂停");
}

/// <summary>TopScene.TryShowTerms 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._TryShowTermsAgreementPopupAsync_d__35), "MoveNext")]
internal static class Trace2_TopScene_TryShowTerms
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._TryShowTermsAgreementPopupAsync_d__35 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.TryShowTerms", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._TryShowTermsAgreementPopupAsync_d__35 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.TryShowTerms", "暂停");
}

/// <summary>TopScene.ShowTermsExisting 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._ShowTermsAgreePopupForExistingUser_d__36), "MoveNext")]
internal static class Trace2_TopScene_ShowTermsExisting
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._ShowTermsAgreePopupForExistingUser_d__36 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ShowTermsExisting", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._ShowTermsAgreePopupForExistingUser_d__36 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.ShowTermsExisting", "暂停");
}

/// <summary>TopScene.OpenUpdateName 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._OpenUpdateNamePopupAsync_d__38), "MoveNext")]
internal static class Trace2_TopScene_OpenUpdateName
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._OpenUpdateNamePopupAsync_d__38 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.OpenUpdateName", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._OpenUpdateNamePopupAsync_d__38 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.OpenUpdateName", "暂停");
}

/// <summary>TopScene.UpdateName 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._UpdateNameAsync_d__39), "MoveNext")]
internal static class Trace2_TopScene_UpdateName
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._UpdateNameAsync_d__39 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.UpdateName", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._UpdateNameAsync_d__39 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.UpdateName", "暂停");
}

/// <summary>TopScene.HintBox 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._OnShowHintBoxPopupAsync_d__40), "MoveNext")]
internal static class Trace2_TopScene_HintBox
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._OnShowHintBoxPopupAsync_d__40 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.HintBox", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._OnShowHintBoxPopupAsync_d__40 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.HintBox", "暂停");
}

/// <summary>TopScene.LoadTitleBG 状态机追踪。</summary>
[HarmonyPatch(typeof(TopScene._LoadTitleBGScheduleAsync_d__41), "MoveNext")]
internal static class Trace2_TopScene_LoadTitleBG
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopScene._LoadTitleBGScheduleAsync_d__41 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.LoadTitleBG", "进入");

    [HarmonyPostfix]
    private static void After(TopScene._LoadTitleBGScheduleAsync_d__41 __instance) =>
        AsyncTrace.Step(__instance, "TopScene.LoadTitleBG", "暂停");
}

/// <summary>TopView.LoadBG 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._LoadBackgroundImageAsync_d__45), "MoveNext")]
internal static class Trace2_TopView_LoadBG
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._LoadBackgroundImageAsync_d__45 __instance) =>
        AsyncTrace.Step(__instance, "TopView.LoadBG", "进入");

    [HarmonyPostfix]
    private static void After(TopView._LoadBackgroundImageAsync_d__45 __instance) =>
        AsyncTrace.Step(__instance, "TopView.LoadBG", "暂停");
}

/// <summary>TopView.MovieLoop 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._CheckMovieLoop_d__46), "MoveNext")]
internal static class Trace2_TopView_MovieLoop
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._CheckMovieLoop_d__46 __instance) =>
        AsyncTrace.Step(__instance, "TopView.MovieLoop", "进入");

    [HarmonyPostfix]
    private static void After(TopView._CheckMovieLoop_d__46 __instance) =>
        AsyncTrace.Step(__instance, "TopView.MovieLoop", "暂停");
}

/// <summary>TopView.WaitPopupClosed 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._WaitUntilPopupClosedAsync_d__47), "MoveNext")]
internal static class Trace2_TopView_WaitPopupClosed
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._WaitUntilPopupClosedAsync_d__47 __instance) =>
        AsyncTrace.Step(__instance, "TopView.WaitPopupClosed", "进入");

    [HarmonyPostfix]
    private static void After(TopView._WaitUntilPopupClosedAsync_d__47 __instance) =>
        AsyncTrace.Step(__instance, "TopView.WaitPopupClosed", "暂停");
}

/// <summary>TopView.WaitWithPopup 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._WaitWithPopupCheckAsync_d__48), "MoveNext")]
internal static class Trace2_TopView_WaitWithPopup
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._WaitWithPopupCheckAsync_d__48 __instance) =>
        AsyncTrace.Step(__instance, "TopView.WaitWithPopup", "进入");

    [HarmonyPostfix]
    private static void After(TopView._WaitWithPopupCheckAsync_d__48 __instance) =>
        AsyncTrace.Step(__instance, "TopView.WaitWithPopup", "暂停");
}

/// <summary>TopView.LoadMovie 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._LoadMovieAsync_d__51), "MoveNext")]
internal static class Trace2_TopView_LoadMovie
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._LoadMovieAsync_d__51 __instance) =>
        AsyncTrace.Step(__instance, "TopView.LoadMovie", "进入");

    [HarmonyPostfix]
    private static void After(TopView._LoadMovieAsync_d__51 __instance) =>
        AsyncTrace.Step(__instance, "TopView.LoadMovie", "暂停");
}

/// <summary>TopView.PlayIn 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._PlayInAsync_d__53), "MoveNext")]
internal static class Trace2_TopView_PlayIn
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._PlayInAsync_d__53 __instance) =>
        AsyncTrace.Step(__instance, "TopView.PlayIn", "进入");

    [HarmonyPostfix]
    private static void After(TopView._PlayInAsync_d__53 __instance) =>
        AsyncTrace.Step(__instance, "TopView.PlayIn", "暂停");
}

/// <summary>TopView.PlayInFromPrologue 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._PlayInFromPrologueAsync_d__54), "MoveNext")]
internal static class Trace2_TopView_PlayInFromPrologue
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._PlayInFromPrologueAsync_d__54 __instance) =>
        AsyncTrace.Step(__instance, "TopView.PlayInFromPrologue", "进入");

    [HarmonyPostfix]
    private static void After(TopView._PlayInFromPrologueAsync_d__54 __instance) =>
        AsyncTrace.Step(__instance, "TopView.PlayInFromPrologue", "暂停");
}

/// <summary>TopView.SoundOption 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._OpenSoundOptionPopupAsync_d__55), "MoveNext")]
internal static class Trace2_TopView_SoundOption
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._OpenSoundOptionPopupAsync_d__55 __instance) =>
        AsyncTrace.Step(__instance, "TopView.SoundOption", "进入");

    [HarmonyPostfix]
    private static void After(TopView._OpenSoundOptionPopupAsync_d__55 __instance) =>
        AsyncTrace.Step(__instance, "TopView.SoundOption", "暂停");
}

/// <summary>TopView.Option 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._OpenOptionPopupAsync_d__56), "MoveNext")]
internal static class Trace2_TopView_Option
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._OpenOptionPopupAsync_d__56 __instance) =>
        AsyncTrace.Step(__instance, "TopView.Option", "进入");

    [HarmonyPostfix]
    private static void After(TopView._OpenOptionPopupAsync_d__56 __instance) =>
        AsyncTrace.Step(__instance, "TopView.Option", "暂停");
}

/// <summary>TopView.ShowTitle 状态机追踪。</summary>
[HarmonyPatch(typeof(TopView._ShowTitleAsync_d__57), "MoveNext")]
internal static class Trace2_TopView_ShowTitle
{
    /// <summary>诊断开关关闭时整类不安装。</summary>
    public static bool Enabled => Plugin.DiagAssets.Value;

    [HarmonyPrefix]
    private static void Before(TopView._ShowTitleAsync_d__57 __instance) =>
        AsyncTrace.Step(__instance, "TopView.ShowTitle", "进入");

    [HarmonyPostfix]
    private static void After(TopView._ShowTitleAsync_d__57 __instance) =>
        AsyncTrace.Step(__instance, "TopView.ShowTitle", "暂停");
}

