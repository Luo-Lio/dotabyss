using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using Absf.Asset.AddressableAssets;
using BepInEx;
using HarmonyLib;
using UnityEngine.ResourceManagement.ResourceLocations;

namespace StoryViewer.Patches;

/// <summary>
/// 离线资产管线的诊断与工具(不含补丁本体)。
/// <para>
/// 背景(2026-09-23 实机):客户端加载 catalog 时请求
/// <c>https://api.abyss-prod-r18.dotabyss.dmmgames.com/resources/windows/r18/aas/&lt;ver&gt;/aa/catalog_1.bin</c>,
/// 无网络时 403,启动流程卡在标题。
/// </para>
/// <para>
/// 机制(interop 反编译 + 实机快照):<c>Absf.Asset.AddressableAssets.AddressablesProfileDefine</c> 是
/// Addressables 的 InternalId 转换器:
/// <c>RemoteLoadPath = ServerUrl + PlatformDir + RatingDir + VersionDirWithSeparator</c>
/// (实机:<c>https://.../resources/</c> + <c>windows</c> + <c>r18</c> + <c>aas/0.1.0/</c>),
/// catalog URL = <c>RemoteLoadPath + "/aa/catalog_1.bin"</c>。
/// 把这两个取值重写到本机假服务器,资源请求就会落到 <see cref="OfflineApiServer"/>。
/// </para>
/// <para>补丁按目标拆成独立小类:单个目标解析失败只影响自己,不会连坐其它补丁。</para>
/// </summary>
internal static class AssetDiag
{
    /// <summary>诊断日志总量上限(超出后只计数,避免刷爆日志)。</summary>
    internal const int MaxDiagLines = 300;

    private static readonly HashSet<string> Seen = new();
    private static readonly object SeenLock = new();
    private static int _suppressed;
    private static int _snapshots;
    private static int _shots;

    /// <summary>是否把资源服务器重定向到本地假服务器。</summary>
    internal static bool Redirect =>
        Plugin.OfflineApi.Value &&
        Plugin.RedirectAssetServer.Value &&
        Plugin.ApiServer != null &&
        Plugin.ApiServer.BaseUrl.Length > 0;

    /// <summary>
    /// 是否输出资产管线/启动链诊断日志。
    /// 只受 <see cref="Plugin.DiagAssets"/> 控制,不再依赖 <see cref="Plugin.OfflineApi"/>:
    /// 在线对照轮(把 OfflineApi 关掉或改成抓包转发)同样需要这些日志。
    /// </summary>
    internal static bool Diag => Plugin.DiagAssets.Value;

    /// <summary>去重诊断日志:同一 key 只记一次,总量封顶。</summary>
    internal static void LogOnce(string key, string message)
    {
        if (!Diag)
            return;
        lock (SeenLock)
        {
            if (Seen.Count >= MaxDiagLines)
            {
                _suppressed++;
                return;
            }
            if (!Seen.Add(key))
                return;
        }
        Plugin.Logger.LogInfo($"[资产] {message}");
    }

    /// <summary>
    /// 把 URL 的协议与主机换成"本机假服务器",路径与查询串原样保留。
    /// 例:<c>https://api.example.com/resources/windows/</c> → <c>http://127.0.0.1:18923/resources/windows/</c>。
    /// </summary>
    internal static string RewriteHost(string url)
    {
        if (string.IsNullOrEmpty(url) || Plugin.ApiServer == null)
            return url;
        string local = Plugin.ApiServer.BaseUrl;                       // http://127.0.0.1:<port>/
        if (url.StartsWith(local, StringComparison.OrdinalIgnoreCase))
            return url;
        int scheme = url.IndexOf("://", StringComparison.Ordinal);
        if (scheme < 0)
            return url;                                                // 相对路径/文件路径,原样返回
        int slash = url.IndexOf('/', scheme + 3);
        string tail = slash < 0 ? "" : url[slash..];                   // 含前导 '/'
        return local.TrimEnd('/') + tail;
    }

