// 空字节兜底的目标表(纯逻辑文件:不得引用 Unity / Il2Cpp / Harmony / 游戏类型,
// 会被 StoryViewer.Tests 独立编译断言)。
//
// ① 兜底的语义只有一个:游戏把 null 字节数组交给 BitConverter 时,按该类型的默认值返回;
//    非 null 时完全透传原方法,不改变任何正常路径的行为。
// ② 表里只收「从字节数组读一个值」的重载,刻意排除 BitConverter.ToString:它返回字符串,
//    不属于这一族;而且它对本就是空数组的输入会合法地返回空串,给它兜底只会掩盖问题而非修复。
// ③ 覆盖范围做成表(而不是散落的十段代码),是为了让「兜底到底覆盖了哪些重载」成为一份
//    可审阅、可测试的数据:解析器按 MethodName + 返回类型匹配,测试可断言表本身的完整性。
using System;
using System.Collections.Generic;

namespace StoryViewer.Patches;

/// <summary>BitConverter「从字节数组读一个值」的返回类型标识。</summary>
internal enum NullByteKind
{
    /// <summary><see cref="bool"/>:BitConverter.ToBoolean。</summary>
    Boolean,

    /// <summary><see cref="char"/>:BitConverter.ToChar。</summary>
    Char,

    /// <summary><see cref="short"/>:BitConverter.ToInt16。</summary>
    Int16,

    /// <summary><see cref="int"/>:BitConverter.ToInt32。</summary>
    Int32,

    /// <summary><see cref="long"/>:BitConverter.ToInt64。</summary>
    Int64,

    /// <summary><see cref="ushort"/>:BitConverter.ToUInt16。</summary>
    UInt16,

    /// <summary><see cref="uint"/>:BitConverter.ToUInt32。</summary>
    UInt32,

    /// <summary><see cref="ulong"/>:BitConverter.ToUInt64。</summary>
    UInt64,

    /// <summary><see cref="float"/>:BitConverter.ToSingle。</summary>
    Single,

    /// <summary><see cref="double"/>:BitConverter.ToDouble。</summary>
    Double,
}

/// <summary>一个待兜底的 BitConverter 目标:IL2CPP 侧方法名 + 返回类型标识。</summary>
internal readonly struct NullByteTarget
{
    /// <summary>初始化一个兜底目标。</summary>
    /// <param name="methodName">IL2CPP 侧的 BitConverter 方法名(如 ToBoolean)。</param>
    /// <param name="kind">该方法的返回类型标识。</param>
    public NullByteTarget(string methodName, NullByteKind kind)
    {
        MethodName = methodName;
        Kind = kind;
    }

    /// <summary>IL2CPP 侧的 BitConverter 方法名(如 ToBoolean);用于反射定位重载。</summary>
    public string MethodName { get; }

    /// <summary>该方法的返回类型标识;用于取 CLR 类型与默认值。</summary>
    public NullByteKind Kind { get; }
}

/// <summary>
/// 空字节兜底的目标表:覆盖 BitConverter 中全部「从字节数组读一个值」的重载。
/// <para>
/// 表是覆盖范围的单一事实来源:补丁类据此定位目标、取默认值,启动日志据此报告覆盖情况。
/// </para>
/// </summary>
internal static class NullByteGuardTargets
{
    /// <summary>全部兜底目标,顺序固定(日志与测试按此顺序报告)。</summary>
    public static IReadOnlyList<NullByteTarget> All { get; } = new NullByteTarget[]
    {
        new NullByteTarget("ToBoolean", NullByteKind.Boolean),
        new NullByteTarget("ToChar", NullByteKind.Char),
        new NullByteTarget("ToInt16", NullByteKind.Int16),
        new NullByteTarget("ToInt32", NullByteKind.Int32),
        new NullByteTarget("ToInt64", NullByteKind.Int64),
        new NullByteTarget("ToUInt16", NullByteKind.UInt16),
        new NullByteTarget("ToUInt32", NullByteKind.UInt32),
        new NullByteTarget("ToUInt64", NullByteKind.UInt64),
        new NullByteTarget("ToSingle", NullByteKind.Single),
        new NullByteTarget("ToDouble", NullByteKind.Double),
    };

    /// <summary>取该返回类型标识对应的 CLR 类型;未知枚举值直接抛异常。</summary>
    /// <param name="kind">返回类型标识。</param>
    /// <returns>对应的 CLR 类型(bool/char/short/int/long/ushort/uint/ulong/float/double)。</returns>
    /// <exception cref="ArgumentOutOfRangeException">传入表中未定义的枚举值时抛出。</exception>
    public static Type ClrTypeOf(NullByteKind kind) => kind switch
    {
        NullByteKind.Boolean => typeof(bool),
        NullByteKind.Char => typeof(char),
        NullByteKind.Int16 => typeof(short),
        NullByteKind.Int32 => typeof(int),
        NullByteKind.Int64 => typeof(long),
        NullByteKind.UInt16 => typeof(ushort),
        NullByteKind.UInt32 => typeof(uint),
        NullByteKind.UInt64 => typeof(ulong),
        NullByteKind.Single => typeof(float),
        NullByteKind.Double => typeof(double),
        _ => throw new ArgumentOutOfRangeException(nameof(kind), kind, "未知的 NullByteKind,不在兜底表内"),
    };

    /// <summary>
    /// 取该返回类型标识的默认值(装箱形式,已按对应 CLR 类型装箱,可直接转型)。
    /// </summary>
    /// <param name="kind">返回类型标识。</param>
    /// <returns>对应类型的零值:bool=false、char=0 字符、数值型为 0。</returns>
    /// <exception cref="ArgumentOutOfRangeException">传入表中未定义的枚举值时抛出。</exception>
    public static object DefaultOf(NullByteKind kind) => kind switch
    {
        NullByteKind.Boolean => false,
        NullByteKind.Char => '\0',
        NullByteKind.Int16 => (short)0,
        NullByteKind.Int32 => 0,
        NullByteKind.Int64 => 0L,
        NullByteKind.UInt16 => (ushort)0,
        NullByteKind.UInt32 => 0u,
        NullByteKind.UInt64 => 0UL,
        NullByteKind.Single => 0f,
        NullByteKind.Double => 0d,
        _ => throw new ArgumentOutOfRangeException(nameof(kind), kind, "未知的 NullByteKind,不在兜底表内"),
    };

    /// <summary>
    /// 是否属于已知崩溃族(缺了必须告警):Boolean / Int16 / Int32 是玩家现场证实会被 null 击穿的三个重载。
    /// </summary>
    /// <param name="kind">返回类型标识。</param>
    /// <returns>属于已知崩溃族返回 true,其余返回 false。</returns>
    /// <exception cref="ArgumentOutOfRangeException">传入表中未定义的枚举值时抛出。</exception>
    public static bool IsCore(NullByteKind kind) => kind switch
    {
        NullByteKind.Boolean or NullByteKind.Int16 or NullByteKind.Int32 => true,
        NullByteKind.Char
            or NullByteKind.Int64
            or NullByteKind.UInt16
            or NullByteKind.UInt32
            or NullByteKind.UInt64
            or NullByteKind.Single
            or NullByteKind.Double => false,
        _ => throw new ArgumentOutOfRangeException(nameof(kind), kind, "未知的 NullByteKind,不在兜底表内"),
    };
}
