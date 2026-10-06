using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

namespace StoryViewer.Patches;

/// <summary>
/// 按目标表解析 Il2CPP 的 BitConverter 方法,并缓存「哪些目标在当前 interop 里可用」。
/// <para>
/// 这里不能直接假定参数是托管 byte[]:当前 interop 代理实际使用
/// <see cref="Il2CppStructArray{T}"/>。不同本体版本的 interop 暴露的重载并不一致,
/// 因此要先探明可用清单:不存在的重载绝不能走进 Harmony 安装(否则
/// <c>CreateClassProcessor().Patch()</c> 会抛异常,被 <see cref="PatchManager"/> 记成
/// 「补丁 X 安装失败」的 Error,看起来像故障),而应让补丁类按配置跳过。
/// 解析失败只记警告并按「全部不可用」处理,不阻止其它补丁加载。
/// </para>
/// </summary>
internal static class NullByteGuardResolver
{
    /// <summary>惰性枚举的结果缓存:目标 → 实际方法(只枚举一次)。</summary>
    private static Dictionary<NullByteKind, MethodBase> _resolved;

    /// <summary>保护惰性枚举的锁(安装期与日志期可能来自不同线程)。</summary>
    private static readonly object Gate = new object();

    /// <summary>当前 interop 是否暴露了该目标的字节数组重载。</summary>
    /// <param name="kind">返回类型标识。</param>
    /// <returns>暴露且可解析返回 true,否则返回 false。</returns>
    public static bool IsAvailable(NullByteKind kind) => ResolveAll().ContainsKey(kind);

    /// <summary>
    /// 找到目标对应的 BitConverter 重载:方法名相同、返回类型为目标的 CLR 类型、
    /// 参数形状为 <c>(Il2CppStructArray&lt;byte&gt;)</c> 或 <c>(Il2CppStructArray&lt;byte&gt;, int)</c>。
    /// </summary>
    /// <param name="target">要解析的目标(方法名 + 返回类型标识)。</param>
    /// <returns>匹配的方法;当前 interop 未暴露该重载时返回 null。</returns>
    public static MethodBase Find(NullByteTarget target)
    {
        if (ResolveAll().TryGetValue(target.Kind, out var method))
            return method;

        Plugin.Logger?.LogWarning(
            $"[空字节兜底] 未找到 Il2CppSystem.BitConverter.{target.MethodName} "
            + "(Il2CppStructArray<byte>[, int]),该补丁类自动跳过");
        return null;
    }

