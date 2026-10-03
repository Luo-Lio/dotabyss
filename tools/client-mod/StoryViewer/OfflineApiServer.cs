using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using BepInEx;
using UnityEngine;

namespace StoryViewer;

/// <summary>
/// 离线模式的本地假 API 服务器:把游戏的 API 根地址指到本机,接管全部接口请求。
/// <para>
/// 用途:没有 DMM 会话 / 无法联网时,让客户端还能走完启动流程。
/// 每个请求都会记录到 <c>BepInEx\offline-api.log</c>;响应优先取
/// <c>BepInEx\plugins\StoryViewer\offline_api\&lt;路径&gt;.json</c>,找不到时返回通用成功信封。
/// </para>
/// <para>
/// 除 API 外还接管<b>资源请求</b>(离线资源加载):
/// <list type="bullet">
/// <item>catalog(<c>.../aa/catalog_1.bin</c> 与 <c>.hash</c>)优先从插件目录下的
/// <c>catalog_seed</c> 种子取,缺失时从 <c>%USERPROFILE%\AppData\LocalLow\...\com.unity.addressables\</c>
/// 的游戏自带缓存里取;</item>
/// <item>bundle(<c>*.bundle</c>)按文件名里的内容哈希,从 <c>&lt;游戏&gt;\ドットアビスX_Data\Caches</c>
/// 的引擎缓存条目(<c>__data</c>)里取,命中即原样回传,未命中回 404。</item>
/// </list>
/// </para>
/// <para>
/// 用裸 <see cref="TcpListener"/> 而不是 HttpListener:后者在非管理员进程下需要
/// http.sys 的 URL ACL 预留,裸 socket 没有这个限制。
/// </para>
/// </summary>
internal sealed class OfflineApiServer : IDisposable
{
    /// <summary>单条请求日志里正文的最大记录长度(避免刷爆日志)。</summary>
    private const int MaxLoggedBody = 2000;

    private readonly int _port;
    private readonly TcpListener _listener;
    private readonly Thread _thread;
    private readonly string _cannedDir;
    private readonly string _catalogSeedDir;
    private readonly string _logPath;
    private readonly object _logLock = new();
    private volatile bool _running;
    private string _baseUrl = "";

    // ---- 资源供应(离线资源加载) ----
    private readonly object _assetLock = new();
    private byte[] _catalogBytes;
    private byte[] _catalogHashBytes;
    private bool _assetResolveFailed;
    private Dictionary<string, string> _bundleIndex;      // 内容哈希(小写) → __data 完整路径
    private Dictionary<string, string> _nameToHash;       // bundle 文件名(小写) → 内容哈希
    private int _bundleHits;
    private int _bundleMisses;
    private int _catalogHits;

    // ---- 抓包转发(在线对照:CaptureForward=true 时把请求原样转发到真实上游并记录) ----
    /// <summary>抓包文件里请求/响应正文的最大留存长度(超出只在文本里记长度)。</summary>
    private const int MaxCaptureBody = 8 * 1024 * 1024;

    /// <summary>转发用的 HTTP 客户端(单例;不自动解压、不跟随重定向,保持与游戏收到的一致)。</summary>
    private static readonly HttpClient Http = new(new HttpClientHandler { AllowAutoRedirect = false })
    {
        Timeout = TimeSpan.FromSeconds(20),
    };

    private int _captureSeq;
    private volatile bool _captureUpstreamWarned;

    /// <summary>抓包输出目录(BepInEx\capture)。</summary>
    private static string CaptureDir => Path.Combine(Paths.BepInExRootPath, "capture");

    /// <summary>创建服务器(不启动)。<paramref name="port"/> 为 0 时由系统分配空闲端口。</summary>
    internal OfflineApiServer(int port)
    {
        _port = port;
        _listener = new TcpListener(IPAddress.Loopback, port);
        _cannedDir = Path.Combine(Paths.PluginPath, "StoryViewer", "offline_api");
        _catalogSeedDir = Path.Combine(Paths.PluginPath, "StoryViewer", "catalog_seed");
        _logPath = Path.Combine(Paths.BepInExRootPath, "offline-api.log");
        _thread = new Thread(Loop)
        {
            IsBackground = true,
            Name = "StoryViewer.OfflineApi",
        };
    }

    /// <summary>服务器基地址(带结尾斜杠),作为游戏 API 根地址使用;未启动时为空串。</summary>
    internal string BaseUrl => _baseUrl;

    /// <summary>实际监听的端口(0 表示尚未启动)。</summary>
    internal int Port { get; private set; }

    /// <summary>启动监听线程。</summary>
    internal void Start()
    {
        try
        {
            _listener.Start();
            Port = ((IPEndPoint)_listener.LocalEndpoint).Port;
            _baseUrl = $"http://127.0.0.1:{Port}/";
        }
        catch (Exception e)
        {
            Plugin.Logger?.LogError($"离线 API 服务器启动失败(端口 {_port}): {e.Message}");
            return;
        }
        _running = true;
        _thread.Start();
        LogLine($"离线 API 服务器已启动: {_baseUrl}(预置响应目录: {_cannedDir})");
        if (Plugin.CaptureForward.Value)
        {
            string upstream = ResolveUpstream();
            LogLine(upstream.Length > 0
                ? $"抓包转发已启用:上游 = {upstream},抓包目录 = {CaptureDir}"
                : $"抓包转发已启用:上游待定(等 ApiRedirect 捕获原始 API 根地址;也可在配置里写 CaptureUpstream),抓包目录 = {CaptureDir}");
        }
    }

