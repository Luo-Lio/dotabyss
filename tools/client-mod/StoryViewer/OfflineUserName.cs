namespace StoryViewer;

/// <summary>
/// 提供离线剧情所需的用户显示名兜底。
/// </summary>
internal static class OfflineUserName
{
    /// <summary>离线档没有账号资料时使用的主人公称呼。</summary>
    internal const string Fallback = "司令官";

    /// <summary>
    /// 将未初始化的用户昵称转换为可安全传给正则替换的显示名。
    /// </summary>
    /// <param name="userName">游戏用户资料中的昵称，可为 null。</param>
    /// <returns>原昵称，或离线档的默认称呼。</returns>
    internal static string Resolve(string userName) => ResolveReplacement(userName);

    /// <summary>
    /// 将正则替换值中的 null 转换为离线档默认称呼。
    /// </summary>
    /// <param name="replacement">正则替换值，可为 null。</param>
    /// <returns>原替换值，或离线档的默认称呼。</returns>
    internal static string ResolveReplacement(string replacement) => replacement ?? Fallback;
}
