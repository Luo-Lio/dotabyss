using System;
using System.Reflection;
using HarmonyLib;

namespace StoryViewer.Patches;

/// <summary>
/// 0.7.22 加入 → 0.7.23 禁用:此 Harmony Finalizer 钩住 AppEngine.OnServiceRegistered
/// 会干扰 il2cpp async 初始化流,使服务注册读取到 null 数据(本机原本正常的 0.7.19
/// 在加了此补丁后反而触发 BitConverter.ToBoolean(null) → 剧情执行报错)。
/// <para>
/// 根因修复已由 DeployRuntimeConfigIfNeeded(嵌入资源释放) 完成,不再需要兜底补丁。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class EngineBootGuard_OnServiceRegistered
{
    /// <summary>0.7.23:永久禁用——Harmony 钩 il2cpp async 方法有副作用。</summary>
    public static bool Enabled => false;

    [HarmonyTargetMethod]
    private static MethodBase TargetMethod()
    {
        var t = Type.GetType("Project.AppEngine, Project", throwOnError: false)
             ?? AccessTools.TypeByName("Project.AppEngine");
        if (t == null) return null;
        return AccessTools.Method(t, "OnServiceRegistered");
    }

    [HarmonyFinalizer]
    private static Exception Finalize(Exception __exception)
    {
        if (__exception != null)
        {
            Plugin.Logger.LogWarning(
                $"[启动容错] AppEngine.OnServiceRegistered 异常已抑制(离线预期): " +
                $"{__exception.GetType().Name}: {__exception.Message}");
            return null;
        }
        return null;
    }
}