    /// <summary>停止监听并等待线程退出。</summary>
    public void Dispose()
    {
        _running = false;
        try
        {
            _listener.Stop();
        }
        catch
        {
            // 进程退出阶段,忽略关闭异常
        }
        if (_thread.IsAlive)
            _thread.Join(1000);
    }

    /// <summary>接受连接的循环(每条连接交给线程池处理,避免相互阻塞)。</summary>
    private void Loop()
    {
        while (_running)
        {
            try
            {
                var client = _listener.AcceptTcpClient();
                ThreadPool.QueueUserWorkItem(_ => Handle(client));
            }
            catch (Exception e)
            {
                if (_running)
                    LogLine($"接受连接异常: {e.Message}");
            }
        }
    }

    /// <summary>处理一条 HTTP 连接:记录请求、生成响应、写回。</summary>
    private void Handle(TcpClient client)
    {
        using (client)
        {
            try
            {
                client.ReceiveTimeout = 10000;
                client.SendTimeout = 10000;
                using var stream = client.GetStream();
                if (!TryReadRequest(stream, out var method, out var path, out var headers, out var body))
                    return;

                var bodyText = body.Length > 0 ? Encoding.UTF8.GetString(body) : "";
                string cleanPath = path.Split('?')[0].Trim('/');

                // 抓包转发优先:在线对照轮把请求原样送往真实上游,并把完整往返落盘
                if (TryForward(stream, method, path, headers, body, out var forwardNote))
                {
                    LogRequest(method, path, headers, bodyText, forwardNote);
                    return;
                }

                // 先尝试用本地缓存供应资源(catalog / bundle);命中或明确 404 都直接结束
                if (TryServeAsset(stream, cleanPath, out var assetNote))
                {
                    LogRequest(method, path, headers, bodyText, assetNote);
                    return;
                }

                if (LooksLikeBinaryDownload(cleanPath))
                {
                    // 资源下载请求直接拒绝:避免把 JSON 塞给二进制消费者、污染本地缓存
                    LogRequest(method, path, headers, bodyText, "疑似资源下载 → 404");
                    WriteResponse(stream, 404, "application/json",
                        "{\"status\":\"error\",\"errors\":{\"code\":404,\"message\":\"offline\"}}");
                    return;
                }

                var (json, source) = ResolveBody(cleanPath);
                LogRequest(method, path, headers, bodyText, source);
                WriteResponse(stream, 200, "application/json; charset=utf-8", json);
            }
            catch (Exception e)
            {
                LogLine($"处理请求异常: {e.Message}");
            }
        }
    }

    // ---------------------------------------------------------------- 资源供应(离线资源加载)

    /// <summary>
    /// 尝试用本地缓存应答资源请求:
    /// <c>catalog_1.bin</c> / <c>catalog_1.bin.hash</c>(来自游戏自带的 Addressables 缓存目录)、
    /// <c>*.bundle</c>(按文件名里的内容哈希,从引擎缓存 Caches 里取 <c>__data</c>)。
    /// </summary>
    /// <param name="stream">连接流,命中时直接写出响应。</param>
    /// <param name="cleanPath">去掉查询串与首尾斜杠的请求路径。</param>
    /// <param name="note">日志里显示的响应来源说明。</param>
    /// <returns>true 表示已处理(含明确的 404),false 表示交给后面的 API 逻辑。</returns>
    private bool TryServeAsset(NetworkStream stream, string cleanPath, out string note)
    {
        note = null;
        if (!Plugin.ServeCachedBundles.Value || cleanPath.Length == 0)
            return false;
        string lower = cleanPath.ToLowerInvariant();

        if (MatchesAny(lower, CatalogSuffixes))
        {
            var bytes = EnsureCatalogBytes();
            if (bytes == null)
            {
                note = "本地 catalog 缺失 → 404";
                WriteResponse(stream, 404, "text/plain; charset=utf-8", "no local catalog");
                return true;
            }
            int n = Interlocked.Increment(ref _catalogHits);
            WriteBytes(stream, 200, "application/octet-stream", bytes);
            note = $"本地 catalog {bytes.Length} 字节(第 {n} 次)";
            return true;
        }

        if (MatchesAny(lower, CatalogHashSuffixes))
        {
            // 0.7.19:不再供应 catalog .hash 文件。
            // 游戏 Addressables 初始化会用此哈希校验 catalog 正文;离线包种子与本体
            // 更新后 settings.json 期望值不一致时验证必定失败,导致黑屏。
            // 返回 404 让引擎跳过哈希校验、直接信任已下载的 catalog 内容。
            note = "catalog hash 已禁用(离线绕过) → 404";
            WriteResponse(stream, 404, "text/plain; charset=utf-8", "hash check disabled");
            return true;
        }

        // 不限于 *.bundle:流式音频(.awb/.acb)等资源在引擎缓存里同样按内容哈希存放,
        // 文件名只要以 32 位十六进制哈希结尾就走缓存查询。
        // (2026-09-23 实测:workunit_novel_bgm/bgm0033.awb_<hash> 因只认 .bundle 后缀而 404)
        string requestFileName = cleanPath[(cleanPath.LastIndexOf('/') + 1)..];
        if (lower.EndsWith(".bundle") || ExtractHash(requestFileName) != null)
        {
            string dataPath = ResolveBundle(cleanPath);
            if (dataPath == null)
            {
                int miss = Interlocked.Increment(ref _bundleMisses);
                note = $"缓存资源未命中 → 404(累计命中 {_bundleHits} / 缺失 {miss})";
                WriteResponse(stream, 404, "text/plain; charset=utf-8", "asset not cached");
                return true;
            }
            byte[] bytes;
            try
            {
                bytes = File.ReadAllBytes(dataPath);
            }
            catch (Exception e)
            {
                note = $"bundle 读取失败 → 404: {e.Message}";
                WriteResponse(stream, 404, "text/plain; charset=utf-8", "bundle read failed");
                return true;
            }
            int hit = Interlocked.Increment(ref _bundleHits);
            WriteBytes(stream, 200, "application/octet-stream", bytes);
            note = $"本地缓存 bundle {bytes.Length} 字节(累计命中 {hit} / 缺失 {_bundleMisses})";
            return true;
        }

        return false;
    }

