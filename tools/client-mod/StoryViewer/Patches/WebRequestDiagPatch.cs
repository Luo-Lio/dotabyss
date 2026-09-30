using System;
using System.Collections.Concurrent;
using System.Text;
using System.Threading;
using HarmonyLib;
using UnityEngine.Networking;

namespace StoryViewer.Patches;

/// <summary>
/// 网络请求诊断:记录所有发出的 <see cref="UnityWebRequest"/>。
/// <para>
/// 用途:离线排查时确认客户端是否在请求外部地址(卡住但本机假服务器收不到请求时,
/// 说明请求打到别处去了;按主机聚合的次数会打印在资产快照里)。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class WebRequestSendDiagPatch
{
    /// <summary>诊断开关:关闭时本类补丁不安装(纯日志,不影响功能)。</summary>
    public static bool Enabled => AssetDiag.Diag;
    /// <summary>按主机名聚合的发送次数(线程安全)。</summary>
    private static readonly ConcurrentDictionary<string, int> HostCounts = new();

    private static int _logged;

    /// <summary>记录发送目标:前 150 条打明细,全部计入按主机统计。</summary>
    [HarmonyPatch(typeof(UnityWebRequest), nameof(UnityWebRequest.SendWebRequest))]
    [HarmonyPrefix]
    private static void Prefix(UnityWebRequest __instance)
    {
        if (!AssetDiag.Diag)
            return;
        string url;
        try
        {
            url = __instance.url;
        }
        catch
        {
            return;
        }
        if (string.IsNullOrEmpty(url))
            return;
        HostCounts.AddOrUpdate(HostOf(url), 1, (_, v) => v + 1);
        if (Interlocked.Increment(ref _logged) <= 150)
            Plugin.Logger.LogInfo($"[网络] 发送 {Shorten(url)}");
    }

    /// <summary>按主机聚合计数的摘要(供资产快照打印)。</summary>
    internal static string Summary()
    {
        if (HostCounts.IsEmpty)
            return "(无)";
        var sb = new StringBuilder();
        foreach (var kv in HostCounts)
        {
            if (sb.Length > 0)
                sb.Append(", ");
            sb.Append(kv.Key).Append('=').Append(kv.Value);
        }
        return sb.ToString();
    }

    /// <summary>取 URL 的主机部分(解析失败时返回原串截断)。</summary>
    private static string HostOf(string url)
    {
        int scheme = url.IndexOf("://", StringComparison.Ordinal);
        if (scheme < 0)
            return "(无主机)";
        int end = url.IndexOf('/', scheme + 3);
        string host = end < 0 ? url[(scheme + 3)..] : url[(scheme + 3)..end];
        return string.IsNullOrEmpty(host) ? "(空主机)" : host;
    }

    /// <summary>URL 过长时截断,避免刷爆日志。</summary>
    private static string Shorten(string url) => url.Length > 160 ? url[..160] + "…" : url;
}