    /// <summary>
    /// 惰性枚举一次 Il2CppSystem.BitConverter,得到「哪些目标可用」的缓存。
    /// </summary>
    /// <returns>目标 → 方法的字典;枚举失败时返回空字典(只告警一次)。</returns>
    private static Dictionary<NullByteKind, MethodBase> ResolveAll()
    {
        lock (Gate)
        {
            if (_resolved != null)
                return _resolved;

            var found = new Dictionary<NullByteKind, MethodBase>();
            try
            {
                Type byteArrayType = typeof(Il2CppStructArray<byte>);
                foreach (var method in typeof(Il2CppSystem.BitConverter).GetMethods(
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
                {
                    foreach (var target in NullByteGuardTargets.All)
                    {
                        if (found.ContainsKey(target.Kind) || !Matches(method, target, byteArrayType))
                            continue;

                        found[target.Kind] = method;
                        break;
                    }
                }
            }
            catch (Exception e)
            {
                Plugin.Logger?.LogWarning(
                    "[空字节兜底] 枚举 Il2CppSystem.BitConverter 失败,本次全部目标视为不可用: "
                    + $"{e.GetType().Name}: {e.Message}");
                found.Clear();
            }

            _resolved = found;
            return _resolved;
        }
    }

    /// <summary>判断一个反射方法是否就是目标要兜底的那一个重载。</summary>
    /// <param name="method">待判断的方法。</param>
    /// <param name="target">目标(方法名 + 返回类型标识)。</param>
    /// <param name="byteArrayType">当前 interop 的 <c>Il2CppStructArray&lt;byte&gt;</c> 类型。</param>
    /// <returns>完全匹配返回 true。</returns>
    private static bool Matches(MethodInfo method, NullByteTarget target, Type byteArrayType)
    {
        var parameters = method.GetParameters();
        return method.Name == target.MethodName
            && method.ReturnType == NullByteGuardTargets.ClrTypeOf(target.Kind)
            && (parameters.Length == 1 || parameters.Length == 2)
            && parameters[0].ParameterType == byteArrayType
            && (parameters.Length == 1 || parameters[1].ParameterType == typeof(int));
    }

    /// <summary>
    /// 在补丁安装完成后报告兜底覆盖情况,让「兜底到底装上没有」在启动日志里一眼可见。
    /// <para>
    /// 文本固定包含「BitConverter」与「空字节兜底」两个关键词,启动器的诊断摘要靠它们抽取。
    /// </para>
    /// </summary>
    public static void LogSummary()
    {
        if (!Plugin.GuardNullBitConverter.Value)
        {
            Plugin.Logger?.LogInfo("[空字节兜底] BitConverter 兜底已按配置关闭(GuardNullBitConverter=false)");
            return;
        }

        var covered = new List<string>();
        var missing = new List<NullByteTarget>();
        var missingCore = new List<string>();
        foreach (var target in NullByteGuardTargets.All)
        {
            if (IsAvailable(target.Kind))
            {
                covered.Add(target.MethodName);
                continue;
            }

            missing.Add(target);
            if (NullByteGuardTargets.IsCore(target.Kind))
                missingCore.Add(target.MethodName);
        }

        Plugin.Logger?.LogInfo(
            $"[空字节兜底] BitConverter 保护已安装: {covered.Count}/{NullByteGuardTargets.All.Count} 目标"
            + $"(已覆盖: {string.Join(", ", covered)})");

        if (missing.Count == 0)
            return;

        string text = $"[空字节兜底] BitConverter 未覆盖: {string.Join(", ", MethodNamesOf(missing))}"
            + "(该 interop 未暴露该重载,该重载不受保护)";
        if (missingCore.Count > 0)
        {
            text += $"; 已知崩溃族未受保护({string.Join(", ", missingCore)}),请人工确认";
            Plugin.Logger?.LogWarning(text);
        }
        else
        {
            Plugin.Logger?.LogInfo(text);
        }
    }

    /// <summary>把目标列表转成方法名列表,供日志拼接。</summary>
    /// <param name="targets">目标列表。</param>
    /// <returns>按原顺序排列的方法名列表。</returns>
    private static List<string> MethodNamesOf(List<NullByteTarget> targets)
    {
        var names = new List<string>(targets.Count);
        foreach (var target in targets)
            names.Add(target.MethodName);
        return names;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToBoolean 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToBoolean
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.Boolean);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToBoolean 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToBoolean", NullByteKind.Boolean));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref bool __result)
    {
        if (value != null)
            return true;

        __result = (bool)NullByteGuardTargets.DefaultOf(NullByteKind.Boolean);
        NullByteGuardLog.LogOnce(ref _logged, "ToBoolean", "false");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToChar 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToChar
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.Char);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToChar 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToChar", NullByteKind.Char));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref char __result)
    {
        if (value != null)
            return true;

        __result = (char)NullByteGuardTargets.DefaultOf(NullByteKind.Char);
        NullByteGuardLog.LogOnce(ref _logged, "ToChar", "'\\0'");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToInt16 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToInt16
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.Int16);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToInt16 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToInt16", NullByteKind.Int16));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref short __result)
    {
        if (value != null)
            return true;

        __result = (short)NullByteGuardTargets.DefaultOf(NullByteKind.Int16);
        NullByteGuardLog.LogOnce(ref _logged, "ToInt16", "0");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToInt32 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToInt32
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.Int32);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToInt32 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToInt32", NullByteKind.Int32));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref int __result)
    {
        if (value != null)
            return true;

        __result = (int)NullByteGuardTargets.DefaultOf(NullByteKind.Int32);
        NullByteGuardLog.LogOnce(ref _logged, "ToInt32", "0");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToInt64 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToInt64
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.Int64);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToInt64 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToInt64", NullByteKind.Int64));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref long __result)
    {
        if (value != null)
            return true;

        __result = (long)NullByteGuardTargets.DefaultOf(NullByteKind.Int64);
        NullByteGuardLog.LogOnce(ref _logged, "ToInt64", "0");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToUInt16 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToUInt16
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.UInt16);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToUInt16 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToUInt16", NullByteKind.UInt16));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref ushort __result)
    {
        if (value != null)
            return true;

        __result = (ushort)NullByteGuardTargets.DefaultOf(NullByteKind.UInt16);
        NullByteGuardLog.LogOnce(ref _logged, "ToUInt16", "0");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToUInt32 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToUInt32
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.UInt32);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToUInt32 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToUInt32", NullByteKind.UInt32));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref uint __result)
    {
        if (value != null)
            return true;

        __result = (uint)NullByteGuardTargets.DefaultOf(NullByteKind.UInt32);
        NullByteGuardLog.LogOnce(ref _logged, "ToUInt32", "0");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToUInt64 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToUInt64
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.UInt64);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToUInt64 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToUInt64", NullByteKind.UInt64));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref ulong __result)
    {
        if (value != null)
            return true;

        __result = (ulong)NullByteGuardTargets.DefaultOf(NullByteKind.UInt64);
        NullByteGuardLog.LogOnce(ref _logged, "ToUInt64", "0");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToSingle 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToSingle
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.Single);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToSingle 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToSingle", NullByteKind.Single));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref float __result)
    {
        if (value != null)
            return true;

        __result = (float)NullByteGuardTargets.DefaultOf(NullByteKind.Single);
        NullByteGuardLog.LogOnce(ref _logged, "ToSingle", "0f");
        return false;
    }
}

/// <summary>
/// 兜底保护 BitConverter.ToDouble 的 null 字节数组调用。
/// <para>
/// 只处理字节数组为 null 的情况;非 null 时完全透传原逻辑。默认值取自
/// <see cref="NullByteGuardTargets.DefaultOf"/>。IL2CPP 可能把 BCL
/// 小方法内联到调用点,导致此 detour 不生效;这是尝试性修复,不生效时不改变原有行为。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class NullByteGuard_ToDouble
{
    /// <summary>配置开关:关闭时整个补丁类不安装;目标重载不存在时同样不安装(避免安装失败被记成故障)。</summary>
    public static bool Enabled =>
        Plugin.GuardNullBitConverter.Value && NullByteGuardResolver.IsAvailable(NullByteKind.Double);

    private static int _logged;

    /// <summary>定位当前 interop 版本中 ToDouble 的字节数组重载。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        NullByteGuardResolver.Find(new NullByteTarget("ToDouble", NullByteKind.Double));

    /// <summary>空数组时返回离线默认值;非空数组继续调用原方法。</summary>
    [HarmonyPrefix]
    private static bool Prefix(Il2CppStructArray<byte> value, ref double __result)
    {
        if (value != null)
            return true;

        __result = (double)NullByteGuardTargets.DefaultOf(NullByteKind.Double);
        NullByteGuardLog.LogOnce(ref _logged, "ToDouble", "0d");
        return false;
    }
}

/// <summary>空字节兜底补丁的单次日志工具。</summary>
internal static class NullByteGuardLog
{
    /// <summary>每个目标补丁只记录一次命中日志。</summary>
    /// <param name="logged">该目标的原子日志标记。</param>
    /// <param name="methodName">命中的 BitConverter 方法名。</param>
    /// <param name="defaultValue">返回的默认值文本(便于阅读的显示形式)。</param>
    public static void LogOnce(ref int logged, string methodName, string defaultValue)
    {
        if (Interlocked.Exchange(ref logged, 1) != 0)
            return;

        Plugin.Logger?.LogInfo(
            $"[空字节兜底] BitConverter.{methodName}(null) → {defaultValue}(离线预期)");
    }
}