    /// <summary>catalog 正文的请求后缀(catalog_1.bin 等)。</summary>
    private static readonly string[] CatalogSuffixes = { "catalog_1.bin", "catalog.bin" };

    /// <summary>catalog 哈希的请求后缀(Addressables 取的是 &lt;catalog 路径&gt;.hash)。</summary>
    private static readonly string[] CatalogHashSuffixes =
    {
        "catalog_1.bin.hash", "catalog_1.hash", "catalog.bin.hash", "catalog.hash",
    };

    /// <summary>路径是否以给定后缀之一结尾。</summary>
    private static bool MatchesAny(string lowerPath, string[] suffixes)
    {
        foreach (var s in suffixes)
            if (lowerPath.EndsWith(s, StringComparison.Ordinal))
                return true;
        return false;
    }

    /// <summary>读取游戏自带的 Addressables catalog 字节(默认取最近写入的一份)。</summary>
    private byte[] EnsureCatalogBytes()
    {
        lock (_assetLock)
        {
            if (_catalogBytes != null || _assetResolveFailed)
                return _catalogBytes;
            var (bin, hash) = ResolveCatalogFiles();
            if (bin == null)
            {
                _assetResolveFailed = true;
                LogLine("资源:未找到本地 catalog(com.unity.addressables 目录为空?)");
                return null;
            }
            _catalogBytes = File.ReadAllBytes(bin);
            _catalogHashBytes = hash != null && File.Exists(hash) ? File.ReadAllBytes(hash) : null;
            string source = bin.StartsWith(_catalogSeedDir, StringComparison.OrdinalIgnoreCase)
                ? "种子"
                : "LocalLow";
            LogLine($"资源:本地 catalog = {Path.GetFileName(bin)}({_catalogBytes.Length} 字节)," +
                    $"来源={source},hash = {(_catalogHashBytes != null ? _catalogHashBytes.Length + " 字节" : "缺失")}");
            return _catalogBytes;
        }
    }

    /// <summary>读取与 catalog 配对的 <c>.hash</c> 字节(缺失时返回 null)。</summary>
    private byte[] EnsureCatalogHashBytes()
    {
        EnsureCatalogBytes();
        lock (_assetLock)
        {
            return _catalogHashBytes;
        }
    }

    /// <summary>挑选 catalog 文件:配置指定时种子优先,否则取种子或缓存里最近修改的一份。</summary>
    private (string Bin, string Hash) ResolveCatalogFiles()
    {
        string localDir = Path.Combine(Application.persistentDataPath, "com.unity.addressables");
        string wanted = Plugin.CatalogFile.Value;
        if (!string.IsNullOrWhiteSpace(wanted))
        {
            string seedBin = Path.Combine(_catalogSeedDir, wanted.Trim());
            if (File.Exists(seedBin))
                return (seedBin, FindHashFile(seedBin));

            string localBin = Path.Combine(localDir, wanted.Trim());
            return File.Exists(localBin) ? (localBin, FindHashFile(localBin)) : (null, null);
        }

        string best = FindNewestCatalog(_catalogSeedDir);
        if (best == null)
            best = FindNewestCatalog(localDir);
        return best == null ? (null, null) : (best, FindHashFile(best));
    }

    /// <summary>返回目录中最近修改的 <c>*.bin</c> 文件;目录不存在或为空时返回 null。</summary>
    private static string FindNewestCatalog(string dir)
    {
        if (!Directory.Exists(dir))
            return null;

        string best = null;
        DateTime bestTime = DateTime.MinValue;
        foreach (var f in Directory.GetFiles(dir, "*.bin"))
        {
            var t = File.GetLastWriteTimeUtc(f);
            if (t > bestTime)
            {
                bestTime = t;
                best = f;
            }
        }
        return best;
    }

    /// <summary>
    /// 找 catalog 配对的哈希文件:游戏缓存里是 <c>&lt;名字&gt;.hash</c>(去掉 .bin),
    /// 但 Addressables 请求的是 <c>&lt;catalog 路径&gt;.hash</c>,两种命名都认。
    /// </summary>
    private static string FindHashFile(string binPath)
    {
        string withBin = binPath + ".hash";
        if (File.Exists(withBin))
            return withBin;
        string withoutBin = Path.ChangeExtension(binPath, ".hash");
        return File.Exists(withoutBin) ? withoutBin : null;
    }

