using System.Text.RegularExpressions;
using StoryViewer;
using StoryViewer.Patches;

OfflineUserNameTests.Run();
NullByteGuardTargetsTests.Run();

/// <summary>离线用户昵称兜底逻辑的最小行为测试。</summary>
internal static class OfflineUserNameTests
{
    /// <summary>运行 null、普通字符串和空字符串三个输入分区的断言。</summary>
    internal static void Run()
    {
        AssertEqual("司令官", OfflineUserName.Resolve(null!), "null 用户名必须使用离线兜底");
        AssertEqual("Alice", OfflineUserName.Resolve("Alice"), "非空用户名必须原样保留");
        AssertEqual(string.Empty, OfflineUserName.Resolve(string.Empty), "空字符串是合法的空替换，不能误改");
        AssertEqual("司令官", OfflineUserName.ResolveReplacement(null!), "null replacement 必须使用离线兜底");
        AssertEqual("Alice", OfflineUserName.ResolveReplacement("Alice"), "replacement 昵称必须原样保留");
        AssertEqual(string.Empty, OfflineUserName.ResolveReplacement(string.Empty), "空 replacement 必须保持为空字符串");
        AssertEqual(
            "欢迎，司令官",
            Regex.Replace("欢迎，<user>", "<user>", OfflineUserName.Resolve(null!)),
            "离线兜底值必须能作为 Regex.Replace 的 replacement");
        Console.WriteLine("OfflineUserName tests passed.");
    }

    /// <summary>比较期望值与实际值，失败时抛出可读断言异常。</summary>
    /// <param name="expected">期望结果。</param>
    /// <param name="actual">实际结果。</param>
    /// <param name="message">失败时显示的行为说明。</param>
    private static void AssertEqual(string expected, string? actual, string message)
    {
        if (!string.Equals(expected, actual, StringComparison.Ordinal))
            throw new InvalidOperationException($"{message}: expected={expected ?? "<null>"}, actual={actual ?? "<null>"}");
    }
}

/// <summary>空字节兜底目标表（NullByteGuardTargets）的结构、类型、默认值与边界测试。</summary>
internal static class NullByteGuardTargetsTests
{
    /// <summary>规范映射：目标表每一项的方法名与 Kind 必须与此处逐项一致（防名字对但 Kind 错）。</summary>
    private static readonly (string Name, NullByteKind Kind)[] Canonical =
    {
        ("ToBoolean", NullByteKind.Boolean),
        ("ToInt16", NullByteKind.Int16),
        ("ToInt32", NullByteKind.Int32),
    };

    /// <summary>运行表结构、枚举覆盖、CLR 类型、默认值转型与未知枚举值的断言。</summary>
    internal static void Run()
    {
        AssertTableShape();
        AssertClrTypesAndDefaults();
        AssertUnknownKindThrows();

        Console.WriteLine("NullByteGuardTargets tests passed.");
    }

    /// <summary>断言目标表恰好 3 项、方法名无重复、每个枚举值恰好出现一次、名字与 Kind 配对正确。</summary>
    private static void AssertTableShape()
    {
        AssertEqual(3, NullByteGuardTargets.All.Count, "兜底目标表必须恰好覆盖 3 个已知崩溃族重载");

        var names = new List<string>();
        var kinds = new List<NullByteKind>();
        foreach (var target in NullByteGuardTargets.All)
        {
            names.Add(target.MethodName);
            kinds.Add(target.Kind);
        }

        AssertEqual(names.Count, names.Distinct().Count(), "目标表的方法名不得重复");
        AssertEqual(kinds.Count, kinds.Distinct().Count(), "目标表的 Kind 不得重复");

        foreach (NullByteKind kind in Enum.GetValues<NullByteKind>())
            AssertEqual(1, kinds.Count(k => k == kind), $"枚举 {kind} 必须在目标表中恰好出现一次（枚举被完整覆盖）");
        AssertEqual(
            Enum.GetValues<NullByteKind>().Length,
            kinds.Distinct().Count(),
            "目标表必须覆盖全部 NullByteKind，不得漏项或多出表外枚举");

        // 名字与 Kind 必须成对正确：同名字若配了别的 Kind，兜底会返回错误类型。
        foreach (var expected in Canonical)
        {
            var matches = NullByteGuardTargets.All.Where(t => t.MethodName == expected.Name).ToList();
            AssertTrue(matches.Count == 1, $"目标表必须恰好包含方法 {expected.Name}");
            AssertEqual(
                expected.Kind,
                matches[0].Kind,
                $"{expected.Name} 的 Kind 必须是 {expected.Kind}（名字对但 Kind 错会让兜底返回错误类型）");
        }

        // 显式用规范配对构造目标，逐项与表中同项一致。
        for (int i = 0; i < Canonical.Length; i++)
        {
            var manual = new NullByteTarget(Canonical[i].Name, Canonical[i].Kind);
            AssertEqual(Canonical[i].Name, manual.MethodName, $"第 {i} 项的手工目标方法名必须回读为 {Canonical[i].Name}");
            AssertEqual(Canonical[i].Kind, manual.Kind, $"第 {i} 项的手工目标 Kind 必须回读为 {Canonical[i].Kind}");
            AssertEqual(
                manual.MethodName,
                NullByteGuardTargets.All[i].MethodName,
                $"目标表第 {i} 项必须是 {Canonical[i].Name}（顺序固定，日志按此顺序报告）");
            AssertEqual(
                manual.Kind,
                NullByteGuardTargets.All[i].Kind,
                $"目标表第 {i} 项的 Kind 必须是 {Canonical[i].Kind}");
        }
    }

