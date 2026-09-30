using HarmonyLib;
using Project;
using Project.Home;
using Project.Outgame;
using UnityEngine;

namespace StoryViewer.Patches;

/// <summary>
/// 屏蔽与「看剧情/CG」无关的功能入口:只隐藏界面元素并拦截跳转,不改写任何游戏数据。
/// <para>保留:主页、任务选择页(主线/支线剧情)、资料室、角色详情、菜单里的图书馆/设置/标题/帮助/下载/退出。</para>
/// <para>
/// 隐藏策略:在官方视图初始化/刷新方法之后把对应控件的 GameObject 关掉(inactive 的按钮
/// 不会响应点击),再用场景跳转拦截兜底(横幅、残留入口)。不使用禁用 EventSystem、
/// 不修改按钮表的引用,避免 Async 刷新时序与 NRE 风险。
/// </para>
/// <para>各项开关见配置 [Hide] 段,均可单独关闭。</para>
/// </summary>
[HarmonyPatch]
internal static class HideFeaturesPatch
{
    /// <summary>隐藏一个 Unity 组件所在的 GameObject。</summary>
    private static void Hide(Component c)
    {
        if (c != null)
            c.gameObject.SetActive(false);
    }

    /// <summary>隐藏一个 GameObject(如徽标)。</summary>
    private static void Hide(GameObject go)
    {
        if (go != null)
            go.SetActive(false);
    }

    /// <summary>隐藏 Home 的按钮包装类型(非组件,必须走它自己的 SetActiveSelf)。</summary>
    private static void HideButton(ButtonView.ButtonWithBadge b)
    {
        if (b != null)
            b.SetActiveSelf(false);
    }

    // ---------------------------------------------------------------
    // 底部导航:只留「主页」「任务」(任务页里有主线/支线剧情入口)
    // ---------------------------------------------------------------

    /// <summary>底部导航初始化后精简。</summary>
    [HarmonyPatch(typeof(GlobalFooterViewController), nameof(GlobalFooterViewController.InitializeView))]
    [HarmonyPostfix]
    private static void FooterInit(GlobalFooterViewController __instance) => HideFooter(__instance);

    /// <summary>底部导航按显示模式刷新后再次精简(刷新会把按钮重新激活)。</summary>
    [HarmonyPatch(typeof(GlobalFooterViewController), nameof(GlobalFooterViewController.UpdateView))]
    [HarmonyPostfix]
    private static void FooterUpdate(GlobalFooterViewController __instance) => HideFooter(__instance);

    /// <summary>隐藏派对/商店/抽卡/酒馆(普通与 R18)/放置探索入口。</summary>
    private static void HideFooter(GlobalFooterViewController v)
    {
        if (!Plugin.HideFooter.Value)
            return;
        Hide(v._partyButton);
        Hide(v._shopButton);
        Hide(v._gachaButton);
        Hide(v._tavernNormalButton);
        Hide(v._tavernR18Button);
        Hide(v._explorationButton);
        PatchLog.Once("底部导航已精简(保留主页/任务)");
    }

    // ---------------------------------------------------------------
    // 主页按钮组:隐藏任务/礼物箱/通行证/SP任务/月卡/推荐/建筑
    // 保留:公告、R18 剧情入口(属于剧情内容)
    // ---------------------------------------------------------------

    /// <summary>主页按钮组初始化后精简。</summary>
    [HarmonyPatch(typeof(ButtonViewController), nameof(ButtonViewController.Initialize))]
    [HarmonyPostfix]
    private static void HomeButtonsInit(ButtonViewController __instance) => HideHomeButtons(__instance);

    /// <summary>主页按钮组刷新后再次精简(徽标状态刷新会重设激活)。</summary>
    [HarmonyPatch(typeof(ButtonViewController), nameof(ButtonViewController.UpdateView))]
    [HarmonyPostfix]
    private static void HomeButtonsUpdate(ButtonViewController __instance) => HideHomeButtons(__instance);

    /// <summary>隐藏主页上与观看剧情无关的入口按钮。</summary>
    private static void HideHomeButtons(ButtonViewController c)
    {
        if (!Plugin.HideHomeButtons.Value)
            return;
        var v = c._buttonView;
        if (v == null)
            return;
        HideButton(v._mission);      // 任务
        HideButton(v._presentBox);   // 礼物箱
        HideButton(v._missionPass);  // 通行证
        HideButton(v._spMission);    // SP 任务
        Hide(v._plan);               // 月卡/计划(AppButton)
        Hide(v._recommend);          // 推荐/抽卡(AppButton)
        Hide(v._building);           // Home 建筑
        Hide(v._planBadge);
        PatchLog.Once("主页按钮已精简(保留公告/R18剧情)");
    }

    // ---------------------------------------------------------------
    // 菜单弹窗:隐藏好友/道具/VIP/自动分解/签到/数据联动/序列码/客服
    // 保留:图书馆、设置、标题、帮助、下载(离线缓存用)、退出
    // ---------------------------------------------------------------

    /// <summary>菜单弹窗初始化后精简。</summary>
    [HarmonyPatch(typeof(MenuPopup), nameof(MenuPopup.Initialize))]
    [HarmonyPostfix]
    private static void MenuPopupInit(MenuPopup __instance) => HideMenuButtons(__instance);