    /// <summary>把请求里的 bundle 解析成引擎缓存里的 __data 文件。</summary>
    private string ResolveBundle(string cleanPath)
    {
        var index = EnsureBundleIndex();
        if (index == null || index.Count == 0)
            return null;
        string fileName = cleanPath[(cleanPath.LastIndexOf('/') + 1)..];
        string hash = ExtractHash(fileName);
        if (hash == null)
        {
            var map = EnsureNameToHash();
            if (map != null && map.TryGetValue(fileName, out var mapped))
                hash = mapped;
        }
        return hash != null && index.TryGetValue(hash, out var path) ? path : null;
    }

    /// <summary>从 bundle 文件名里取最后一段 32 位十六进制(内容哈希);取不到返回 null。</summary>
    private static string ExtractHash(string fileName)
    {
        string stem = fileName.EndsWith(".bundle", StringComparison.OrdinalIgnoreCase)
            ? fileName[..^".bundle".Length]
            : fileName;
        int at = stem.LastIndexOf('_');
        if (at < 0 || stem.Length - at - 1 != 32)
            return null;
        string candidate = stem[(at + 1)..];
        foreach (var c in candidate)
            if (!Uri.IsHexDigit(c))
                return null;
        return candidate;
    }

    /// <summary>
    /// 建立「引擎缓存内容哈希 → 载荷文件路径」索引(只建一次)。
    /// 缓存结构:&lt;Caches&gt;\&lt;一级&gt;\&lt;内容哈希&gt;\,载荷有两种布局:
    /// <c>__data</c>(普通 bundle)与「原始文件名」(如 <c>xxx.awb_&lt;hash&gt;</c> + <c>__info</c>,流式音频)。
    /// </summary>
    private Dictionary<string, string> EnsureBundleIndex()
    {
        lock (_assetLock)
        {
            if (_bundleIndex != null)
                return _bundleIndex;
            string root = Path.Combine(Application.dataPath, "Caches");
            if (!Directory.Exists(root))
            {
                LogLine($"资源:引擎缓存目录不存在: {root}");
                _bundleIndex = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                return _bundleIndex;
            }
            var index = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            int entries = 0, named = 0, skipped = 0;
            foreach (var level1 in Directory.GetDirectories(root))
            {
                foreach (var level2 in Directory.GetDirectories(level1))
                {
                    string hash = Path.GetFileName(level2);   // 二级目录名 = 内容哈希
                    string data = Path.Combine(level2, "__data");
                    if (File.Exists(data))
                    {
                        index[hash] = data;
                        entries++;
                        continue;
                    }
                    // 另一种布局:目录里放的是原始文件名(如 bgm0033.awb_<hash>) + __info,常见于流式音频。
                    string payload = FindPayloadFile(level2);
                    if (payload == null)
                    {
                        skipped++;
                        continue;
                    }
                    index[hash] = payload;
                    entries++;
                    named++;
                }
            }
            _bundleIndex = index;
            LogLine($"资源:引擎缓存索引建立完成:{entries} 个条目" +
                $"(其中原始文件名布局 {named} 个,跳过 {skipped} 个无载荷目录)");
            return index;
        }
    }

    /// <summary>
    /// 在缓存条目目录里找唯一的载荷文件(排除 <c>__data</c>/<c>__info</c> 这类下划线元数据文件)。
    /// 出现多个候选说明不是预期的单文件布局,返回 null 以免送错内容。
    /// </summary>
    private static string FindPayloadFile(string dir)
    {
        string found = null;
        foreach (var file in Directory.GetFiles(dir))
        {
            string name = Path.GetFileName(file);
            if (name.StartsWith("__", StringComparison.Ordinal))
                continue;
            if (found != null)
                return null;
            found = file;
        }
        return found;
    }

    /// <summary>从 catalog 文本里建立「bundle 文件名 → 内容哈希」映射(URL 不带哈希时使用)。</summary>
    private Dictionary<string, string> EnsureNameToHash()
    {
        lock (_assetLock)
        {
            if (_nameToHash != null)
                return _nameToHash;
            var bytes = EnsureCatalogBytes();
            if (bytes == null)
                return null;
            string text = Encoding.Latin1.GetString(bytes);
            var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (Match m in Regex.Matches(text, @"([A-Za-z0-9_\.\-]{3,120}?)_([0-9a-f]{32})\.bundle"))
            {
                map[m.Groups[1].Value + ".bundle"] = m.Groups[2].Value;   // 去哈希名 → 哈希
                map[m.Value] = m.Groups[2].Value;                         // 带哈希名 → 哈希
            }
            _nameToHash = map;
            LogLine($"资源:catalog 名字映射建立完成:{map.Count} 项");
            return map;
        }
    }

    /// <summary>写回一个二进制 HTTP 响应并关闭连接。</summary>
    private static void WriteBytes(NetworkStream stream, int status, string contentType, byte[] payload)
    {
        string head = $"HTTP/1.1 {status} {(status == 200 ? "OK" : "Not Found")}\r\n" +
                      $"Content-Type: {contentType}\r\n" +
                      $"Content-Length: {payload.Length}\r\n" +
                      "Connection: close\r\n\r\n";
        var headBytes = Encoding.ASCII.GetBytes(head);
        stream.Write(headBytes, 0, headBytes.Length);
        stream.Write(payload, 0, payload.Length);
        stream.Flush();
    }

