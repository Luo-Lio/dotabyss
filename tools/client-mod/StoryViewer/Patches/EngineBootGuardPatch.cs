using System;
using System.Reflection;
using HarmonyLib;

namespace StoryViewer.Patches;

/// <summary>
/// fresh install 兜底:AppEngine.OnServiceRegistered 在 <b>Windows 10</b> 上会读到 null
/// 字节 → BitConverter.ToBoolean(null) 抛异常 → InitializeServicesAsync 中断 → 黑屏/卡启动。
/// 本 Finalizer 抑制这个离线预期内的异常,让引擎初始化继续走完。
/// <para>
/// 版本沿革:0.7.22 加入 → 0.7.23 误判禁用 → 0.7.25 重新启用。
/// 0.7.23 以为“Harmony 钩 il2cpp async 方法有副作用”而禁用,但玩家侧 fresh install
/// 在 0.7.24(无 guard)下直接重现该崩溃、反而不可用;当初本机那次“回归”实为
/// caches_update 清单含非法路径导致的更新失败(已独立修复),与本补丁无关。
/// 本补丁只对**同步 void** 方法加 Finalizer(不碰 __args、不短路、不碰 __result),
/// 不属“钩 async 状态机”那一类陷阱,安全。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class EngineBootGuard_OnServiceRegistered
{
    /// <summary>0.7.25:重新启用——fresh install 需要它抑制 OnServiceRegistered 的离线预期崩溃。</summary>
    public static bool Enabled => true;

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
