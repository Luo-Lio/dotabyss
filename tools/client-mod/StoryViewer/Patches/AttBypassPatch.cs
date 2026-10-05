using Cysharp.Threading.Tasks;
using HarmonyLib;
using Project.Title;

namespace StoryViewer.Patches;

/// <summary>
/// Title 场景 ATT(实名/年龄授权)检查的离线旁路(0.7.27)。
/// <para>
/// 现象(玩家 22:41 诊断包):全新机器装好离线包,EngineBootGuard 已把
/// <c>AppEngine.OnServiceRegistered</c> 的 <c>BitConverter.ToBoolean(null)</c> 抑制住,
/// 流程走到 Title 场景后又撞同族第二处崩溃——
/// <c>TopScene.OnInitializeImplAsync → ATTPermissionCheck → ATTManager.RequestAuthorizationAsync
/// → BitConverter.ToBoolean(null)</c>,异常经 UniTask 异步链被捕获成「未观察异常」,
/// Title 初始化停住、进不了 Home。开发机能过是因为早年装过在线版、机器侧早有那份授权缓存;
/// 新机器没有 → 读 null → 崩。这正是「脱离原版依赖」没做到位的根因。
/// </para>
/// <para>
/// 修复方式:ATT 是 DMM 的实名/年龄授权门(代码语义在 Windows 本应「直接过」)。
/// 直接把 <c>TopScene.ATTPermissionCheck</c>(返回 <see cref="UniTask"/>)短路成
/// 一个**已完成**的 UniTask,不让它去 await <c>RequestAuthorizationAsync</c>,
/// 于是既不读那份不存在的缓存、OnInitializeImplAsync 也能继续走到 Home。
/// 这与已验证可用的 <see cref="Dmm_PlatformInitBypass"/> 用的是同一套「置 __result=已完成的 UniTask」手法,
/// 不碰 async 状态机本身,风险最低。
/// </para>
/// <para>由 <see cref="Plugin.BypassTitleAtt"/> 控制(默认开:离线必需)。关闭时整类不安装,走游戏原逻辑。</para>
/// </summary>
[HarmonyPatch(typeof(TopScene), "ATTPermissionCheck")]
internal static class AttBypassPatch
{
    /// <summary>配置开关:关闭时整个补丁类不安装(交给游戏原逻辑)。</summary>
    public static bool Enabled => Plugin.BypassTitleAtt.Value;

    /// <summary>旁路日志只播报一次(Title 场景可能多次进入)。</summary>
    private static bool _logged;

    /// <summary>把 ATT 检查直接判为「已通过」:返回已完成的 UniTask、跳过原异步授权流程。</summary>
    private static bool Prefix(ref UniTask __result)
    {
        __result = UniTask.CompletedTask;
        if (!_logged)
        {
            _logged = true;
            Plugin.Logger?.LogInfo(
                "[Title ATT] 离线旁路:跳过 ATTPermissionCheck(不走 ATTManager.RequestAuthorizationAsync),"
                + "避免全新机器读空授权缓存导致 BitConverter.ToBoolean(null) 卡在 Title。");
        }
        return false;
    }
}
