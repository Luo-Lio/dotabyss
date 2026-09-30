using System.Text.RegularExpressions;
using StoryViewer;

OfflineUserNameTests.Run();

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