    /// <summary>选择响应正文:先找预置文件,再生成完整成功信封。</summary>
    private (string Json, string Source) ResolveBody(string cleanPath)
    {
        foreach (var name in CandidateNames(cleanPath))
        {
            var file = Path.Combine(_cannedDir, name);
            if (File.Exists(file))
                return (File.ReadAllText(file, Encoding.UTF8), $"预置响应 {name}");
        }
        return (BuildEnvelope(cleanPath), "成功信封");
    }

    /// <summary>version 字段里所有需要填的版本数组(来自 interop 的 VersionEntity 成员)。</summary>
    private static readonly string[] ClientVersionFields =
    {
        "ClientVersionWebDmmGeneral", "ClientVersionWebDmmR18",
        "ClientVersionAndroidDmmGeneral", "ClientVersionAndroidDmmR18",
        "ClientVersionAndroidGooglePlayGeneral",
        "ClientVersionStandaloneDmmGeneral", "ClientVersionStandaloneDmmR18",
        "ClientVersionIosDmmGeneral", "ClientVersionIosDmmR18", "ClientVersionIosAppStoreGeneral",
    };

    /// <summary>资源版本数组字段。</summary>
    private static readonly string[] AssetVersionFields =
    {
        "AssetVersionWebDmmGeneral", "AssetVersionWebDmmR18",
        "AssetVersionAndroidDmmGeneral", "AssetVersionAndroidDmmR18",
        "AssetVersionAndroidGooglePlayGeneral",
        "AssetVersionStandaloneDmmGeneral", "AssetVersionStandaloneDmmR18",
        "AssetVersionIosDmmGeneral", "AssetVersionIosDmmR18", "AssetVersionIosAppStoreGeneral",
    };

    /// <summary>
    /// 构造完整响应信封:
    /// <c>status / server_time / timestamp / errors / api_token / versions / contents</c>。
    /// <para>
    /// 字段依据 interop 的 <c>ApiResponseEntity&lt;T&gt;</c>(contents / versions / server_time / api_token);
    /// versions 的所有数组都填游戏自身的版本号,避免客户端对 null 数组做 <c>Contains</c> 崩溃
    /// (2026-09-23 实机 <c>ApiManager.CheckValidVersion</c> 的 ArgumentNullException)。
    /// </para>
    /// </summary>
    private static string BuildEnvelope(string cleanPath)
    {
        string app = SafeConfig(() => Absf.RuntimeConfig.GetAppVersionCode(), "1.0.0");
        string bundle = SafeConfig(() => Absf.RuntimeConfig.GetBundleVersion(), "1");
        var sb = new StringBuilder(4096);
        sb.Append('{')
          .Append("\"status\":\"success\",")
          .Append("\"server_time\":\"").Append(DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss")).Append("\",")
          .Append("\"timestamp\":").Append(DateTimeOffset.UtcNow.ToUnixTimeSeconds()).Append(',')
          .Append("\"errors\":{\"code\":0,\"message\":\"\",\"severity\":\"\",\"app_transition\":\"\"},")
          .Append("\"api_token\":\"offline\",")
          .Append("\"versions\":");
        AppendVersions(sb, app, bundle);
        sb.Append(",\"contents\":").Append(ContentsFor(cleanPath));
        sb.Append('}');
        return sb.ToString();
    }

    /// <summary>按接口路径给出 contents 内容;未识别的接口返回空对象。</summary>
    private static string ContentsFor(string cleanPath)
    {
        if (cleanPath.Contains("maintenance", StringComparison.OrdinalIgnoreCase))
            return "{\"maintenance_type\":0,\"is_debug_user\":false,\"configs\":[],\"message\":{\"title\":\"\",\"body\":\"\"}}";
        return "{}";
    }

    /// <summary>写出版本信息对象(server/resource/各平台客户端与资源版本,全部为单元素数组)。</summary>
    private static void AppendVersions(StringBuilder sb, string app, string bundle)
    {
        sb.Append('{');
        bool first = true;
        AppendStringArray(sb, "server", app, ref first);
        AppendStringArray(sb, "resource", bundle, ref first);
        foreach (var field in ClientVersionFields)
            AppendStringArray(sb, field, app, ref first);
        foreach (var field in AssetVersionFields)
            AppendStringArray(sb, field, bundle, ref first);
        AppendStringArray(sb, "SubscriptionNoteAppStore", bundle, ref first);
        AppendStringArray(sb, "SubscriptionNoteGamePlayer", bundle, ref first);
        AppendStringArray(sb, "SubscriptionNoteGooglePlay", bundle, ref first);
        sb.Append('}');
    }

    /// <summary>写一个 JSON 字符串数组字段。</summary>
    private static void AppendStringArray(StringBuilder sb, string name, string value, ref bool first)
    {
        if (!first)
            sb.Append(',');
        first = false;
        sb.Append('"').Append(name).Append("\":[\"").Append(Escape(value)).Append("\"]");
    }

    /// <summary>转义 JSON 字符串中的反斜杠与引号。</summary>
    private static string Escape(string s) => s.Replace("\\", "\\\\").Replace("\"", "\\\"");