    /// <summary>菜单弹窗按条件切换按钮激活后再次精简。</summary>
    [HarmonyPatch(typeof(MenuPopup), nameof(MenuPopup.SwitchButtonActives))]
    [HarmonyPostfix]
    private static void MenuPopupSwitch(MenuPopup __instance) => HideMenuButtons(__instance);

    /// <summary>隐藏菜单弹窗里与剧情观看无关的入口。</summary>
    private static void HideMenuButtons(MenuPopup m)
    {
        if (!Plugin.HideMenuPopup.Value)
            return;
        Hide(m._friend);
        Hide(m._item);
        Hide(m._vip);
        Hide(m._autoDisassemblyOption);
        Hide(m._loginBonus);
        Hide(m._dataLinkage);
        Hide(m._serialCode);
        Hide(m._inquiry);
        PatchLog.Once("菜单弹窗已精简(保留图书馆/设置/标题/帮助/下载/退出)");
    }

    // ---------------------------------------------------------------
    // 任务选择页:隐藏奈落/灾厄/训练所/连合,保留主线与支线剧情
    // ---------------------------------------------------------------

    /// <summary>任务选择页初始化完成后精简。</summary>
    [HarmonyPatch(typeof(Project.QuestSelect.Top.SubViewController),
        nameof(Project.QuestSelect.Top.SubViewController.InitializeAsync))]
    [HarmonyPostfix]
    private static void QuestSelectInit(Project.QuestSelect.Top.SubViewController __instance) =>
        HideQuestButtons(__instance);

    /// <summary>任务选择页按星期刷新后再次精简。</summary>
    [HarmonyPatch(typeof(Project.QuestSelect.Top.SubViewController),
        nameof(Project.QuestSelect.Top.SubViewController.ApplyDayOfWeek))]
    [HarmonyPostfix]
    private static void QuestSelectRefresh(Project.QuestSelect.Top.SubViewController __instance) =>
        HideQuestButtons(__instance);

    /// <summary>隐藏任务选择页上的玩法入口(主线/支线按钮保留)。</summary>
    private static void HideQuestButtons(Project.QuestSelect.Top.SubViewController v)
    {
        if (!Plugin.HideQuestSelect.Value)
            return;
        Hide(v._netherButton);
        Hide(v._disasterButton);
        Hide(v._trainingCenterButton);
        Hide(v._unionQuestButton);
        PatchLog.Once("任务选择页已精简(保留主线/支线剧情)");
    }

    // ---------------------------------------------------------------
    // 场景跳转拦截(兜底):横幅、引导、残留入口点击后直接拦下
    // ---------------------------------------------------------------

    /// <summary>被屏蔽的场景跳转(剧情相关场景一律放行)。</summary>
    private static bool IsBlocked(TransitionSceneId id)
    {
        switch (id)
        {
            case TransitionSceneId.PartyEdit:       // 队伍编成
            case TransitionSceneId.Equipment:       // 装备
            case TransitionSceneId.Research:        // 研究
            case TransitionSceneId.Unit:            // 角色养成
            case TransitionSceneId.Gacha:           // 抽卡
            case TransitionSceneId.Tavern:          // 酒馆(玩法;酒馆剧情在故事面板)
            case TransitionSceneId.Shop:            // 商店
            case TransitionSceneId.PartyTop:        // 队伍
            case TransitionSceneId.IdleExploration: // 放置探索
            case TransitionSceneId.DisasterTop:     // 灾厄
            case TransitionSceneId.DisasterParty:   // 灾厄编队
            case TransitionSceneId.SpMission:       // SP 任务
            case TransitionSceneId.Friend:          // 好友
            case TransitionSceneId.Profile:         // 名片
            case TransitionSceneId.LevelSynchro:    // 等级同步
            case TransitionSceneId.UnionRequest:    // 连合要请
                return true;
            default:
                // 放行:Home / QuestSelect / MainStory / Novel / Library / Interaction 等剧情路径
                return false;
        }
    }

    /// <summary>拦截带参数的场景跳转(每次调用都记「拦截/放行」,便于定位"卡在跳转"问题)。</summary>
    [HarmonyPatch(typeof(SceneTransitionUtility), nameof(SceneTransitionUtility.ChangeScene))]
    [HarmonyPrefix]
    private static bool BlockChangeScene(TransitionSceneId transitionSceneId)
    {
        bool blocked = Plugin.BlockScenes.Value && IsBlocked(transitionSceneId);
        PatchLog.Once($"跳转 {transitionSceneId} → {(blocked ? "拦截" : "放行")}");
        return !blocked;
    }

    /// <summary>拦截不带参数的场景跳转(同样记录拦截/放行)。</summary>
    [HarmonyPatch(typeof(SceneTransitionUtility), nameof(SceneTransitionUtility.ChangeSceneTop))]
    [HarmonyPrefix]
    private static bool BlockChangeSceneTop(TransitionSceneId transitionSceneId)
    {
        bool blocked = Plugin.BlockScenes.Value && IsBlocked(transitionSceneId);
        PatchLog.Once($"跳转(Top) {transitionSceneId} → {(blocked ? "拦截" : "放行")}");
        return !blocked;
    }
}
