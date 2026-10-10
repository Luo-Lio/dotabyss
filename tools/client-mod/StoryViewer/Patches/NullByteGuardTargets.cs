// 空字节兜底的目标表(纯逻辑文件:不得引用 Unity / Il2Cpp / Harmony / 游戏类型,
// 会被 StoryViewer.Tests 独立编译断言)。
//
// ① 兜底的语义只有一个:游戏把 null 字节数组交给 BitConverter 时,按该类型的默认值返回;
//    非 null 时完全透传原方法,不改变任何正常路径的行为。
// ② 表里只收已知会被 null 字节数组击穿的 3 个重载,刻意排除其它类型与 BitConverter.ToString。
//    0.7.29 曾把目标扩到全部 10 个「从字节数组读一个值」的重载;对 ToUInt32 等目标安装
//    Harmony detour 后,托管代理与 il2cpp_runtime_invoke 会无限互递归并栈溢出(0xc00000fd),
//    因此 0.7.30 回退为 ToBoolean / ToInt16 / ToInt32 这 3 个已知崩溃族。
// ③ 覆盖范围做成表(而不是散落的三段代码),是为了让「兜底到底覆盖了哪些重载」成为一份
//    可审阅、可测试的数据:解析器按 MethodName + 返回类型匹配,测试可断言表本身的完整性。
using System;
using System.Collections.Generic;

namespace StoryViewer.Patches;

/// <summary>BitConverter「从字节数组读一个值」的返回类型标识。</summary>
internal enum NullByteKind
{
    /// <summary><see cref="bool"/>:BitConverter.ToBoolean。</summary>
    Boolean,

    /// <summary><see cref="short"/>:BitConverter.ToInt16。</summary>
    Int16,

    /// <summary><see cref="int"/>:BitConverter.ToInt32。</summary>
    Int32,
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
/// 空字节兜底的目标表:只覆盖已知会被 null 字节数组击穿的 3 个重载。
/// <para>
/// 0.7.29 把目标扩到 10 个重载后,对 ToUInt32 等目标安装 Harmony detour 会让托管代理与
/// il2cpp_runtime_invoke 无限互递归并栈溢出(0xc00000fd),所以 0.7.30 回退为
/// ToBoolean / ToInt16 / ToInt32。表是覆盖范围的单一事实来源:补丁类据此定位目标、取默认值,
/// 启动日志据此报告覆盖情况。
/// </para>
/// </summary>
internal static class NullByteGuardTargets
{
    /// <summary>全部兜底目标,顺序固定为 ToBoolean / ToInt16 / ToInt32(日志与测试按此顺序报告)。</summary>
    public static IReadOnlyList<NullByteTarget> All { get; } = new NullByteTarget[]
    {
        new NullByteTarget("ToBoolean", NullByteKind.Boolean),
        new NullByteTarget("ToInt16", NullByteKind.Int16),
        new NullByteTarget("ToInt32", NullByteKind.Int32),
    };

    /// <summary>取该返回类型标识对应的 CLR 类型;未知枚举值直接抛异常。</summary>
    /// <param name="kind">返回类型标识。</param>
    /// <returns>对应的 CLR 类型(bool/short/int)。</returns>
    /// <exception cref="ArgumentOutOfRangeException">传入表中未定义的枚举值时抛出。</exception>
    public static Type ClrTypeOf(NullByteKind kind) => kind switch
    {
        NullByteKind.Boolean => typeof(bool),
        NullByteKind.Int16 => typeof(short),
        NullByteKind.Int32 => typeof(int),
        _ => throw new ArgumentOutOfRangeException(nameof(kind), kind, "未知的 NullByteKind,不在兜底表内"),
    };

    /// <summary>
    /// 取该返回类型标识的默认值(装箱形式,已按对应 CLR 类型装箱,可直接转型)。
    /// </summary>
    /// <param name="kind">返回类型标识。</param>
    /// <returns>对应类型的零值:bool=false、数值型为 0。</returns>
    /// <exception cref="ArgumentOutOfRangeException">传入表中未定义的枚举值时抛出。</exception>
    public static object DefaultOf(NullByteKind kind) => kind switch
    {
        NullByteKind.Boolean => false,
        NullByteKind.Int16 => (short)0,
        NullByteKind.Int32 => 0,
        _ => throw new ArgumentOutOfRangeException(nameof(kind), kind, "未知的 NullByteKind,不在兜底表内"),
    };
}
