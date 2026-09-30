using System.Reflection;
using HarmonyLib;

namespace StoryViewer.Patches;

/// <summary>
/// 剧情播放前的「データダウンロード」(语音/分割下载)确认弹窗:离线档直接跳过。
/// <para>
/// 弹窗本身会加载预制体并等待玩家选择;离线环境里资源全部在本地,无需下载,
/// 跳过可以让 <c>NovelSceneTransitionUtility.ChangeSceneAsync</c> 的流程直接继续。
/// </para>
/// 目标方法:<c>NovelSceneTransitionUtility.ShowSplitDownloadConfirmPopupAsync</c>
/// (private static UniTask,参数含待下载的 assetKeys / voiceKeys)。
/// </summary>
[HarmonyPatch]
internal static class Novel_ShowSplitDownloadConfirmPopup
{
    /// <summary>只有配置打开时才安装(默认打开:离线资源都已缓存在本地)。</summary>
    public static bool Enabled => Plugin.SkipNovelDownloadPopup.Value;

    /// <summary>按名字定位私有静态方法。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(Project.Novel.NovelSceneTransitionUtility), "ShowSplitDownloadConfirmPopupAsync");

    /// <summary>
    /// 记录待下载数量后直接返回已完成的任务:调用方会立刻继续播剧情,
    /// 不再加载/显示下载确认弹窗。
    /// </summary>
    /// <param name="__result">原方法返回值,跳过时写入已完成任务。</param>
    /// <param name="__args">原方法实参,用于记录待下载数量。</param>
    /// <returns>false = 不执行原方法。</returns>
    [HarmonyPrefix]
    private static bool Skip(ref Cysharp.Threading.Tasks.UniTask __result, object[] __args)
    {
        Plugin.Logger.LogInfo(
            $"[剧情] 跳过「数据下载」确认弹窗(待下载资源 {CountOf(__args, 2)} 项 / 语音 {CountOf(__args, 3)} 项)");
        __result = Cysharp.Threading.Tasks.UniTask.CompletedTask;
        return false;
    }

    /// <summary>
    /// 尽力读取第 idx 个实参(列表)的元素个数;读不到返回 -1。
    /// 仅用于诊断日志,任何异常都不得影响播放流程。
    /// </summary>
    private static int CountOf(object[] args, int idx)
    {
        try
        {
            if (args == null || args.Length <= idx || args[idx] == null)
                return -1;
            var count = args[idx].GetType().GetProperty("Count");
            return count != null ? (int)count.GetValue(args[idx]) : -1;
        }
        catch
        {
            return -1;
        }
    }
}