    /// <summary>
    /// 输出一次资产管线快照(ProfileDefine 关键值 + 引擎缓存状态 + RuntimeConfig 字符串项)。
    /// 由 <see cref="ViewerBehaviour"/> 定时调用,最多 8 次。
    /// </summary>
    internal static void Snapshot(string trigger)
    {
        if (!Diag)
            return;
        if (Interlocked.Increment(ref _snapshots) > 8)
            return;

        var sb = new StringBuilder(1024);
        sb.Append("[资产] 快照(").Append(trigger).Append(')');
        AppendValue(sb, "ServerUrl", () => AddressablesProfileDefine.ServerUrl);
        AppendValue(sb, "RemoteLoadPath", () => AddressablesProfileDefine.RemoteLoadPath);
        AppendValue(sb, "LocalLoadPath", () => AddressablesProfileDefine.LocalLoadPath);
        AppendValue(sb, "PlatformDir", () => AddressablesProfileDefine.PlatformDir);
        AppendValue(sb, "RatingDir", () => AddressablesProfileDefine.RatingDir);
        AppendValue(sb, "VersionDir", () => AddressablesProfileDefine.VersionDirWithSeparator);
        AppendValue(sb, "远程模式", () => AddressablesProfileDefine.IsConnectRemoteServerMode ? "true" : "false");
        AppendValue(sb, "_serverUrl", () => AddressablesProfileDefine._serverUrl);
        AppendValue(sb, "_versionDir", () => AddressablesProfileDefine._versionDir);
        AppendValue(sb, "持久化目录", () => UnityEngine.Application.persistentDataPath);
        AppendValue(sb, "引擎缓存数", () => UnityEngine.Caching.cacheCount.ToString());
        AppendValue(sb, "当前缓存目录", () => UnityEngine.Caching.currentCacheForWriting.path);
        AppendValue(sb, "帧数", () => UnityEngine.Time.frameCount.ToString());
        AppendValue(sb, "运行秒", () => ((int)UnityEngine.Time.realtimeSinceStartup).ToString());
        AppendValue(sb, "定位器数", CountLocators);
        AppendValue(sb, "ID转换器", () => UnityEngine.AddressableAssets.Addressables.InternalIdTransformFunc == null ? "null" : "已设置");
        AppendValue(sb, "网络发送", WebRequestSendDiagPatch.Summary);
        DumpRuntimeConfig(sb);
        Plugin.Logger.LogInfo(sb.ToString());

        if (_suppressed > 0)
            Plugin.Logger.LogInfo($"[资产] 诊断日志已达上限 {MaxDiagLines} 条,另有 {_suppressed} 条被省略");
    }

    /// <summary>
    /// 让游戏自己截一张图,存到 <c>BepInEx\plugins\StoryViewer\shots\</c>,用于"看到"卡住时的实际画面。
    /// <para>
    /// 首选 <c>ScreenCapture.CaptureScreenshotAsTexture</c> + <c>ImageConversion.EncodeToPNG</c>
    /// (2026-09-23 实机:<c>CaptureScreenshot(string)</c> 会抛 interop 的
    /// <c>ReadOnlySpan.GetPinnableReference</c> 缺失异常,所以这里先走纹理路径)。
    /// 纹理路径失败时再退回原 <c>CaptureScreenshot(string)</c>。
    /// </para>
    /// 最多截 <see cref="MaxShots"/> 张。
    /// </summary>
    internal static void CaptureScreen(string tag)
    {
        // 0.7.13:恢复 DiagAssets 门槛。截图 = 全屏读回 + PNG 编码 + 写盘(主线程重活),
        // 0.7.11 曾按窗口/定时自动触发,是滚动卡顿的来源;现在只有 DiagAssets 打开时才截。
        if (!Diag || Interlocked.Increment(ref _shots) > MaxShots)
            return;

        // Boot/Notice 阶段是 DMM SDK 初始化与登录窗口,截图(含 PNG 编码,主线程重活)避开这段时间,
        // 只在 Title 及之后截,既够用又不干扰启动流程。
        try
        {
            string scene = UnityEngine.SceneManagement.SceneManager.GetActiveScene().name;
            if (scene is "Boot" or "Notice" or "Splash")
                return;
        }
        catch
        {
            // 场景名取不到就照常截图。
        }

        string dir = Path.Combine(Paths.PluginPath, "StoryViewer", "shots");
        string file = Path.Combine(dir, $"{DateTime.Now:HHmmss}-{Sanitize(tag)}.png");
        try
        {
            Directory.CreateDirectory(dir);
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"[截图] 目录创建失败: {e.Message}");
            return;
        }

