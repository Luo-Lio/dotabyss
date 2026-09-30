using System;
using Cysharp.Threading.Tasks;
using Project.Novel;

namespace StoryViewer;

/// <summary>
/// 用游戏自身的剧情场景 API 播放任意剧情。
///
/// 调用链(全部为正式客户端里已有的公开 API,与游戏「资料室 → 播放」同路):
///   1. <c>TopParam.CreateParam(novelId, skipR18)</c> 构造剧情场景参数;
///   2. <c>NovelSceneTransitionUtility.ChangeSceneAsync(param, SceneLoadMode, ct)</c>
///      切换/加载 Novel 场景并开始播放(含素材缺失时的下载确认流程)。
///
/// 该路径不经过任何「剧情开始」服务器请求,播放资源全部取自本地缓存。
/// </summary>
internal static class NovelPlayer
{
    /// <summary>
    /// 播放指定剧情。
    /// </summary>
    /// <param name="novelId">剧情 key(scriptId,如 mas_1001011001)。</param>
    /// <param name="skipR18">是否跳过 R18 段。</param>
    /// <returns>null 表示已发起播放;否则为错误信息。</returns>
    internal static string Play(string novelId, bool skipR18)
    {
        try
        {
            if (string.IsNullOrEmpty(novelId))
                return "novelId 为空";

            var param = TopScene.TopParam.CreateParam(novelId, skipR18);
            if (param == null)
            {
                // CreateParam 查不到该 scriptId 时返回 null(interop 侧不会抛异常,原生侧会静默失败)。
                Plugin.Logger.LogWarning($"CreateParam 返回 null,无法播放: {novelId}");
                return $"游戏主数据里找不到该剧情({novelId})";
            }

            // 注意:CancellationToken 在 interop 里是引用类型,ChangeSceneAsync 内部对它做了
            // Il2CppObjectBaseToPtrNotNull → 传 null 会直接 NullReferenceException。必须给实例。
            var ct = Il2CppSystem.Threading.CancellationToken.None;
            var task = NovelSceneTransitionUtility.ChangeSceneAsync(
                param, Absf.SceneLoadMode.NewScenePushHistory, ct);
            UniTaskExtensions.Forget(task);

            Plugin.Logger.LogInfo($"发起剧情播放: {novelId} (skipR18={skipR18})");
            return null;
        }
        catch (Exception e)
        {
            Plugin.Logger.LogError($"播放剧情失败 {novelId}: {e}");
            return $"{e.GetType().Name}: {e.Message}";
        }
    }
}
