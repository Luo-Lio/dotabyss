using System;
using System.Reflection;
using System.Text;
using HarmonyLib;

namespace StoryViewer.Patches;

/// <summary>
/// 游戏错误弹窗:把内容写进日志,并可按配置跳过弹出。
/// <para>
/// 离线环境里极小的资源缺失(例如某个 .awb 流式音频)也会弹错误框并卡住剧情播放;
/// 跳过弹窗不丢信息——错误码/标题/正文都会先写进日志,便于和 offline-api.log 对照。
/// </para>
/// 目标方法是显式接口实现,interop 里的名字是
/// <c>Project_IExceptionService_RequestErrorPopupAsync</c>,不能写死,按名字在类型上查。
/// </summary>
[HarmonyPatch]
internal static class ErrorPopup_LogAndSkip
{
    /// <summary>定位 Project.ExceptionService 上的显式接口实现方法。</summary>
    [HarmonyTargetMethod]
    private static MethodBase TargetMethod() =>
        AccessTools.Method(typeof(Project.ExceptionService), "Project_IExceptionService_RequestErrorPopupAsync");

    /// <summary>
    /// 记录弹窗内容;SuppressErrorPopups 打开时以「用户点了确认」直接返回(UniTask&lt;bool&gt; 的 true),
    /// 让调用方走成功分支继续,不再等用户点掉弹窗。
    /// </summary>
    /// <param name="__result">原方法的返回值,跳过时写入 true。</param>
    /// <param name="__args">原方法实参,第一个是 ErrorParam。</param>
    /// <returns>true = 继续执行原方法(照常弹窗);false = 跳过原方法。</returns>
    [HarmonyPrefix]
    private static bool LogAndMaybeSkip(ref Cysharp.Threading.Tasks.UniTask<bool> __result, object[] __args)
    {
        if (Plugin.ErrorPopupLog.Value)
            Plugin.Logger.LogWarning($"[错误弹窗] {Describe(__args)}");

        if (!Plugin.SuppressErrorPopups.Value)
            return true;

        __result = Cysharp.Threading.Tasks.UniTask.FromResult(true);
        Plugin.Logger.LogInfo("离线模式:已跳过错误弹窗(按「确认」继续)");
        return false;
    }

    /// <summary>把 ErrorParam 的关键字段拼成一行;无参数或读取失败时给出可读的兜底文本。</summary>
    private static string Describe(object[] args)
    {
        object param = args != null && args.Length > 0 ? args[0] : null;
        if (param == null)
            return "(无参数)";

        var sb = new StringBuilder();
        TryAppend(sb, param, "errorCode");
        TryAppend(sb, param, "title");
        TryAppend(sb, param, "message");
        TryAppend(sb, param, "confirmText");
        TryAppend(sb, param, "hideAllButtons");
        return sb.Length > 0 ? sb.ToString() : param.GetType().Name;
    }

    /// <summary>
    /// 反射读取一个属性并追加到诊断行(单个字段读不到就跳过)。
    /// 诊断日志绝不能反过来影响游戏流程,因此这里吞掉异常。
    /// </summary>
    private static void TryAppend(StringBuilder sb, object target, string name)
    {
        try
        {
            var prop = target.GetType().GetProperty(name);
            string value = prop?.GetValue(target)?.ToString();
            if (string.IsNullOrEmpty(value))
                return;
            if (value.Length > 300)
                value = value[..300] + "…";
            if (sb.Length > 0)
                sb.Append(" | ");
            sb.Append(name).Append('=').Append(value);
        }
        catch
        {
            // 忽略:字段缺失/类型不匹配都不影响弹窗控制逻辑。
        }
    }
}