    /// <summary>安全读取游戏运行时配置(失败时返回兜底值)。</summary>
    private static string SafeConfig(Func<string> getter, string fallback)
    {
        try
        {
            var value = getter();
            return string.IsNullOrEmpty(value) ? fallback : value;
        }
        catch
        {
            return fallback;
        }
    }

    /// <summary>按「整路径」与「最后一段」两种命名依次尝试预置响应文件。</summary>
    private static IEnumerable<string> CandidateNames(string cleanPath)
    {
        if (cleanPath.Length == 0)
            yield break;
        yield return cleanPath.Replace('/', '_') + ".json";
        var segments = cleanPath.Split('/');
        yield return segments[^1] + ".json";
    }

    /// <summary>粗略识别资源/主数据下载请求(这些不该由假 API 接管)。</summary>
    private static bool LooksLikeBinaryDownload(string cleanPath)
    {
        string p = cleanPath.ToLowerInvariant();
        if (p.EndsWith(".dat") || p.EndsWith(".bin") || p.EndsWith(".zip") ||
            p.EndsWith(".unity3d") || p.EndsWith(".mpk") || p.EndsWith(".bundle"))
            return true;
        return p.Contains("master") || p.Contains("assetbundle") || p.Contains("bundle") ||
               p.Contains("download") || p.Contains("cri");
    }

    /// <summary>写回一个最小 HTTP/1.1 响应并关闭连接。</summary>
    private static void WriteResponse(NetworkStream stream, int status, string contentType, string body)
    {
        var payload = Encoding.UTF8.GetBytes(body);
        string head = $"HTTP/1.1 {status} {(status == 200 ? "OK" : "Not Found")}\r\n" +
                      $"Content-Type: {contentType}\r\n" +
                      $"Content-Length: {payload.Length}\r\n" +
                      "Connection: close\r\n\r\n";
        var headBytes = Encoding.ASCII.GetBytes(head);
        stream.Write(headBytes, 0, headBytes.Length);
        stream.Write(payload, 0, payload.Length);
        stream.Flush();
    }

    /// <summary>读取一个 HTTP 请求(请求行 + 头 + 按 Content-Length 读取的正文)。</summary>
    private static bool TryReadRequest(NetworkStream stream, out string method, out string path,
        out Dictionary<string, string> headers, out byte[] body)
    {
        method = null;
        path = null;
        headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        body = Array.Empty<byte>();

        var buffer = new MemoryStream();
        var chunk = new byte[4096];
        int headerEnd = -1;
        while (headerEnd < 0)
        {
            int read = stream.Read(chunk, 0, chunk.Length);
            if (read <= 0)
                return false;
            buffer.Write(chunk, 0, read);
            headerEnd = FindHeaderEnd(buffer.GetBuffer(), (int)buffer.Length);
            if (headerEnd < 0 && buffer.Length > 256 * 1024)
                return false;   // 头部异常,放弃这条连接
        }

        var raw = buffer.GetBuffer();
        var headerText = Encoding.ASCII.GetString(raw, 0, headerEnd);
        var lines = headerText.Split("\r\n", StringSplitOptions.RemoveEmptyEntries);
        if (lines.Length == 0)
            return false;
        var first = lines[0].Split(' ');
        if (first.Length < 2)
            return false;
        method = first[0];
        path = first[1];
        for (int i = 1; i < lines.Length; i++)
        {
            int colon = lines[i].IndexOf(':');
            if (colon > 0)
                headers[lines[i][..colon].Trim()] = lines[i][(colon + 1)..].Trim();
        }

        int contentLength = headers.TryGetValue("Content-Length", out var cl) && int.TryParse(cl, out var n) ? n : 0;
        int bodyStart = headerEnd + 4;
        var bodyStream = new MemoryStream();
        int already = Math.Min(contentLength, (int)buffer.Length - bodyStart);
        if (already > 0)
            bodyStream.Write(raw, bodyStart, already);
        while (bodyStream.Length < contentLength)
        {
            int want = Math.Min(chunk.Length, contentLength - (int)bodyStream.Length);
            int read = stream.Read(chunk, 0, want);
            if (read <= 0)
                break;
            bodyStream.Write(chunk, 0, read);
        }
        body = bodyStream.ToArray();
        return true;
    }

    /// <summary>在字节缓冲区中查找请求头结束位置(\r\n\r\n),返回首字节下标。</summary>
    private static int FindHeaderEnd(byte[] data, int length)
    {
        for (int i = 3; i < length; i++)
        {
            if (data[i - 3] == '\r' && data[i - 2] == '\n' && data[i - 1] == '\r' && data[i] == '\n')
                return i - 3;
        }
        return -1;
    }

    // ---------------------------------------------------------------- 抓包转发(在线对照)