    /// <summary>断言每个 Kind 的 CLR 类型与默认值正确，且默认值真的能按该 CLR 类型转型（装箱类型必须与声明类型一致）。</summary>
    private static void AssertClrTypesAndDefaults()
    {
        var expectedTypes = new Dictionary<NullByteKind, Type>
        {
            [NullByteKind.Boolean] = typeof(bool),
            [NullByteKind.Int16] = typeof(short),
            [NullByteKind.Int32] = typeof(int),
        };

        var expectedDefaults = new Dictionary<NullByteKind, object>
        {
            [NullByteKind.Boolean] = false,
            [NullByteKind.Int16] = (short)0,
            [NullByteKind.Int32] = 0,
        };

        // 真的做一次 (T)转型：装箱类型与声明类型不一致的错误只会在现场炸，必须在这里挡住。
        var castChecks = new Dictionary<NullByteKind, Func<object, bool>>
        {
            [NullByteKind.Boolean] = value => (bool)value == false,
            [NullByteKind.Int16] = value => (short)value == 0,
            [NullByteKind.Int32] = value => (int)value == 0,
        };

        foreach (NullByteKind kind in Enum.GetValues<NullByteKind>())
        {
            AssertEqual(
                expectedTypes[kind],
                NullByteGuardTargets.ClrTypeOf(kind),
                $"{kind} 的 CLR 类型必须是 {expectedTypes[kind].Name}");
            AssertEqual(
                expectedDefaults[kind],
                NullByteGuardTargets.DefaultOf(kind),
                $"{kind} 的默认值必须是 {expectedDefaults[kind]}");
            AssertTrue(
                castChecks[kind](NullByteGuardTargets.DefaultOf(kind)),
                $"{kind} 的默认值必须能按 {expectedTypes[kind].Name} 转型"
                + "（声明类型与装箱类型不一致时，Win10 现场会抛 InvalidCastException）");
        }
    }

    /// <summary>断言未知枚举值不会被静默当成合法值，必须抛 ArgumentOutOfRangeException。</summary>
    private static void AssertUnknownKindThrows()
    {
        const NullByteKind unknown = (NullByteKind)999;
        AssertThrowsArgumentOutOfRange(
            () => NullByteGuardTargets.ClrTypeOf(unknown),
            "(NullByteKind)999 传给 ClrTypeOf 必须抛 ArgumentOutOfRangeException");
        AssertThrowsArgumentOutOfRange(
            () => NullByteGuardTargets.DefaultOf(unknown),
            "(NullByteKind)999 传给 DefaultOf 必须抛 ArgumentOutOfRangeException");
    }

    /// <summary>比较期望值与实际值（装箱比较），失败时抛出可读断言异常。</summary>
    /// <param name="expected">期望结果。</param>
    /// <param name="actual">实际结果。</param>
    /// <param name="message">失败时显示的行为说明。</param>
    private static void AssertEqual(object? expected, object? actual, string message)
    {
        if (!Equals(expected, actual))
            throw new InvalidOperationException($"{message}: expected={expected ?? "<null>"}, actual={actual ?? "<null>"}");
    }

    /// <summary>断言条件为真，失败时抛出可读断言异常。</summary>
    /// <param name="condition">待断言的条件。</param>
    /// <param name="message">失败时显示的行为说明。</param>
    private static void AssertTrue(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException(message);
    }

    /// <summary>断言动作抛出 ArgumentOutOfRangeException，其它异常或无异常都视为失败。</summary>
    /// <param name="action">待执行的动作。</param>
    /// <param name="message">失败时显示的行为说明。</param>
    private static void AssertThrowsArgumentOutOfRange(Action action, string message)
    {
        try
        {
            action();
        }
        catch (ArgumentOutOfRangeException)
        {
            return;
        }
        catch (Exception e)
        {
            throw new InvalidOperationException($"{message}: 实际抛出 {e.GetType().Name}: {e.Message}");
        }

        throw new InvalidOperationException($"{message}: 但未抛出任何异常");
    }
}