        // 路径一:纹理截图 → PNG 字节(绕开 CaptureScreenshot(string) 的 interop 缺陷)。
        try
        {
            var tex = UnityEngine.ScreenCapture.CaptureScreenshotAsTexture();
            if (tex != null)
            {
                byte[] png = UnityEngine.ImageConversion.EncodeToPNG(tex);
                UnityEngine.Object.Destroy(tex);
                if (png != null && png.Length > 0)
                {
                    File.WriteAllBytes(file, png);
                    Plugin.Logger.LogInfo($"[截图] 已保存: {Path.GetFileName(file)} ({png.Length} 字节)");
                    return;
                }
            }
            Plugin.Logger.LogWarning("[截图] 纹理截图返回空,改用引擎截图接口");
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"[截图] 纹理截图失败: {e.Message}");
        }

        // 路径二:引擎自带的写文件接口(此前实测抛异常,留作兜底)。
        try
        {
            UnityEngine.ScreenCapture.CaptureScreenshot(file);
            Plugin.Logger.LogInfo($"[截图] 已请求截图: {Path.GetFileName(file)}");
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"[截图] 截图失败: {e.Message}");
        }
    }

    /// <summary>截图总量上限(一次进程内最多截这么多张)。</summary>
    internal const int MaxShots = 12;

    /// <summary>文件名安全化(非字母数字替换为下划线)。</summary>
    private static string Sanitize(string tag)
    {
        var sb = new StringBuilder(tag.Length);
        foreach (char c in tag)
            sb.Append(char.IsLetterOrDigit(c) || c == '-' || c == '_' ? c : '_');
        return sb.ToString();
    }

    /// <summary>数一下 Addressables 已注册的资源定位器数量(0 说明 catalog 没注册成功)。</summary>
    private static string CountLocators()
    {
        var locators = UnityEngine.AddressableAssets.Addressables.ResourceLocators;
        if (locators == null)
            return "null";
        int count = 0;
        if (locators is System.Collections.IEnumerable plain)
        {
            foreach (var _ in plain)
            {
                if (++count >= 50)
                    break;
            }
            return count.ToString();
        }
        return "存在(不可枚举)";
    }

    /// <summary>往快照里追加一个取值(取值失败不影响其它项)。</summary>
    private static void AppendValue(StringBuilder sb, string name, Func<string> getter)
    {
        sb.Append(" | ").Append(name).Append('=');
        try
        {
            sb.Append(getter());
        }
        catch (Exception e)
        {
            sb.Append("取值失败(").Append(e.GetType().Name).Append(')');
        }
    }

    /// <summary>列出 Absf.RuntimeConfig 的字符串型静态属性(找资产版本等关键值)。</summary>
    private static void DumpRuntimeConfig(StringBuilder sb)
    {
        try
        {
            foreach (var p in typeof(Absf.RuntimeConfig).GetProperties(BindingFlags.Public | BindingFlags.Static))
            {
                if (p.PropertyType != typeof(string) || p.GetMethod == null || !p.GetMethod.IsStatic)
                    continue;
                sb.Append(" | RC.").Append(p.Name).Append('=');
                try
                {
                    sb.Append(p.GetValue(null));
                }
                catch
                {
                    sb.Append("ERR");
                }
                if (sb.Length > 2600)
                {
                    sb.Append(" | …(截断)");
                    break;
                }
            }
        }
        catch (Exception e)
        {
            sb.Append(" | RuntimeConfig 反射失败: ").Append(e.GetType().Name);
        }
    }
}

/// <summary>资源服务器根地址 → 本机假服务器(catalog 与 bundle URL 的公共前缀)。</summary>
[HarmonyPatch]
internal static class AssetServerUrlPatch
{
    /// <summary>记录并改写 ProfileDefine.ServerUrl。</summary>
    [HarmonyPatch(typeof(AddressablesProfileDefine), "get_ServerUrl")]
    [HarmonyPostfix]
    private static void Postfix(ref string __result)
    {
        AssetDiag.LogOnce($"ServerUrl:{__result}", $"ProfileDefine.ServerUrl = {__result}");
        if (AssetDiag.Redirect)
            __result = AssetDiag.RewriteHost(__result);
    }
}