    /// <summary>
    /// 把请求原样转发到真实上游(先看 <see cref="Plugin.CaptureUpstream"/>,留空则用
    /// 捕获到的游戏原始 API 根地址),把完整请求/响应写入 <c>BepInEx\capture</c>,
    /// 并把上游响应原样回给游戏。
    /// </summary>
    /// <returns>true 表示已转发并写好响应;false 表示未启用/上游未知/转发失败(交给本地预置响应)。</returns>
    private bool TryForward(NetworkStream stream, string method, string path,
        Dictionary<string, string> headers, byte[] body, out string note)
    {
        note = null;
        if (!Plugin.CaptureForward.Value)
            return false;

        string upstream = ResolveUpstream();
        if (upstream.Length == 0)
        {
            if (!_captureUpstreamWarned)
            {
                _captureUpstreamWarned = true;
                LogLine("抓包:上游地址未知(未捕获到原始 API 根地址且未配置 CaptureUpstream)→ 继续用本地预置响应");
            }
            return false;
        }

        string url = upstream + (path.StartsWith("/", StringComparison.Ordinal) ? path : "/" + path);
        int seq = Interlocked.Increment(ref _captureSeq);
        string baseName = $"{seq:D4}-{Sanitize(method)}-{Sanitize(Path.GetFileName(path.Split('?')[0]))}";
        try
        {
            using var req = new HttpRequestMessage(new HttpMethod(method), url);
            if (body.Length > 0)
                req.Content = new ByteArrayContent(body);
            foreach (var kv in headers)
            {
                if (IsHopByHop(kv.Key))
                    continue;
                if (req.Headers.TryAddWithoutValidation(kv.Key, kv.Value))
                    continue;
                req.Content?.Headers.TryAddWithoutValidation(kv.Key, kv.Value);
            }

            using var resp = Http.Send(req, HttpCompletionOption.ResponseHeadersRead);
            byte[] respBytes = resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult();
            WriteCaptureFiles(baseName, method, url, headers, body, resp, respBytes);
            WriteForwardedResponse(stream, resp, respBytes);
            note = $"转发上游 {resp.StatusCode} ({respBytes.Length} 字节) | 抓包 {baseName}";
            return true;
        }
        catch (Exception e)
        {
            LogLine($"抓包:转发失败 {method} {path} → {url}: {e.GetType().Name}: {e.Message}(退回本地预置响应)");
            return false;
        }
    }

    /// <summary>解析转发上游基地址(配置优先,否则用游戏原始 API 根地址)。</summary>
    private static string ResolveUpstream()
    {
        string configured = Plugin.CaptureUpstream.Value;
        if (!string.IsNullOrWhiteSpace(configured))
            return configured.TrimEnd('/');
        return string.IsNullOrWhiteSpace(Plugin.OriginalApiBase)
            ? ""
            : Plugin.OriginalApiBase.TrimEnd('/');
    }

