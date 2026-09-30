using HarmonyLib;
using Project;
using UnityEngine.EventSystems;

namespace StoryViewer.Patches;

/// <summary>
/// 窗口显示期间的输入屏蔽(照 AbyssMod 的 SettingsMenuInputPatch / SettingsMenuRaycastPatch):
///
/// 1. 跳过 <c>Project.InputService.OnUpdate</c>,并清掉按下/长按/计时状态,
///    这样游戏收不到点击与拖拽(也顺带切断了 TouchUtility 相关调用链);
/// 2. 清空 <c>EventSystem.RaycastAll</c> 的结果,游戏 uGUI 收不到悬停/点击穿透;
/// 3. <b>不禁用 EventSystem</b>——游戏的 <c>TouchUtility.GetTouchedUIList</c> 依赖它,
///    禁用会导致每帧 NullReferenceException(实测踩过)。
///
/// 屏蔽时机由 <see cref="InputGuard"/> 控制:关窗后还会多屏蔽几帧,直到鼠标完全静止。
/// </summary>
[HarmonyPatch]
internal static class GameInputBlockPatch
{
    /// <summary>窗口打开时跳过游戏的输入更新,并清空残留的按压状态。</summary>
    [HarmonyPrefix, HarmonyPatch(typeof(InputService), nameof(InputService.OnUpdate))]
    private static bool BlockGameInput(InputService __instance)
    {
        if (!InputGuard.BlocksGame)
            return true;

        // 丢弃打开窗口前残留的按住/拖拽状态,避免关窗后补发点击。
        __instance._inputState = InputState.None;
        __instance._holdEventTriggered = false;
        __instance._startTime = 0f;
        return false;
    }

    /// <summary>窗口打开时清空 uGUI 射线结果,避免点击落到游戏界面上。</summary>
    [HarmonyPostfix, HarmonyPatch(typeof(EventSystem), nameof(EventSystem.RaycastAll))]
    private static void BlockUiRaycasts(Il2CppSystem.Collections.Generic.List<RaycastResult> __1)
    {
        if (!InputGuard.BlocksGame)
            return;
        __1.Clear();
    }
}
