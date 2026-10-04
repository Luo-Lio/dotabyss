using System;
using System.Reflection;
using UnityEngine.AddressableAssets;

namespace StoryViewer;

/// <summary>
/// 离线资源系统自举(2026-09-23,v0.7.0)。
/// <para>
/// 实机证据(22:15 轮):F7 剧情列表可用、主数据可用,但点播放后资源加载失败
/// (<c>アセットの読み込みに失敗しました</c>),而且<b>没有任何资源请求</b>发出 ——
/// 原因是游戏启动流程没走到 <c>InitializeAssetLoaderAsync</c>,Addressables 的
/// 内容 catalog 从未注册,任何按地址加载都必然失败。
/// </para>
/// <para>
/// 这里在离线档自己把这一步补上:确保 Addressables 初始化 → 用本机假服务器的
/// 地址加载内容 catalog(路径与游戏自身请求的完全一致)。catalog 注册后,
/// bundle 请求会被 <c>AssetOfflinePatch</c> 改写到本机服务器,由 Caches 目录供给。
/// </para>
/// <para>
/// 实现在 <see cref="Tick"/> 里分步推进(不用 async/await:IL2CPP interop 的程序集
/// 里 <c>UniTaskVoid</c> 缺少 AsyncMethodBuilder 特性,<c>async UniTaskVoid</c> 编译不过;
/// Addressables 的 handle 是泛型结构体,用 object 装箱 + 反射读取进度,避免写死类型名)。
/// </para>
/// 只在配置 BootstrapAssets=true(默认)时工作;失败可重试。
/// </summary>
internal static class AssetBootstrap
{
    /// <summary>内容 catalog 的相对路径(与游戏中实际请求的路径一致)。</summary>
    private const string CatalogPath = "/resources/windows/r18/aas/0.1.0/aa/catalog_1.bin";

    /// <summary>本机资源服务器的兜底根地址。</summary>
    private const string LocalAssetBase = "http://127.0.0.1:18923";

    /// <summary>状态:0=未开始 1=初始化 Addressables 中 2=加载 catalog 中 3=完成 4=失败。</summary>
    private static int _state;

    /// <summary>当前进行中的 Addressables 操作(装箱的 AsyncOperationHandle&lt;T&gt;)。</summary>
    private static object _op;

    private static bool _wanted;
    private static float _wantAt;
    private static float _stepAt;
    private static string _reason = "";
    private static string _initializationStatus = "(未开始)";

    /// <summary>自举是否已完成(供界面提示)。</summary>
    internal static bool Done => _state == 3;

    /// <summary>自举是否失败(供界面提示)。</summary>
    internal static bool Failed => _state == 4;

    /// <summary>
    /// 请求自举(幂等;失败后再次请求会重试)。
    /// 触发点:标题流程停在 OnEnteredImpl 时、打开剧情列表时、插件加载兜底计时。
    /// </summary>
    internal static void Want(string reason)
    {
        if (!Plugin.BootstrapAssets.Value || _state == 3)
            return;

        if (_wanted && _state != 4)
            return;

        _wanted = true;
        _state = 0;
        _op = null;
        _initializationStatus = "(未开始)";
        _wantAt = UnityEngine.Time.realtimeSinceStartup;
        _reason = reason;
        Plugin.Logger?.LogInfo($"[资源自举] 已排队(触发: {reason})");
    }