    /// <summary>把一次完整往返写入 <c>BepInEx\capture\&lt;序号&gt;-&lt;方法&gt;-&lt;路径&gt;.txt</c>
    /// (二进制正文另存同名 <c>.req.bin</c> / <c>.resp.bin</c>)。</summary>
    private void WriteCaptureFiles(string baseName, string method, string url,
        Dictionary<string, string> headers, byte[] requestBody,
        HttpResponseMessage resp, byte[] responseBody)
    {
        try
        {
            Directory.CreateDirectory(CaptureDir);
            var sb = new StringBuilder(4096);
            sb.Append("时间: ").Append(DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff")).Append('\n');
            sb.Append("请求: ").Append(method).Append(' ').Append(url).Append('\n');
            sb.Append("— 请求头 —\n");
            foreach (var kv in headers)
                sb.Append(kv.Key).Append(": ").Append(kv.Value).Append('\n');
            sb.Append("— 请求体(").Append(requestBody.Length).Append(" 字节)—\n");
            sb.Append(BodyForLog(requestBody)).Append('\n');
            sb.Append("响应: ").Append((int)resp.StatusCode).Append(' ').Append(resp.ReasonPhrase).Append('\n');
            sb.Append("— 响应头 —\n");
            foreach (var h in resp.Headers)
                sb.Append(h.Key).Append(": ").Append(string.Join(", ", h.Value)).Append('\n');
            foreach (var h in resp.Content.Headers)
                sb.Append(h.Key).Append(": ").Append(string.Join(", ", h.Value)).Append('\n');
            sb.Append("— 响应体(").Append(responseBody.Length).Append(" 字节)—\n");
            sb.Append(BodyForLog(responseBody)).Append('\n');
            File.WriteAllText(Path.Combine(CaptureDir, baseName + ".txt"), sb.ToString(), Encoding.UTF8);

            if (requestBody.Length > 0 && requestBody.Length <= MaxCaptureBody && !IsProbablyText(requestBody))
                File.WriteAllBytes(Path.Combine(CaptureDir, baseName + ".req.bin"), requestBody);
            if (responseBody.Length > 0 && responseBody.Length <= MaxCaptureBody && !IsProbablyText(responseBody))
                File.WriteAllBytes(Path.Combine(CaptureDir, baseName + ".resp.bin"), responseBody);
        }
        catch (Exception e)
        {
            LogLine($"抓包:写入文件失败: {e.Message}");
        }
    }

    /// <summary>正文的日志表示:文本直接给,二进制给十六进制摘要(正文本身另存 .bin)。</summary>
    private static string BodyForLog(byte[] data)
    {
        if (data.Length == 0)
            return "(空)";
        if (IsProbablyText(data))
            return data.Length > 64 * 1024
                ? Encoding.UTF8.GetString(data, 0, 64 * 1024) + "\n…(截断,共 " + data.Length + " 字节)"
                : Encoding.UTF8.GetString(data);
        int n = Math.Min(data.Length, 64);
        var hex = new StringBuilder(n * 3);
        for (int i = 0; i < n; i++)
            hex.Append(data[i].ToString("x2")).Append(' ');
        return $"(二进制) {hex}… 共 {data.Length} 字节";
    }

    /// <summary>粗略判断是否文本(无 NUL、控制字符占比很低)。</summary>
    private static bool IsProbablyText(byte[] data)
    {
        int limit = Math.Min(data.Length, 8192);
        int bad = 0;
        for (int i = 0; i < limit; i++)
        {
            byte b = data[i];
            if (b == 0)
                return false;
            if (b < 0x09 || (b > 0x0d && b < 0x20))
                bad++;
        }
        return limit == 0 || bad * 20 <= limit;
    }

    /// <summary>把上游响应原样回给游戏(状态码 + 头 + 正文;跳过头由本层决定)。</summary>
    private static void WriteForwardedResponse(NetworkStream stream, HttpResponseMessage resp, byte[] payload)
    {
        var sb = new StringBuilder(1024);
        sb.Append("HTTP/1.1 ").Append((int)resp.StatusCode).Append(' ')
          .Append(string.IsNullOrEmpty(resp.ReasonPhrase) ? "OK" : resp.ReasonPhrase).Append("\r\n");
        foreach (var h in resp.Headers)
        {
            if (IsHopByHop(h.Key) || h.Key.Equals("Content-Length", StringComparison.OrdinalIgnoreCase))
                continue;
            sb.Append(h.Key).Append(": ").Append(string.Join(", ", h.Value)).Append("\r\n");
        }
        foreach (var h in resp.Content.Headers)
        {
            if (h.Key.Equals("Content-Length", StringComparison.OrdinalIgnoreCase) ||
                h.Key.Equals("Transfer-Encoding", StringComparison.OrdinalIgnoreCase))
                continue;
            sb.Append(h.Key).Append(": ").Append(string.Join(", ", h.Value)).Append("\r\n");
        }
        sb.Append("Content-Length: ").Append(payload.Length).Append("\r\n");
        sb.Append("Connection: close\r\n\r\n");
        var headBytes = Encoding.ASCII.GetBytes(sb.ToString());
        stream.Write(headBytes, 0, headBytes.Length);
        stream.Write(payload, 0, payload.Length);
        stream.Flush();
    }

    /// <summary>HTTP 逐跳头(转发/回写时都要去掉,由本层重新决定)。</summary>
    private static bool IsHopByHop(string name) =>
        name.Equals("Host", StringComparison.OrdinalIgnoreCase) ||
        name.Equals("Connection", StringComparison.OrdinalIgnoreCase) ||
        name.Equals("Keep-Alive", StringComparison.OrdinalIgnoreCase) ||
        name.Equals("Transfer-Encoding", StringComparison.OrdinalIgnoreCase) ||
        name.Equals("TE", StringComparison.OrdinalIgnoreCase) ||
        name.Equals("Upgrade", StringComparison.OrdinalIgnoreCase) ||
        name.Equals("Proxy-Connection", StringComparison.OrdinalIgnoreCase) ||
        name.Equals("Proxy-Authenticate", StringComparison.OrdinalIgnoreCase) ||
        name.Equals("Proxy-Authorization", StringComparison.OrdinalIgnoreCase) ||
        name.Equals("Content-Length", StringComparison.OrdinalIgnoreCase);

    /// <summary>把方法/路径片段整理成可用作文件名的短串。</summary>
    private static string Sanitize(string text)
    {
        if (string.IsNullOrEmpty(text))
            return "x";
        var sb = new StringBuilder(Math.Min(text.Length, 40));
        foreach (char c in text)
        {
            if (sb.Length >= 40)
                break;
            sb.Append(char.IsLetterOrDigit(c) || c == '_' || c == '-' || c == '.' ? c : '_');
        }
        return sb.Length == 0 ? "x" : sb.ToString();
    }

    /// <summary>记录一条请求(路径、关键头、正文摘要、响应来源)到日志文件。</summary>
    private void LogRequest(string method, string path, Dictionary<string, string> headers,
        string bodyText, string source)
    {
        var sb = new StringBuilder();
        sb.Append('[').Append(DateTime.Now.ToString("HH:mm:ss.fff")).Append("] ")
          .Append(method).Append(' ').Append(path).Append(" → ").Append(source);
        foreach (var key in new[] { "X-Content-Type", "Content-Type", "X-Api-Token", "X-Session", "Accept" })
        {
            if (headers.TryGetValue(key, out var v) && !string.IsNullOrEmpty(v))
                sb.Append(" | ").Append(key).Append('=').Append(v.Length > 60 ? v[..60] + "…" : v);
        }
        if (bodyText.Length > 0)
        {
            string shortBody = bodyText.Length > MaxLoggedBody ? bodyText[..MaxLoggedBody] + "…" : bodyText;
            sb.Append("\n    正文: ").Append(shortBody.Replace("\n", " ").Replace("\r", ""));
        }
        LogLine(sb.ToString());
    }

    /// <summary>向日志文件追加一行(带锁,后台线程安全)。</summary>
    private void LogLine(string line)
    {
        Plugin.Logger?.LogInfo($"[离线API] {line}");
        try
        {
            lock (_logLock)
            {
                File.AppendAllText(_logPath, line + Environment.NewLine, Encoding.UTF8);
            }
        }
        catch
        {
            // 日志失败不影响请求处理
        }
    }
}
