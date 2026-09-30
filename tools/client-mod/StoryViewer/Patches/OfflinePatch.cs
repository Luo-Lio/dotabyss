using Absf.Api;
using Absl.Cryptography;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

namespace StoryViewer.Patches;

/// <summary>
/// 离线模式的协议层补丁:跳过请求体加解密与版本校验。
/// <para>
/// 处理依据(2026-09-23 实机 Player.log):
/// 1. <c>Absl.Cryptography.Crypto.Encrypt</c> 收到空 cryptoKey → <c>Encoding.GetBytes(null)</c> 崩溃;
/// 2. <c>ApiManager.CheckValidVersion</c> 对 null 的版本数组调用 <c>Enumerable.Contains</c> 崩溃;
/// 3. <c>ApiManager.SkipCheckVersion</c> 是官方预留的静态开关(可写)。
/// </para>
/// <para>
/// 仅在 <see cref="Plugin.OfflineApi"/> 打开、假服务器监听成功、
/// 且 <see cref="Plugin.SkipRequestEncryption"/> 为 true 时生效。
/// 在线对照/抓包(转发真实上游)时必须把 SkipRequestEncryption 关掉:真实服务器
/// 需要真实的加密请求体,否则解不开。
/// </para>
/// </summary>
[HarmonyPatch]
internal static class OfflinePatch
{
    /// <summary>离线模式判定(开关打开且假 API 服务器已在监听)。</summary>
    private static bool Offline =>
        Plugin.OfflineApi.Value &&
        Plugin.SkipRequestEncryption.Value &&
        Plugin.ApiServer != null &&
        Plugin.ApiServer.BaseUrl.Length > 0;

    /// <summary>请求体加密(单参重载)改为原样返回:假服务器忽略正文,不需要真实密文。</summary>
    [HarmonyPatch(typeof(Crypto), nameof(Crypto.Encrypt), new[] { typeof(Il2CppStructArray<byte>) })]
    [HarmonyPrefix]
    private static bool EncryptBytes(ref Il2CppStructArray<byte> __result, Il2CppStructArray<byte> data)
    {
        if (!Offline)
            return true;
        __result = data;
        return false;
    }

    /// <summary>请求体加密(带 key 重载)改为原样返回,避开空 key 崩溃。</summary>
    [HarmonyPatch(typeof(Crypto), nameof(Crypto.Encrypt), new[] { typeof(Il2CppStructArray<byte>), typeof(string) })]
    [HarmonyPrefix]
    private static bool EncryptBytesWithKey(ref Il2CppStructArray<byte> __result, Il2CppStructArray<byte> data)
    {
        if (!Offline)
            return true;
        __result = data;
        return false;
    }

    /// <summary>ApiCrypt 的请求体加密同样原样返回(双保险)。</summary>
    [HarmonyPatch(typeof(ApiCrypt), nameof(ApiCrypt.EncryptBody))]
    [HarmonyPrefix]
    private static bool EncryptBody(ref Il2CppStructArray<byte> __result, Il2CppStructArray<byte> data)
    {
        if (!Offline)
            return true;
        __result = data;
        return false;
    }

    /// <summary>ApiCrypt 的 Laravel 流加密原样返回(离线时不使用)。</summary>
    [HarmonyPatch(typeof(ApiCrypt), nameof(ApiCrypt.EncryptLaravel))]
    [HarmonyPrefix]
    private static bool EncryptLaravel(ref string __result, string payload)
    {
        if (!Offline)
            return true;
        __result = payload;
        return false;
    }

    /// <summary>版本校验一律判定为通过(离线时没有真实版本信息可比)。</summary>
    [HarmonyPatch(typeof(ApiManager), nameof(ApiManager.CheckValidVersion))]
    [HarmonyPostfix]
    private static void SkipVersion(ref VersionErrorType __result)
    {
        if (Offline)
            __result = VersionErrorType.None;
    }
}
