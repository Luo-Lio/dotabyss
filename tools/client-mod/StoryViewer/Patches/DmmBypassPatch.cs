using System;
using System.Reflection;
using Cysharp.Threading.Tasks;
using HarmonyLib;

namespace StoryViewer.Patches;

/// <summary>
/// DMM SDK 初始化的离线旁路(2026-09-23)。
/// <para>
/// 背景与教训:
/// 1) 14:36 那轮 SDK 初始化失败 → 游戏的包装层置位 <c>HasDmmSdkBootFailure</c> → 标题画面弹
///    「初期化に失敗しました。アプリケーションを再起動してください。」,启动流程整段中止(无任何 API 请求);
/// 2) 14:45 那轮的「白屏闪退」是<b>诊断补丁自身</b>的问题:对 <c>Absf.DmmPlatforms.DmmSdk.Log(string)</c>
///    打点时机身收到非法字符串指针,`Il2CppStringToManaged` 触发 CLR fatal error(0x80131506)。
///    结论:对 SDK 层方法不要声明 <c>string</c> 参数,也不要包 delegate 回调。
/// </para>
/// <para>
/// 因此这里改为「最安全的旁路」:直接把游戏包装层的 <c>Initialize</c> 短路
/// —— 不调用原生 SDK,直接走成功回调并返回已完成 UniTask。
/// DMM SDK 的原生层自己解析命令行(settings.CommandPrefix),managed 侧补丁绕不过它,
/// 而离线模式本来就不需要 DMM 账号功能。
/// 由 <see cref="Plugin.ForceDmmSdkSuccess"/> 控制,默认关闭。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class Dmm_PlatformInitBypass
{
    /// <summary>定位 Absf.DmmPlatforms.DmmSdk.Initialize(ct, onSuccess, onError)。</summary>
    [HarmonyTargetMethod]
    private static MethodBase Target() =>
        StartupDiag.Of(typeof(Absf.DmmPlatforms.DmmSdk), "Initialize");

    /// <summary>配置打开时跳过原生 SDK 初始化,直接回调成功并返回已完成的 UniTask。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppSystem.Action onSuccess, ref UniTask __result)
    {
        if (!Plugin.ForceDmmSdkSuccess.Value)
            return true;

        StartupDiag.Log("DmmPlatformInitSkip", "离线旁路:跳过 DMM SDK 初始化,直接调用成功回调");
        try
        {
            onSuccess?.Invoke();
        }
        catch (Exception e)
        {
            StartupDiag.Log("DmmPlatformInitSkipEx", $"onSuccess 调用异常: {e.GetType().Name}: {e.Message}");
        }
        __result = UniTask.CompletedTask;
        return false;
    }
}
