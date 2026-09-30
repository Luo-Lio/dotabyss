using UnityEngine;

namespace StoryViewer;

/// <summary>
/// 游戏层输入屏蔽状态机(照 AbyssMod 的 MenuMouseIsolation 方案实现)。
///
/// 窗口打开期间通过 Harmony 补丁拦掉游戏自己的输入入口;关闭窗口后仍继续屏蔽,
/// 直到出现「没有鼠标活动」的干净帧才放行——否则关窗那一下的点击会被游戏补发,
/// 造成「关了窗口却顺手点了游戏 UI」。
///
/// 这里绝不修改 Unity 的输入 API、也不禁用 EventSystem:游戏的
/// <c>TouchUtility.GetTouchedUIList</c> 依赖 EventSystem,禁用后每帧都会抛
/// NullReferenceException(实测)。
/// </summary>
internal static class InputGuard
{
    /// <summary>上一个「无鼠标活动」帧号;-1 表示尚未出现。</summary>
    private static int _cleanFrame = -1;

    /// <summary>关闭窗口时的帧号,保证干净帧判定发生在关窗之后。</summary>
    private static int _closeFrame;

    /// <summary>窗口是否处于打开状态(界面可见)。</summary>
    internal static bool IsOpen { get; private set; }

    /// <summary>是否仍需要屏蔽游戏输入(窗口打开中,或关窗后尚未出现干净帧)。</summary>
    internal static bool BlocksGame { get; private set; }

    /// <summary>打开窗口:立即开始屏蔽游戏输入。</summary>
    internal static void Begin()
    {
        IsOpen = true;
        BlocksGame = true;
        _cleanFrame = -1;
    }

    /// <summary>关闭窗口:保持屏蔽,等鼠标完全静止的帧再放行。</summary>
    internal static void End()
    {
        IsOpen = false;
        BlocksGame = true;
        _closeFrame = Time.frameCount;
        _cleanFrame = -1;
    }

    /// <summary>每帧调用:采集鼠标/触摸活动并推进状态机。</summary>
    internal static void Tick()
    {
        if (!BlocksGame || IsOpen)
            return;

        bool mouseActivity = false;
        for (int i = 0; i < 7; i++)
        {
            var key = (KeyCode)((int)KeyCode.Mouse0 + i);
            mouseActivity |= Input.GetKey(key) || Input.GetKeyDown(key) || Input.GetKeyUp(key);
        }
        var scroll = Input.mouseScrollDelta;
        mouseActivity |= scroll.x != 0f || scroll.y != 0f || Input.touchCount != 0;

        Advance(Time.frameCount, mouseActivity);
    }

    /// <summary>
    /// 状态机推进(与输入读取分离,便于推理):
    /// 连续两帧以上无鼠标活动、且帧号晚于关窗帧时解除屏蔽。
    /// </summary>
    /// <param name="frame">当前帧号(Time.frameCount)。</param>
    /// <param name="mouseActivity">本帧是否存在鼠标/触摸活动。</param>
    internal static void Advance(int frame, bool mouseActivity)
    {
        if (!BlocksGame || IsOpen)
            return;

        if (mouseActivity)
        {
            _cleanFrame = -1;
            return;
        }
        if (_cleanFrame < 0)
            _cleanFrame = frame;
        else if (frame > _cleanFrame && frame > _closeFrame)
            BlocksGame = false;
    }

    /// <summary>强制解除屏蔽(组件销毁/插件卸载时调用,保证不留下永久屏蔽)。</summary>
    internal static void ForceRelease()
    {
        IsOpen = false;
        BlocksGame = false;
        _cleanFrame = -1;
    }
}
