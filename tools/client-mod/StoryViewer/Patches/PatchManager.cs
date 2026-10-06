using System;
using System.Reflection;
using HarmonyLib;
using Project.Novel;

namespace StoryViewer.Patches;

/// <summary>集中安装 Harmony 补丁(逐类安装,单个补丁失败不影响其它补丁)。</summary>
internal static class PatchManager
{
    /// <summary>
    /// 安装本程序集内全部带 [HarmonyPatch] 的类。
    /// <para>
    /// 支持「按配置开关安装」:补丁类若声明 <c>public static bool Enabled</c>,
    /// 取值 false 时整个类不安装(用于把有崩溃风险的目标补丁彻底挡在门外,
    /// 而不是装上去再靠前缀判断——被补丁方法本身可能一被调用就出问题)。
    /// </para>
    /// </summary>
    internal static void Install()
    {
        var harmony = new Harmony(Plugin.Guid);
        int ok = 0, skipped = 0;
        foreach (var type in typeof(PatchManager).Assembly.GetTypes())
        {
            if (type.GetCustomAttribute<HarmonyPatch>() == null)
                continue;

            if (!IsEnabledByConfig(type))
            {
                skipped++;
                continue;
            }

            try
            {
                harmony.CreateClassProcessor(type).Patch();
                ok++;
            }
            catch (Exception e)
            {
                Plugin.Logger.LogError($"补丁 {type.Name} 安装失败: {e.Message}");
            }
        }
        // 「跳过」现在有两种来源:按配置关闭、或目标重载在当前 interop 里不存在
        // (后者见 NullByteGuardResolver:不存在的重载必须跳过而不是走进安装失败分支)。
        Plugin.Logger.LogInfo($"Harmony 补丁安装完成: {ok} 个" +
            (skipped > 0 ? $"(按配置或目标缺失跳过 {skipped} 个)" : ""));
        // 放在安装报告处,便于一眼看出兜底覆盖情况。
        NullByteGuardResolver.LogSummary();
    }

    /// <summary>
    /// 读取补丁类的静态 Enabled 属性(没有该属性视为启用)。
    /// 属性读取失败按启用处理并记录警告,避免静默少装补丁。
    /// </summary>
    private static bool IsEnabledByConfig(Type type)
    {
        var prop = type.GetProperty("Enabled",
            BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        if (prop == null)
            return true;
        try
        {
            return prop.GetValue(null) is not bool enabled || enabled;
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"补丁 {type.Name} 的 Enabled 读取失败,按启用处理: {e.Message}");
            return true;
        }
    }
}

/// <summary>
/// 剧情列表打开时阻断 Novel 场景的点击推进,避免鼠标事件穿透到剧情界面。
/// NovelViewClick.OnViewUpdate 是游戏的剧情输入热路径,这里只做最轻的前缀拦截。
/// </summary>
[HarmonyPatch(typeof(NovelViewClick), nameof(NovelViewClick.OnViewUpdate))]
internal static class NovelInputPatch
{
    /// <summary>返回 false 时跳过原方法,即窗口打开期间不处理剧情点击。</summary>
    [HarmonyPrefix]
    private static bool BlockWhileViewerOpen() => !ViewerBehaviour.IsOpen;
}

/// <summary>
/// 离线启动:用假凭证跳过 DMM 启动参数校验(原游戏由 DMM Game Player 传入 openid/accessToken,
/// 直接双击 exe 时没有参数会导致校验失败)。仅在配置 OfflineAuth=true 时生效。
/// </summary>
[HarmonyPatch]
internal static class OfflineStartupPatch
{
    /// <summary>定位 CommandLineArgs.Parse(在 interop 里是私有方法,用反射定位)。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(Dmm.Games.Sdk.CommandLineArgs), "Parse");

    /// <summary>写入假凭证并直接把结果置为成功,跳过原解析。</summary>
    [HarmonyPrefix]
    private static bool UseFakeCredentials(Dmm.Games.Sdk.CommandLineArgs __instance, ref bool __result)
    {
        if (!Plugin.OfflineAuth.Value)
            return true;

        SetProperty(__instance, "OpenId", "114514");
        SetProperty(__instance, "AccessToken", "1919810");
        SetProperty(__instance, "IsSuccess", true);
        __result = true;
        Plugin.Logger.LogInfo("离线启动:已注入假凭证");
        return false;
    }

    /// <summary>通过反射设置私有属性(interop 的 setter 是 private)。</summary>
    private static void SetProperty(object target, string name, object value)
    {
        var prop = AccessTools.Property(target.GetType(), name);
        if (prop == null)
        {
            Plugin.Logger.LogWarning($"离线启动:找不到属性 {name}");
            return;
        }
        prop.SetValue(target, value);
    }
}

/// <summary>
/// 离线启动时把 API 根地址改成配置值(默认空 = 不改);
/// 配合 OfflineAuth 使用,避免假凭证打到官方接口。
/// </summary>
[HarmonyPatch]
internal static class ApiRedirectPatch
{
    /// <summary>定位 Absf.RuntimeConfig.GetApiUrl。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(Absf.RuntimeConfig), "GetApiUrl");

    /// <summary>把返回值替换为配置的 API 根地址(离线模式优先用本地假 API 服务器)。</summary>
    [HarmonyPrefix]
    private static bool Redirect(ref string __result)
    {
        if (Plugin.OfflineApi.Value && Plugin.ApiServer != null && Plugin.ApiServer.BaseUrl.Length > 0)
        {
            // 抓包转发需要「游戏原本指向哪里」,在第一次重定向时记下来。
            if (string.IsNullOrEmpty(Plugin.OriginalApiBase) && !string.IsNullOrEmpty(__result))
            {
                Plugin.OriginalApiBase = __result;
                Plugin.Logger.LogInfo($"[抓包] 游戏原始 API 根地址 = {__result}");
            }
            __result = Plugin.ApiServer.BaseUrl;
            return false;
        }
        string api = Plugin.ApiBase.Value;
        if (string.IsNullOrWhiteSpace(api))
            return true;
        __result = api.TrimEnd('/');
        return false;
    }
}
