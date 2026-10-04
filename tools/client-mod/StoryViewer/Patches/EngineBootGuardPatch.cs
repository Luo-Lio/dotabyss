using System;
using System.Reflection;
using HarmonyLib;

namespace StoryViewer.Patches;

/// <summary>
/// 0.7.22:抑制 AppEngine.OnServiceRegistered 的非致命崩溃。
/// <para>
/// 离线环境下,游戏的服务注册后置逻辑 (OnServiceRegistered) 会读取一个由
/// 服务器初始化流程填充的配置 byte[]——离线时该数组为 null → BitConverter.ToBoolean(null) 抛
/// ArgumentNullException → 异常向上传播到 Engine.InitializeServicesAsync → 引擎标记为 Failed →
/// 后续所有 Addressables.LoadSceneAsync / Absf 场景切换均失败 → 所有剧情黑屏。
/// </para>
/// 本补丁用 Finalizer 吞掉此异常,让引擎初始化继续完成。
/// </summary>
[HarmonyPatch]
internal static class EngineBootGuard_OnServiceRegistered
{
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod()
    {
        // Project.AppEngine 在 il2cpp interop 的 Project.dll 中;
        // 用反射查找以防 il2cpp 更新后类型路径变动。
        var t = Type.GetType("Project.AppEngine, Project", throwOnError: false)
             ?? AccessTools.TypeByName("Project.AppEngine");
        if (t == null) return null;
        return AccessTools.Method(t, "OnServiceRegistered");
    }

    /// <summary>
    /// Harmony Finalizer:若原方法抛出异常,记录日志后返回 null(吞掉)。
    /// </summary>
    [HarmonyFinalizer]
    private static Exception Finalize(Exception __exception)
    {
        if (__exception != null)
        {
            Plugin.Logger.LogWarning(
                $"[启动容错] AppEngine.OnServiceRegistered 异常已抑制(离线预期): " +
                $"{__exception.GetType().Name}: {__exception.Message}");
            return null; // swallow → caller sees success
        }
        return null;
    }
}
