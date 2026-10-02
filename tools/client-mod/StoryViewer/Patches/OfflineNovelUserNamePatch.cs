using System;
using HarmonyLib;
using Il2CppRegex = Il2CppSystem.Text.RegularExpressions.Regex;
using Il2CppRegexOptions = Il2CppSystem.Text.RegularExpressions.RegexOptions;
using Il2CppTimeSpan = Il2CppSystem.TimeSpan;

namespace StoryViewer.Patches;

/// <summary>
/// 离线登录没有完整用户资料时，拦截 IL2CPP Regex 的四参数替换调用。
/// </summary>
[HarmonyPatch(typeof(Il2CppRegex), nameof(Il2CppRegex.Replace), new[]
{
    typeof(string), typeof(string), typeof(string), typeof(Il2CppRegexOptions),
})]
internal static class OfflineNovelUserNamePatch
{
    /// <summary>仅在本地假 API 模式启用，在线模式保持游戏原始行为。</summary>
    public static bool Enabled => Plugin.OfflineApi?.Value == true;

    /// <summary>
    /// 在四参数正则替换执行前补齐 null replacement。
    /// </summary>
    /// <param name="replacement">正则替换值，离线用户资料缺失时可能为 null。</param>
    [HarmonyPrefix]
    private static void Prefix(ref string replacement)
        => NormalizeReplacement(ref replacement);

    /// <summary>
    /// 将离线剧情的 null replacement 归一化为可安全传给 Regex 的字符串。
    /// </summary>
    /// <param name="replacement">待修改的正则替换值。</param>
    internal static void NormalizeReplacement(ref string replacement)
    {
        if (replacement != null)
            return;

        replacement = OfflineUserName.ResolveReplacement(replacement);
        PatchLog.Once("离线剧情:Regex.Replace 收到 null replacement，已使用“司令官”");
    }
}

/// <summary>
/// 离线登录没有完整用户资料时，拦截 IL2CPP Regex 的五参数替换调用。
/// </summary>
[HarmonyPatch(typeof(Il2CppRegex), nameof(Il2CppRegex.Replace), new[]
{
    typeof(string), typeof(string), typeof(string), typeof(Il2CppRegexOptions), typeof(Il2CppTimeSpan),
})]
internal static class OfflineNovelUserNameTimeoutPatch
{
    /// <summary>仅在本地假 API 模式启用，在线模式保持游戏原始行为。</summary>
    public static bool Enabled => Plugin.OfflineApi?.Value == true;

    /// <summary>
    /// 在五参数正则替换执行前补齐 null replacement。
    /// </summary>
    /// <param name="replacement">正则替换值，离线用户资料缺失时可能为 null。</param>
    [HarmonyPrefix]
    private static void Prefix(ref string replacement)
        => OfflineNovelUserNamePatch.NormalizeReplacement(ref replacement);
}