    /// <summary>每帧推进(由 ViewerBehaviour.Update 调用,主线程)。</summary>
    internal static void Tick()
    {
        if (!Plugin.BootstrapAssets.Value || _state == 3)
            return;

        // 兜底:插件加载 25 秒后自动排队,不依赖任何打点是否命中
        if (!_wanted && UnityEngine.Time.realtimeSinceStartup > 25f)
            Want("插件加载兜底计时");

        if (!_wanted)
            return;

        float now = UnityEngine.Time.realtimeSinceStartup;
        if (_state == 0)
        {
            if (now < _wantAt + 1f)
                return;
            _state = 1;
            _stepAt = now;
            Plugin.Logger?.LogInfo("[资源自举] 1/2 Addressables.InitializeAsync …");
            try
            {
                _op = Addressables.InitializeAsync();
            }
            catch (Exception e)
            {
                _state = 4;
                Plugin.Logger?.LogError($"[资源自举] Addressables.InitializeAsync 调用失败: {e}");
            }
            return;
        }

        if (_state == 1)
        {
            if (!IsDone(_op))
                return;
            _initializationStatus = StatusOf(_op);
            string initializationException = ExceptionOf(_op);
            if (!string.Equals(_initializationStatus, "Succeeded", StringComparison.OrdinalIgnoreCase))
            {
                // 离线包没有游戏在线启动流程生成的 settings.json；手工 catalog 是本插件的预期兜底，
                // 但不能把原生初始化失败继续记录为“完成”，否则排障时会误判资源状态。
                Plugin.Logger?.LogWarning(
                    $"[资源自举] Addressables.InitializeAsync 未成功(Status={_initializationStatus},异常={initializationException});" +
                    "离线模式继续尝试手工 catalog");
            }
            else
            {
                Plugin.Logger?.LogInfo($"[资源自举] 原生初始化完成(Status={_initializationStatus})");
            }

            string url = ResolveCatalogUrl();
            Plugin.Logger?.LogInfo($"[资源自举] 2/2 加载内容 catalog: {url}");
            _state = 2;
            _stepAt = now;
            try
            {
                _op = Addressables.LoadContentCatalogAsync(url);
            }
            catch (Exception e)
            {
                _state = 4;
                Plugin.Logger?.LogError($"[资源自举] LoadContentCatalogAsync 调用失败: {e}");
            }
            return;
        }

        if (_state == 2 && IsDone(_op))
        {
            string status = StatusOf(_op);
            if (status == "Succeeded")
            {
                _state = 3;
                Plugin.Logger?.LogInfo(
                    $"[资源自举] 完成:内容 catalog 已注册({_reason};原生初始化={_initializationStatus})");
            }
            else
            {
                // catalog 加载失败即置失败态(不做 file:// 回退:离线包没有本地 aa/ 目录,
                // 用 file:// 注册的 catalog 会把 bundle 解析成本地路径而绕过本机服务器,
                // 结果「进得去、开得了面板、但播放黑屏」。正解是让 http catalog 加载成功,
                // 服务器下发本地 .hash(0.7.21 回退了 0.7.20 的“一律 404”)。)
                _state = 4;
                Plugin.Logger?.LogError($"[资源自举] 失败:catalog 加载 Status={status},异常={ExceptionOf(_op)}");
            }
        }
    }

    /// <summary>读装箱 handle 的 IsDone(反射;读不到按未完成处理)。</summary>
    private static bool IsDone(object handle)
    {
        if (handle == null)
            return false;
        return ReadMember(handle, "IsDone") is bool done && done;
    }

    /// <summary>读装箱 handle 的 Status(反射)。</summary>
    private static string StatusOf(object handle) => ReadMember(handle, "Status")?.ToString() ?? "(未知)";

    /// <summary>读装箱 handle 的 OperationException(反射,失败时给原因)。</summary>
    private static string ExceptionOf(object handle) => ReadMember(handle, "OperationException")?.ToString() ?? "(无)";

    /// <summary>按属性/字段名读取装箱对象成员(读不到返回 null)。</summary>
    private static object ReadMember(object target, string name)
    {
        try
        {
            Type t = target.GetType();
            PropertyInfo prop = t.GetProperty(name, BindingFlags.Public | BindingFlags.Instance);
            if (prop != null)
                return prop.GetValue(target);
            FieldInfo field = t.GetField(name, BindingFlags.Public | BindingFlags.Instance);
            return field?.GetValue(target);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>内容 catalog 的本机地址(优先用假服务器实际监听的端口)。</summary>
    private static string ResolveCatalogUrl()
    {
        string baseUrl = Plugin.ApiServer?.BaseUrl;
        if (string.IsNullOrEmpty(baseUrl))
            baseUrl = LocalAssetBase;
        return baseUrl.TrimEnd('/') + CatalogPath;
    }

    /// <summary>界面上给用户的一句状态描述。</summary>
    internal static string StatusText()
    {
        return _state switch
        {
            1 or 2 => "资源系统自举中,请等几秒再播放",
            3 => "资源系统就绪,可以播放",
            4 => "资源系统自举失败,详见日志 [资源自举]",
            _ => "资源系统未自举(播放会失败)",
        };
    }
}