/// <summary>远程资源路径(ServerUrl + 平台/分级/版本目录) → 本机假服务器。</summary>
[HarmonyPatch]
internal static class AssetRemoteLoadPathPatch
{
    /// <summary>记录并改写 ProfileDefine.RemoteLoadPath。</summary>
    [HarmonyPatch(typeof(AddressablesProfileDefine), "get_RemoteLoadPath")]
    [HarmonyPostfix]
    private static void Postfix(ref string __result)
    {
        AssetDiag.LogOnce($"RemoteLoadPath:{__result}", $"ProfileDefine.RemoteLoadPath = {__result}");
        if (AssetDiag.Redirect)
            __result = AssetDiag.RewriteHost(__result);
    }
}

/// <summary>RuntimeConfig 的资产 bundle 根地址 → 本机假服务器。</summary>
[HarmonyPatch]
internal static class AssetBundleUrlPatch
{
    /// <summary>记录并改写 RuntimeConfig.GetAssetBundleUrl。</summary>
    [HarmonyPatch(typeof(Absf.RuntimeConfig), "GetAssetBundleUrl")]
    [HarmonyPostfix]
    private static void Postfix(ref string __result)
    {
        AssetDiag.LogOnce($"GetAssetBundleUrl:{__result}", $"RuntimeConfig.GetAssetBundleUrl = {__result}");
        if (AssetDiag.Redirect)
            __result = AssetDiag.RewriteHost(__result);
    }
}

/// <summary>InternalId → URL 转换的入参/结果日志(确认 catalog 占位符的最终形态)。</summary>
[HarmonyPatch]
internal static class AssetTransformIdPatch
{
    /// <summary>记录入参。</summary>
    [HarmonyPatch(typeof(AddressablesProfileDefine), nameof(AddressablesProfileDefine.TransformInternalId),
        new[] { typeof(string) })]
    [HarmonyPrefix]
    private static void Prefix(string internalId) =>
        AssetDiag.LogOnce($"tid-in:{internalId}", $"TransformInternalId 入: {internalId}");

    /// <summary>记录结果。</summary>
    [HarmonyPatch(typeof(AddressablesProfileDefine), nameof(AddressablesProfileDefine.TransformInternalId),
        new[] { typeof(string) })]
    [HarmonyPostfix]
    private static void Postfix(string internalId, ref string __result) =>
        AssetDiag.LogOnce($"tid-out:{internalId}", $"TransformInternalId 出: {__result}");
}

/// <summary>带 IResourceLocation 的 InternalId 转换结果日志。</summary>
[HarmonyPatch]
internal static class AssetTransformLocationPatch
{
    /// <summary>记录转换结果。</summary>
    [HarmonyPatch(typeof(AddressablesProfileDefine), nameof(AddressablesProfileDefine.TransformInternalId),
        new[] { typeof(IResourceLocation) })]
    [HarmonyPostfix]
    private static void Postfix(IResourceLocation location, ref string __result) =>
        AssetDiag.LogOnce($"tid-loc:{location?.PrimaryKey}", $"TransformInternalId(loc {location?.PrimaryKey}) 出: {__result}");
}

/// <summary>资产初始化时传入的版本参数日志。</summary>
[HarmonyPatch]
internal static class AssetLoaderInitPatch
{
    /// <summary>记录 InitializeAsync 的版本入参。</summary>
    [HarmonyPatch(typeof(AddressablesAssetLoader), nameof(AddressablesAssetLoader.InitializeAsync))]
    [HarmonyPrefix]
    private static void Prefix(string manualAssetVersion, string manualCatalogVersion) =>
        AssetDiag.LogOnce($"init:{manualAssetVersion}:{manualCatalogVersion}",
            $"AddressablesAssetLoader.InitializeAsync(asset='{manualAssetVersion}', catalog='{manualCatalogVersion}')");
}

/// <summary>catalog 手工加载的版本参数日志。</summary>
[HarmonyPatch]
internal static class AssetLoadManualCatalogPatch
{
    /// <summary>记录 LoadManualCatalogAsync 的版本入参。</summary>
    [HarmonyPatch(typeof(AddressablesAssetLoader), nameof(AddressablesAssetLoader.LoadManualCatalogAsync))]
    [HarmonyPrefix]
    private static void Prefix(string manualAssetVersion, string manualCatalogVersion) =>
        AssetDiag.LogOnce($"cat:{manualAssetVersion}:{manualCatalogVersion}",
            $"AddressablesAssetLoader.LoadManualCatalogAsync(asset='{manualAssetVersion}', catalog='{manualCatalogVersion}')");
}
