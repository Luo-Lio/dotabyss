using System;
using System.Reflection;
using System.Threading;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

namespace StoryViewer.Patches;

/// <summary>
/// 按方法名和参数形状解析 Il2CPP 的 BitConverter 方法。
/// <para>
/// 这里不能直接假定参数是托管 byte[]:当前 interop 代理实际使用
/// <see cref="Il2CppStructArray{T}"/>。解析失败只记警告并返回 null,不阻止其它补丁加载。
/// </para>
/// </summary>
internal static class NullByteGuardResolver
{
    /// <summary>
    /// 找到指定返回类型的 BitConverter 字节数组读取方法。
    /// </summary>
    /// <param name="methodName">要解析的方法名。</param>
    /// <param name="returnType">预期返回类型。</param>
    /// <returns>匹配的方法,找不到或反射失败时返回 null。</returns>
    public static MethodBase Find(string methodName, Type returnType)
    {
        try
        {
            Type byteArrayType = typeof(Il2CppStructArray<byte>);
            foreach (var method in typeof(Il2CppSystem.BitConverter).GetMethods(
                BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
            {
                var parameters = method.GetParameters();
                if (method.Name != methodName
                    || method.ReturnType != returnType
                    || (parameters.Length != 1 && parameters.Length != 2)
                    || parameters[0].ParameterType != byteArrayType
                    || (parameters.Length == 2 && parameters[1].ParameterType != typeof(int)))
                    continue;

                return method;
            }

            Plugin.Logger?.LogWarning(
                $"[空字节兜底] 未找到 Il2CppSystem.BitConverter.{methodName} "
                + "(Il2CppStructArray<byte>[, int]),该补丁类自动跳过");
        }
        catch (Exception e)
        {
            Plugin.Logger?.LogWarning(
                $"[空字节兜底] 解析 BitConverter.{methodName} 失败,该补丁类自动跳过: "
                + $"{e.GetType().Name}: {e.Message}");
        }

        return null;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToBoolean 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToBoolean
{
    /// <summary>配置开关:关闭时整个补丁类不安装。</summary>
    public static bool Enabled => Plugin.GuardNullBitConverter.Value;

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToBoolean 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find("ToBoolean", typeof(bool));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref bool __result)
    {
        if (value != null)
            return true;

        __result = false;
        NullByteGuardLog.LogOnce(ref _logged, "ToBoolean", "false");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToInt16 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToInt16
{
    /// <summary>配置开关:关闭时整个补丁类不安装。</summary>
    public static bool Enabled => Plugin.GuardNullBitConverter.Value;

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToInt16 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find("ToInt16", typeof(short));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref short __result)
    {
        if (value != null)
            return true;

        __result = 0;
        NullByteGuardLog.LogOnce(ref _logged, "ToInt16", "0");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToInt32 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToInt32
{
    /// <summary>配置开关:关闭时整个补丁类不安装。</summary>
    public static bool Enabled => Plugin.GuardNullBitConverter.Value;

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToInt32 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find("ToInt32", typeof(int));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref int __result)
    {
        if (value != null)
            return true;

        __result = 0;
        NullByteGuardLog.LogOnce(ref _logged, "ToInt32", "0");
        return false;
    }
}

/// <summary>空字节兜底补丁的单次日志工具。</summary>
internal static class NullByteGuardLog
{
    /// <summary>每个目标补丁只记录一次命中日志。</summary>
    /// <param name="logged">该目标的原子日志标记。</param>
    /// <param name="methodName">命中的 BitConverter 方法名。</param>
    /// <param name="defaultValue">返回的默认值文本。</param>
    public static void LogOnce(ref int logged, string methodName, string defaultValue)
    {
        if (Interlocked.Exchange(ref logged, 1) != 0)
            return;

        Plugin.Logger?.LogInfo(
            $"[空字节兜底] BitConverter.{methodName}(null) → {defaultValue}(离线预期)");
    }
}
