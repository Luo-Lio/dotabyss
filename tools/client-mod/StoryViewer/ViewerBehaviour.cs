using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes;
using StoryViewer.Patches;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace StoryViewer;

/// <summary>
/// 剧情浏览器窗口 · 方案「画廊」:左侧系列竖栏 + 中间卡片网格 + 右侧详情。
///
/// 布局(1080×700,居中):
/// <code>
/// ┌────┬──────────────────────────────────────────────┬──────────────┐
/// │ 系 │  当前分组标题 · N 条        [仅R18][续篇][搜索][×] │              │
/// │ 列 │  ┌────┐ ┌────┐ ┌────┐                       │   预览大图    │
/// │ 竖 │  │卡片│ │卡片│ │卡片│                       │   标题/key    │
/// │ 栏 │  └────┘ └────┘ └────┘                       │   分段 ①②③   │
/// │    │  ┌────┐ ┌────┐ ┌────┐                       │   简介        │
/// │    │  │卡片│ │卡片│ │卡片│                       │   [播放剧情]  │
/// │    │  共 N 条 · 当前 M 条        操作提示           │              │
/// └────┴──────────────────────────────────────────────┴──────────────┘
/// </code>
///
/// 视觉:暖炭底色 + 琥珀强调色;标题用思源宋体,正文思源黑体,key 用等宽字体。
/// 全部控件自绘(圆角/投影贴图运行时生成,见 <see cref="UiKit"/>,不回退默认皮肤)。
///
/// 输入隔离:窗口显示期间用 Harmony 补丁拦掉游戏自己的输入入口(见 InputGuard /
/// GameInputBlockPatch),<b>不禁用 EventSystem</b>。
///
/// 实现注意:本游戏的 Unity 6 IL2CPP 构建把不少 IMGUI 方法裁成了桩(调用即抛
/// NotSupportedException("Method unstripping failed")),已确认的有:
/// <c>GUILayout.Space</c>、<c>GUILayout.FlexibleSpace</c>、<c>GUI.BeginScrollView</c>(8 参数)、
/// <c>GUI.EndScrollView(bool)</c>、<c>GUI.Scroller</c>、<c>GUI.TextField</c> 等。
/// 因此窗口全部用显式 Rect 的 GUI.* 绘制,并按区域隔离异常;输入框自绘(Input.inputString +
/// Input.compositionString,聚焦时自己打开输入法),滚动用 GUI.BeginGroup 裁剪 + 滚轮/翻页键自绘。
///
/// 注入注意:本类型是注册进 IL2CPP 的 MonoBehaviour,Il2CppInterop 会遍历它声明的全部
/// 实例方法生成 native thunk。**禁止**使用「捕获变量的本地函数」——编译器会把它生成
/// 带 ref 闭包参数(<c>&lt;&gt;c__DisplayClass</c>)的私有方法,注入时在
/// <c>ClassInjector.ConvertMethodInfo</c>(ByRef 分支)抛 NullReferenceException 导致插件
/// 加载失败;实例方法的参数也不要 ref/out。静态方法不参与注入,不受此限。
/// </summary>
public class ViewerBehaviour : MonoBehaviour
{
    // ---------------------------------------------------------------- 布局数值
    //
    // 设计基准 = 1080p 下的 1080×700 窗口。0.7.13:这些数值改为实例字段,
    // 首次打开时由 ApplyUiScale() 按屏幕高度整体放大(解决「窗口/文字偏小」);
    // 只放大不缩小,小屏保持 1×,避免元素重叠。

    /// <summary>UI 整体缩放系数(1.0 = 1080p 基准)。</summary>
    private static float _uiScale = 1f;

    /// <summary>是否已按当前屏幕算过一次缩放。</summary>
    private bool _scaleApplied;
    // 0.7.27:记录上次应用缩放时的屏幕尺寸;窗口放大/全屏切换后据此重算缩放与布局,
    // 修「游戏窗口变大、剧情面板不跟着变大(仍按首次打开时的小尺寸居中)」的问题。
    private int _lastScreenW = -1;
    private int _lastScreenH = -1;

    /// <summary>把设计尺寸换算成实际像素(静态方法:类注释禁止实例方法内的本地函数)。</summary>
    private static int S(int design) => Mathf.RoundToInt(design * _uiScale);

    private int WindowW = 1080;
    private int WindowH = 700;
    /// <summary>左侧系列竖栏宽。</summary>
    private int RailW = 72;
    /// <summary>顶栏高。</summary>
    private int TopH = 64;
    /// <summary>卡片网格区域。</summary>
    private int GridX = 96;
    private int GridY = 88;
    private int GridW = 654;
    private int GridH = 572;
    /// <summary>右栏详情宽度(贴在窗口右边)。</summary>
    private int DetailW = 306;
    private int DetailX = 1080 - 306;
    private int DetailPad = 20;
    /// <summary>卡片尺寸:总高 162 = 7 + 缩略图 108 + 6 + 标题 17 + 2 + 元信息 13 + 9。</summary>
    private int CardW = 207;
    private int CardH = 162;
    private int CardGap = 16;
    private const int CardsPerRow = 3;
    private int CardPad = 7;
    private int ThumbW = 193;
    private int ThumbH = 108;
    /// <summary>分组标题行高。</summary>
    private int GroupH = 30;
    private int GroupGap = 8;
    /// <summary>顶栏右侧控件。</summary>
    private int SearchW = 200;
    private int ControlH = 30;
    private int CloseW = 30;
    private int TogglePartsW = 56;
    private int ToggleR18W = 64;
    /// <summary>底部提示行。</summary>
    private int FooterH = 30;
    private int BodySize = 13;

    // ---------------------------------------------------------------- 配色(暖炭 + 琥珀)

    private static readonly Color ColWindow = new(0.078f, 0.067f, 0.063f, 1f);
    private static readonly Color ColWindowBorder = new(0.165f, 0.145f, 0.125f, 1f);
    private static readonly Color ColRail = new(0.098f, 0.086f, 0.078f, 1f);
    private static readonly Color ColLine = new(0.149f, 0.133f, 0.125f, 1f);
    private static readonly Color ColCard = new(0.129f, 0.118f, 0.106f, 1f);
    private static readonly Color ColCardBorder = new(0.180f, 0.161f, 0.145f, 1f);
    private static readonly Color ColCardHover = new(0.227f, 0.200f, 0.173f, 1f);
    private static readonly Color ColAmber = new(0.851f, 0.604f, 0.306f, 1f);
    private static readonly Color ColAmberLight = new(0.941f, 0.788f, 0.529f, 1f);
    private static readonly Color ColAmberBg = new(0.227f, 0.173f, 0.090f, 1f);
    private static readonly Color ColCream = new(0.925f, 0.894f, 0.851f, 1f);
    private static readonly Color ColMuted = new(0.608f, 0.569f, 0.518f, 1f);
    private static readonly Color ColFaint = new(0.435f, 0.400f, 0.357f, 1f);
    private static readonly Color ColSoft = new(0.635f, 0.592f, 0.498f, 1f);
    private static readonly Color ColR18 = new(0.698f, 0.227f, 0.169f, 1f);
    private static readonly Color ColR18Text = new(1f, 0.914f, 0.894f, 1f);
    private static readonly Color ColField = new(0.129f, 0.114f, 0.102f, 1f);
    private static readonly Color ColFieldBorder = new(0.200f, 0.176f, 0.157f, 1f);
    private static readonly Color ColPlaceholder = new(0.518f, 0.478f, 0.424f, 1f);
    private static readonly Color ColBand = new(0.106f, 0.094f, 0.082f, 1f);
    private static readonly Color ColPreviewBg = new(0.063f, 0.055f, 0.047f, 1f);
    private static readonly Color ColInk = new(0.137f, 0.102f, 0.055f, 1f);

    // ---------------------------------------------------------------- 状态

    private static ViewerBehaviour _instance;
    private StoryDatabase _db;
    private PreviewCache _previews;
    private List<StoryEntry> _filtered = new();
    private readonly List<Row> _rows = new();
    private readonly List<float> _rowTops = new();
    private readonly List<Cell> _cells = new();
    private float _contentH;
    private bool _filterDirty = true;
    private bool _open;
    private string _series = "all";
    private string _search = "";
    private bool _searchFocused;
    private bool _showParts;
    private bool _onlyR18;
    /// <summary>平滑滚动趋近速率(1/秒,越大越跟手;16 ≈ 0.15 秒到位)。</summary>
    private const float ScrollSmoothRate = 16f;
    /// <summary>滚动显示位置(每帧朝 <see cref="_scrollTarget"/> 平滑推进)。</summary>
    private float _scrollY;
    /// <summary>滚动目标位置(滚轮/按键/选中跟随立即改它,动画见 <see cref="AdvanceScroll"/>)。</summary>
    private float _scrollTarget;
    private string _status = "";
    /// <summary>主数据探测只做一次(打开列表时触发)。</summary>
    private bool _masterProbed;
    /// <summary>资源自举完成提示只在界面上播报一次。</summary>
    private bool _bootstrapNotified;
    private bool _fontAttempted;
    private string _selectedKey;
    private int _selCell = -1;
    private float _lastClickTime = -10f;
    private readonly HashSet<string> _sectionErrors = new();
    private float _nextSceneCheck;
    private float _nextAssetDiag;
    private string _lastScene = "";
    /// <summary>本帧输入法组合串(未确定的预编辑文本,由 CompositionText 采集)。</summary>
    private string _composing = "";
    /// <summary>上一帧的输入法组合串(拼字结束时兜底并入搜索词)。</summary>
    private string _lastComposing = "";
    /// <summary>本帧是否吃进了可见字符(用于区分「输入法提交文字的回车」与「结束输入的回车」)。</summary>
    private bool _searchTextThisFrame;
    /// <summary>当前是否已把输入法切到打开状态。</summary>
    private bool _imeOn;
    private bool _imeWarned;
    /// <summary>本帧鼠标命中的卡片(用于 hover 高亮;-1 表示无)。</summary>
    private int _hoverCell = -1;

    /// <summary>本次打开是否已把布局矩形写进日志。</summary>
    private bool _layoutLogged;
    /// <summary>覆盖前的原始皮肤字体(字体诊断对照用;用于比较“自建字体 vs 游戏皮肤字体”)。</summary>
    private Font _origSkinFont;

    // ---------------------------------------------------------------- 字体与样式

    private Font _fSans;
    private Font _fSerif;
    private Font _fMono;
    private GUIStyle _stTopTitle;
    private GUIStyle _stDetailTitle;
    private GUIStyle _stGroup;
    private GUIStyle _stCardTitle;
    private GUIStyle _stMeta;
    private GUIStyle _stSmall;
    private GUIStyle _stBody;
    private GUIStyle _stKey;
    private GUIStyle _stRail;
    /// <summary>无背景样式:只用来承载 GUI.Button 的点击热区,视觉全部自绘。</summary>
    private GUIStyle _stBlank;
    private bool _stylesReady;

    /// <summary>左侧竖栏条目。</summary>
    private sealed class RailItem
    {
        internal Rect Rect;
        internal string Key;
        internal string Label;
    }

    private readonly List<RailItem> _rail = new();

    /// <summary>网格行:分组标题,或一行卡片(最多 <see cref="CardsPerRow"/> 张)。</summary>
    private sealed class Row
    {
        /// <summary>true 表示分组标题行。</summary>
        internal bool Header;
        /// <summary>分组标题文本(仅 Header 行)。</summary>
        internal string Text;
        /// <summary>该分组的条目数(仅 Header 行)。</summary>
        internal int Count;
        /// <summary>该行的卡片(仅非 Header 行;末尾可能不足 3 张)。</summary>
        internal StoryEntry[] Items;
        /// <summary>行高(嵌套类取不到外层字段,由 BuildRows 按当前缩放后的数值填写)。</summary>
        internal float Height;
    }

    /// <summary>卡片在网格中的位置(行号 + 列号),用于键盘移动与选中定位。</summary>
    private sealed class Cell
    {
        internal int Row;
        internal int Col;
        internal StoryEntry Entry;
    }

    private Rect _winRect;
    private Rect _railRect;
    private Rect _topRect;
    private Rect _gridRect;
    private Rect _detailRect;
    private Rect _bigRect;
    private Rect _playRect;
    private Rect _footerRect;
    private Rect _searchRect;
    private Rect _closeRect;
    private Rect _toggleR18Rect;
    private Rect _togglePartsRect;

    /// <summary>窗口当前是否打开(供输入屏蔽补丁查询)。</summary>
    internal static bool IsOpen => InputGuard.IsOpen;

    // ---------------------------------------------------------------- 生命周期

    private void Awake()
    {
        _instance = this;
        _db = StoryDatabase.Load();
        _previews = new PreviewCache();
        if (!string.IsNullOrEmpty(_db.Error))
            _status = _db.Error;
    }

    private void OnDestroy()
    {
        PreviewCache cache = _previews;
        _previews = null;
        cache?.Dispose();
        InputGuard.ForceRelease();
        SetIme(false, force: true);
        if (_instance == this)
            _instance = null;
    }

    /// <summary>
    /// 打开列表时探一次游戏主数据(novel 脚本表)是否已装载。
    /// 离线档启动流程没走完时主数据可能是空的,那样播放剧情必然失败;
    /// 探测结果写日志并在界面上给提示。只读、异常全吞。
    /// </summary>
    private void ProbeMasterDataOnce()
    {
        if (_masterProbed)
            return;
        _masterProbed = true;
        try
        {
            var param = Project.Novel.TopScene.TopParam.CreateParam("mas_1001011001", false);
            bool ok = param != null;
            Plugin.Logger?.LogInfo($"[探针] 主数据 CreateParam(\"mas_1001011001\") = {(ok ? "可用" : "不可用(null)")}");
            if (!ok && string.IsNullOrEmpty(_status))
                _status = "主数据未装载:此时播放剧情会失败(详见日志 [探针])";
        }
        catch (Exception e)
        {
            Plugin.Logger?.LogWarning($"[探针] CreateParam 异常: {e.GetType().Name}: {e.Message}");
        }

        // 资源系统自举:游戏启动流程没走到资源初始化时,由插件补上,
        // 否则播放剧情会在加载 bundle 时报「アセットの読み込みに失敗しました」。
        AssetBootstrap.Want("打开剧情列表");
        if (!AssetBootstrap.Done && string.IsNullOrEmpty(_status))
            _status = AssetBootstrap.StatusText();
    }

    private void Update()
    {
        InputGuard.Tick();

        if (Input.GetKeyDown(ToggleKey()))
        {
            bool willOpen = !InputGuard.IsOpen;
            Toggle();
            if (willOpen)
                ProbeMasterDataOnce();
        }

        // 剧情中「跳到本段结尾」热键:列表关着时直接调用游戏自身的跳过执行
        // (与跳过按钮确认后同一条路径,但绕开按钮可用性判断与确认弹窗;
        //  第 2/3 段按钮失效时用它兜底)。
        if (!_open && Input.GetKeyDown(SkipKey()))
            TriggerSkip();

        _composing = CompositionText();
        if (_open)
        {
            if (Input.GetKeyDown(KeyCode.Escape))
            {
                if (_searchFocused)
                    _searchFocused = false;
                else
                    Close("Esc");
            }

            // 先吃掉本帧的字符输入:输入法提交的汉字同样经由 inputString 送达
            _searchTextThisFrame = false;
            HandleSearchTyping();

            if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter))
            {
                // 搜索框聚焦时回车属于输入法(确认候选)/结束输入,不触发播放:
                // 正在拼字、或本帧刚提交了文字时都不结束输入。
                if (_searchFocused)
                {
                    if (string.IsNullOrEmpty(_composing) && !_searchTextThisFrame)
                        _searchFocused = false;
                }
                else
                {
                    PlaySelected();
                }
            }
            if (!_searchFocused)
            {
                if (Input.GetKeyDown(KeyCode.RightArrow))
                    MoveSelection(1, 0);
                else if (Input.GetKeyDown(KeyCode.LeftArrow))
                    MoveSelection(-1, 0);
                else if (Input.GetKeyDown(KeyCode.DownArrow))
                    MoveSelection(0, 1);
                else if (Input.GetKeyDown(KeyCode.UpArrow))
                    MoveSelection(0, -1);
            }
            ScrollByKeys();
            AdvanceScroll();
        }

        SetIme(_open && _searchFocused, force: false);
        ResolveCompositionEnd();

        // 资源系统自举:每帧推进(离线档补上游戏没走到的 catalog 注册)
        AssetBootstrap.Tick();
        if (_open && !_bootstrapNotified && AssetBootstrap.Done)
        {
            _bootstrapNotified = true;
            _status = "资源系统就绪,可以播放";
        }

        // 场景切换看门狗(0.7.21): ChangeSceneAsync 15s 后若仍不在剧情场景则写日志。
        if (NovelPlayer.WatchdogPending && Time.realtimeSinceStartup >= NovelPlayer.WatchdogDeadline)
        {
            string pending = NovelPlayer.WatchdogNovelId;
            NovelPlayer.ClearWatchdog();
            if (FindLiveTopScene() == null)
                Plugin.Logger.LogError($"[场景看门狗] {pending} 发起切换后 15s 未进入剧情场景,疑似 Addressables/场景加载卡住");
        }

        // 离线模式:定期输出资产管线快照(定位资源加载卡点;DiagAssets 关闭时为空操作)
        if (Plugin.OfflineApi.Value && Time.unscaledTime >= _nextAssetDiag)
        {
            _nextAssetDiag = Time.unscaledTime + 10f;
            AssetDiag.Snapshot("定时");
        }

        if (Time.unscaledTime < _nextSceneCheck)
            return;
        _nextSceneCheck = Time.unscaledTime + 0.5f;

        string scene = ActiveSceneName();
        if (scene == _lastScene)
            return;

        // 场景切换时收起窗口;进入 Home 时按配置自动打开
        _lastScene = scene;
        Plugin.Logger.LogInfo($"场景切换到: {scene}");
        AssetDiag.Snapshot($"场景 {scene}");
        AssetDiag.CaptureScreen($"scene-{scene}"); // 截图能力保留,受 DiagAssets 开关控制(默认关)
        if (_open)
            Close("场景切换");
        if (Plugin.AutoOpen.Value && scene == "Home")
            Open("进入 Home");
    }

    // ---------------------------------------------------------------- 输入法(自绘输入框必须自己开关 IME)

    /// <summary>
    /// 打开/关闭系统输入法。
    /// <para>
    /// 本构建的 <c>GUI.TextField</c> 是桩,搜索框是自绘的——没有 IMGUI 文本控件时
    /// Unity 不会替我们打开输入法,导致中日文根本输入不进来(只能打 ASCII)。
    /// 聚焦搜索框期间强制 <c>IMECompositionMode.On</c>,失焦/关窗恢复 Auto。
    /// </para>
    /// </summary>
    /// <param name="on">true 打开,false 收回 Auto。</param>
    /// <param name="force">true 时忽略状态缓存强制设置(销毁时用)。</param>
    private void SetIme(bool on, bool force)
    {
        if (!force && on == _imeOn)
            return;
        _imeOn = on;
        try
        {
            Input.imeCompositionMode = on ? IMECompositionMode.On : IMECompositionMode.Auto;
        }
        catch (Exception e)
        {
            if (!_imeWarned)
            {
                _imeWarned = true;
                Plugin.Logger?.LogWarning($"输入法开关设置失败(搜索框只能用英文输入): {e.GetType().Name}: {e.Message}");
            }
        }
    }

    /// <summary>取当前输入法组合串(未确定文本);不可用时返回空串。</summary>
    private string CompositionText()
    {
        if (!_open || !_searchFocused)
            return "";
        try
        {
            return Input.compositionString ?? "";
        }
        catch
        {
            return "";
        }
    }

    /// <summary>
    /// 拼字结束(组合串由非空变为空)时的兜底:某些 Unity 版本不把确认后的文字放进
    /// <c>Input.inputString</c>,只在组合串里给;这里把上一帧的组合串并入搜索词。
    /// <para>
    /// 两种正常路径都不会重复:<c>_searchTextThisFrame</c> 为 true(本帧已从 inputString
    /// 收到提交字符),或搜索词结尾已经就是这段文本(说明先前已提交)时直接跳过。
    /// </para>
    /// </summary>
    private void ResolveCompositionEnd()
    {
        string last = _lastComposing;
        _lastComposing = _composing;
        if (last.Length == 0 || _composing.Length > 0 || _searchTextThisFrame)
            return;
        if (!_open || !_searchFocused || _search.EndsWith(last, StringComparison.Ordinal))
            return;
        _search += last;
        _filterDirty = true;
    }

    // ---------------------------------------------------------------- 开关与输入

    /// <summary>切换窗口显示。</summary>
    private void Toggle()
    {
        if (_open)
            Close("快捷键/按钮");
        else
            Open("快捷键/按钮");
    }

    /// <summary>打开窗口并接管输入;搜索框自动获得焦点,可直接输入筛选。</summary>
    private void Open(string reason)
    {
        if (_open)
            return;
        _open = true;
        ApplyUiScale();
        _filterDirty = true;
        _searchFocused = true;
        InputGuard.Begin();
        _layoutLogged = false;
        Plugin.Logger.LogInfo($"剧情列表已打开({reason})");
    }

    /// <summary>关闭窗口;输入屏蔽延后到鼠标静止的干净帧才解除。</summary>
    private void Close(string reason)
    {
        if (!_open)
            return;
        _open = false;
        _searchFocused = false;
        InputGuard.End();
        Plugin.Logger.LogInfo($"剧情列表已关闭({reason})");
    }

    /// <summary>取配置的快捷键,解析失败时回退 F7。</summary>
    private static KeyCode ToggleKey() =>
        Enum.TryParse(Plugin.ToggleKey.Value, true, out KeyCode key) ? key : KeyCode.F7;

    /// <summary>取配置的「跳到本段结尾」热键,解析失败时回退 F8。</summary>
    private static KeyCode SkipKey() =>
        Enum.TryParse(Plugin.SkipKey.Value, true, out KeyCode key) ? key : KeyCode.F8;

    /// <summary>
    /// 跳到本段结尾(热键 General/SkipKey,默认 F8):直接调用游戏自身的跳过执行
    /// TopScene.OnSkipExec()——与点跳过按钮确认后走同一条路径,落点由
    /// SkipPointInjector 注入的跳过点决定(每段一个)。未进入剧情或调用失败时只记日志。
    /// </summary>
    private static void TriggerSkip()
    {
        try
        {
            Project.Novel.TopScene scene = FindLiveTopScene();
            if (scene == null)
            {
                Plugin.Logger.LogInfo($"[跳过] 按 {Plugin.SkipKey.Value}:当前不在剧情场景");
                return;
            }
            Plugin.Logger.LogInfo($"[跳过] 按 {Plugin.SkipKey.Value}:调用引擎跳过执行 OnSkipExec()");
            scene.OnSkipExec();
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"[跳过] 热键执行失败: {e.GetType().Name}: {e.Message}");
        }
    }

    /// <summary>
    /// 查找当前**存活**的剧情场景实例(不在剧情中时返回 null)。
    /// 用 Resources.FindObjectsOfTypeAll:它只返回仍存活的对象,天然排除已销毁场景,
    /// 因此不需要缓存引用,也没有悬垂指针风险;每次按键查一次,开销可忽略。
    /// </summary>
    private static Project.Novel.TopScene FindLiveTopScene()
    {
        var all = Resources.FindObjectsOfTypeAll(Il2CppType.Of<Project.Novel.TopScene>());
        if (all == null)
            return null;
        Project.Novel.TopScene fallback = null;
        foreach (var obj in all)
        {
            Project.Novel.TopScene scene = obj?.TryCast<Project.Novel.TopScene>();
            if (scene == null)
                continue;
            // 场景缓存里可能残留「已退出但未销毁」的实例:优先取仍在层级中激活的那个。
            try
            {
                if (scene.gameObject != null && scene.gameObject.activeInHierarchy)
                    return scene;
            }
            catch { /* 读不到游戏对象就退而取第一个非空实例 */ }
            fallback ??= scene;
        }
        return fallback;
    }

    /// <summary>取当前活动场景名;不可用时返回空串。</summary>
    private static string ActiveSceneName()
    {
        try
        {
            return SceneManager.GetActiveScene().name ?? "";
        }
        catch
        {
            return "";
        }
    }

    /// <summary>
    /// 自绘搜索框的键盘输入(本构建 GUI.TextField 是桩,不能用)。
    /// 输入法拼字期间不处理原始按键(预编辑文本由 compositionString 单独显示)。
    /// </summary>
    private void HandleSearchTyping()
    {
        if (!_searchFocused || !string.IsNullOrEmpty(_composing))
            return;

        string input = Input.inputString;
        if (string.IsNullOrEmpty(input))
            return;

        bool changed = false;
        foreach (char c in input)
        {
            if (c == '\b')
            {
                if (_search.Length > 0)
                {
                    _search = _search.Substring(0, _search.Length - 1);
                    changed = true;
                }
            }
            else if (c == '\n' || c == '\r')
            {
                // 回车统一在 Update 里处理(要区分「输入法确认」与「结束输入」)
            }
            else if (!char.IsControl(c))
            {
                _search += c;
                changed = true;
                _searchTextThisFrame = true;
            }
        }
        if (changed)
            _filterDirty = true;
    }

    /// <summary>翻页键/首尾键滚动列表(鼠标滚轮之外的补充操作)。</summary>
    private void ScrollByKeys()
    {
        if (_searchFocused)
            return;
        float page = Mathf.Max(60f, _gridRect.height - CardH - CardGap);
        if (Input.GetKeyDown(KeyCode.PageDown))
            SetScroll(_scrollTarget + page);
        else if (Input.GetKeyDown(KeyCode.PageUp))
            SetScroll(_scrollTarget - page);
        else if (Input.GetKeyDown(KeyCode.Home))
            SetScroll(0f);
        else if (Input.GetKeyDown(KeyCode.End))
            SetScroll(float.MaxValue);
    }

    /// <summary>
    /// 键盘移动选中项:左右 = 相邻卡片,上下 = 相邻网格行(尽量保持列号)。
    /// </summary>
    /// <param name="dx">水平方向(-1/0/1)。</param>
    /// <param name="dy">垂直方向(-1/0/1)。</param>
    private void MoveSelection(int dx, int dy)
    {
        if (_cells.Count == 0)
            return;
        int idx = _selCell;
        if (idx < 0 || idx >= _cells.Count)
        {
            idx = 0;
        }
        else if (dx != 0)
        {
            idx = Mathf.Clamp(idx + dx, 0, _cells.Count - 1);
        }
        else if (dy != 0)
        {
            Cell cur = _cells[idx];
            int targetRow = cur.Row + dy;
            int best = -1;
            for (int i = 0; i < _cells.Count; i++)
            {
                Cell c = _cells[i];
                if (c.Row != targetRow)
                    continue;
                if (c.Col == cur.Col)
                {
                    best = i;
                    break;
                }
                // 目标行没有同列卡片时:向下取该行最左、向上取该行最右
                if (dy > 0 && c.Col >= cur.Col && (best < 0 || c.Col < _cells[best].Col))
                    best = i;
                else if (dy < 0 && c.Col <= cur.Col && (best < 0 || c.Col > _cells[best].Col))
                    best = i;
            }
            if (best < 0)
                return;
            idx = best;
        }

        _selCell = idx;
        _selectedKey = _cells[idx].Entry.k;
        EnsureSelectedVisible();
    }

    /// <summary>把当前选中卡片滚入可视区。</summary>
    private void EnsureSelectedVisible()
    {
        if (_selCell < 0 || _selCell >= _cells.Count)
            return;
        int row = _cells[_selCell].Row;
        if (row < 0 || row >= _rowTops.Count)
            return;
        float top = _rowTops[row];
        float bottom = top + _rows[row].Height;
        // 用目标值(而非显示值)判断:连续按键时不会因动画未到位而反复追加滚动。
        if (top < _scrollTarget)
            SetScroll(top);
        else if (bottom > _scrollTarget + _gridRect.height)
            SetScroll(bottom - _gridRect.height);
    }

    /// <summary>设置滚动目标位置(自动夹紧到内容范围);显示位置由 AdvanceScroll 平滑推进。</summary>
    private void SetScroll(float value)
    {
        float max = Mathf.Max(0f, _contentH - _gridRect.height);
        _scrollTarget = Mathf.Clamp(value, 0f, max);
    }

    /// <summary>
    /// 把滚动显示位置平滑推进到目标值(在 Update 里每帧调用一次)。
    /// 用帧率无关的指数趋近 1-e^(-rate·dt),到位后直接对齐避免长尾;
    /// 目标越界(内容/窗口变化)时先夹紧。
    /// </summary>
    private void AdvanceScroll()
    {
        float max = Mathf.Max(0f, _contentH - _gridRect.height);
        _scrollTarget = Mathf.Clamp(_scrollTarget, 0f, max);
        if (Mathf.Abs(_scrollTarget - _scrollY) <= 0.5f)
        {
            _scrollY = _scrollTarget;
            return;
        }
        float k = 1f - Mathf.Exp(-ScrollSmoothRate * Time.unscaledDeltaTime);
        _scrollY = Mathf.Lerp(_scrollY, _scrollTarget, k);
    }

    // ---------------------------------------------------------------- 播放

    /// <summary>播放当前选中项。</summary>
    private void PlaySelected()
    {
        if (_selCell < 0 || _selCell >= _cells.Count)
            return;
        Play(_cells[_selCell].Entry);
    }

    /// <summary>播放剧情;成功时收起窗口交由游戏演出。</summary>
    private void Play(StoryEntry e)
    {
        string error = NovelPlayer.Play(e.k, Plugin.SkipR18.Value);
        if (error == null)
        {
            _status = $"正在播放: {e.k}";
            Close("开始播放");
        }
        else
        {
            _status = $"播放失败: {error}";
        }
    }

    /// <summary>
    /// 详情栏「分段」步进器:选中同一故事的第 part 段(若该段被「显示续篇」过滤掉,
    /// 自动打开续篇显示再定位)。
    /// </summary>
    private void SelectPart(int part)
    {
        if (_selCell < 0 || _selCell >= _cells.Count)
            return;
        List<StoryEntry> siblings = _db.Siblings(_cells[_selCell].Entry);
        if (siblings == null)
            return;
        StoryEntry target = null;
        foreach (var s in siblings)
        {
            if (s.part == part)
            {
                target = s;
                break;
            }
        }
        if (target == null)
            return;

        if (!_showParts)
        {
            _showParts = true;
            _filterDirty = true;
        }
        _selectedKey = target.k;
        _filterDirty = true; // 重建后按 key 找回选中项
    }

    // ---------------------------------------------------------------- 字体

    /// <summary>候选字体:标题用宋体族,正文用黑体族,key 用等宽(都以雅黑兜底,保证 CJK 可用)。</summary>
    private static readonly string[] SerifCandidates =
        { "Noto Serif SC", "Source Han Serif SC", "思源宋体", "Yu Mincho", "MS PMincho", "SimSun", "Microsoft YaHei UI" };

    private static readonly string[] SansCandidates =
        { "Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Yu Gothic UI", "Meiryo", "Arial" };

    private static readonly string[] MonoCandidates =
        { "Cascadia Mono", "Consolas", "Courier New", "Microsoft YaHei UI" };

    /// <summary>
    /// 准备界面字体。0.7.13 实测结论(诊断条截图对照,见 BepInEx\plugins\StoryViewer\shots):
    /// 本构建里用 <c>il2cpp_object_new</c> + <c>Font.Internal_CreateDynamicFont</c> 自建的
    /// OS 动态字体**渲染是坏的**——用它画的每个标签都显示上一帧最后生成的那串文本
    /// (整页文字变成同一串样式串),而 Unity 内置字体(LegacyRuntime)渲染完全正常。
    /// 因此:内置字体(有 CJK 时)优先;它没有 CJK 字形时用游戏自带字体资产;
    /// 都没有才退回自建 OS 字体(聊胜于无)。字体只准备一次,失败不刷日志。
    /// </summary>
    private void EnsureFonts()
    {
        if (_fontAttempted)
            return;
        _fontAttempted = true;

        // 先记下游戏原始皮肤字体,便于对照「自建字体 vs 皮肤字体」的渲染差异。
        try { _origSkinFont = GUI.skin.font; } catch { _origSkinFont = null; }

        Font builtin = TryLoadBuiltinFont();
        Font asset = TryFindAssetFont();

        bool builtinCjk = HasCjk(builtin);
        if (builtin != null && builtinCjk)
            _fSans = builtin;
        else if (asset != null)
            _fSans = asset;
        else
            _fSans = builtin ?? TryCreateNativeFont(SansCandidates);

        // 标题/等宽一律跟随正文字体:自建宋体/等宽族同样渲染失败,不再混用字体。
        _fSerif = _fSans;
        _fMono = _fSans;

        if (_fSans != null)
        {
            GUI.skin.font = _fSans;
            Plugin.Logger.LogInfo(
                $"界面字体已就绪: {_fSans.name}(CJK={HasCjk(_fSans)},内置CJK={builtinCjk}," +
                $"资产候选={asset?.name ?? "无"},标题/等宽同族)");
            LogFontInfo("正文", _fSans);
            LogFontInfo("内置", builtin);
            LogFontInfo("原皮肤", _origSkinFont);
        }
        else
        {
            Plugin.Logger.LogWarning("未能加载界面字体:列表中的中日文可能显示为方块(功能不受影响)。");
        }
    }

    /// <summary>字体是否覆盖常用中日文(对动态字体,HasCharacter 查的是系统字体链)。</summary>
    private static bool HasCjk(Font font)
    {
        if (font == null)
            return false;
        try { return font.HasCharacter('中'); } catch { return false; }
    }

    /// <summary>
    /// 在已加载的字体资产里找一个能出中日文的(排除内置 LegacyRuntime)。
    /// 这类资产是游戏自己导入的,渲染路径与内置字体相同,比自建动态字体可靠;
    /// 找不到返回 null,枚举失败只记一条警告。
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static Font TryFindAssetFont()
    {
        try
        {
            var all = Resources.FindObjectsOfTypeAll(Il2CppType.Of<Font>());
            if (all == null)
                return null;
            foreach (var obj in all)
            {
                Font font = obj?.TryCast<Font>();
                if (font == null)
                    continue;
                try
                {
                    string name = font.name ?? "";
                    if (name.Length == 0 || name == "LegacyRuntime")
                        continue;
                    if (!font.HasCharacter('中'))
                        continue;
                    Plugin.Logger?.LogInfo($"[字体] 找到可用字体资产: {name}(dynamic={font.dynamic})");
                    return font;
                }
                catch { /* 单个资产的属性读取失败不影响其它候选 */ }
            }
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"枚举字体资产失败: {e.GetType().Name}: {e.Message}");
        }
        return null;
    }

    /// <summary>记录字体的材质/着色器/贴图信息(排查文字异常时对照用;每次启动只写几行)。</summary>
    private static void LogFontInfo(string tag, Font font)
    {
        try
        {
            if (font == null)
            {
                Plugin.Logger?.LogInfo($"[字体诊断] {tag}: null");
                return;
            }
            string mat = "null", shader = "null", tex = "null", mcolor = "n/a";
            Material m = font.material;
            if (m != null)
            {
                mat = m.name;
                shader = m.shader != null ? m.shader.name : "null";
                Texture t = m.mainTexture;
                tex = t != null ? $"{t.name}({t.width}x{t.height})" : "null";
                mcolor = $"({m.color.r:F2},{m.color.g:F2},{m.color.b:F2},{m.color.a:F2})";
            }
            bool dyn = false, hasCjk = false;
            try { dyn = font.dynamic; } catch { }
            try { hasCjk = font.HasCharacter('中'); } catch { }
            Plugin.Logger?.LogInfo(
                $"[字体诊断] {tag}: name={font.name} 材质={mat} 着色器={shader} 贴图={tex} 材质色={mcolor} " +
                $"dynamic={dyn} CJK={hasCjk} fontSize={font.fontSize}");
        }
        catch (Exception e)
        {
            Plugin.Logger?.LogInfo($"[字体诊断] {tag}: 读取失败 {e.GetType().Name}: {e.Message}");
        }
    }

    /// <summary>
    /// 通过 il2cpp 原生入口创建动态字体;任何失败返回 null(已记录日志)。
    /// NoInlining:避免 JIT 把本方法内联进 OnGUI,导致异常逃出 OnGUI 的 try 范围。
    /// </summary>
    /// <param name="candidates">候选系统字体名(按优先级)。</param>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static Font TryCreateNativeFont(string[] candidates)
    {
        try
        {
            IntPtr pointer = IL2CPP.il2cpp_object_new(Il2CppClassPointerStore<Font>.NativeClassPtr);
            if (pointer == IntPtr.Zero)
                return null;
            var font = new Font(pointer);
            Font.Internal_CreateDynamicFont(font, candidates, 15);
            // 与旧版一致:动态字体必须标记「不随场景卸载」,否则切场景后字体资源可能被回收,
            // 样式引用到失效字体(旧版有此行,重写时遗漏)。
            font.hideFlags = HideFlags.HideAndDontSave;
            return font;
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"原生动态字体创建失败({candidates[0]}): {e.GetType().Name}: {e.Message}");
            return null;
        }
    }

    /// <summary>
    /// 取 Unity 内置字体(唯一实测渲染正常的一路);CJK 字形由系统字体链兜底
    /// (HasCharacter('中') 为 true),启动日志里会记录实际结果。
    /// </summary>
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static Font TryLoadBuiltinFont()
    {
        try
        {
            return Resources.GetBuiltinResource(Il2CppType.Of<Font>(), "LegacyRuntime.ttf")?.TryCast<Font>();
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"内置字体加载失败: {e.GetType().Name}: {e.Message}");
            return null;
        }
    }

    // ---------------------------------------------------------------- 绘制入口

    private void OnGUI()
    {
        if (!_open)
            return;

        EnsureFonts();
        Safe("样式", EnsureStyles);
        // 0.7.27:每帧按当前屏幕尺寸校正缩放(尺寸没变时内部直接返回),使面板随窗口变化自适应。
        Safe("缩放", ApplyUiScale);
        Safe("布局", ComputeLayout);

        Safe("遮罩", () => UiKit.Fill(new Rect(0f, 0f, Screen.width, Screen.height),
            new Color(0.02f, 0.017f, 0.015f, 0.66f)));
        Safe("窗框", DrawWindowFrame);
        Safe("顶栏", DrawTopBar);
        Safe("竖栏", DrawRail);
        Safe("网格", DrawGrid);
        Safe("详情", DrawDetail);
        Safe("页脚", DrawFooter);

        // 诊断(0.7.11):首次打开时把关键布局矩形写进日志,便于对照截图定位元素位置。
        if (!_layoutLogged)
        {
            _layoutLogged = true;
            Plugin.Logger?.LogInfo(
                $"[布局] 窗口=({_winRect.x:F0},{_winRect.y:F0},{_winRect.width:F0},{_winRect.height:F0}) " +
                $"顶栏=({_topRect.x:F0},{_topRect.y:F0},{_topRect.width:F0},{_topRect.height:F0}) " +
                $"网格=({_gridRect.x:F0},{_gridRect.y:F0},{_gridRect.width:F0},{_gridRect.height:F0}) " +
                $"详情=({_detailRect.x:F0},{_detailRect.y:F0},{_detailRect.width:F0},{_detailRect.height:F0}) " +
                $"大图=({_bigRect.x:F0},{_bigRect.y:F0},{_bigRect.width:F0},{_bigRect.height:F0}) " +
                $"播放=({_playRect.x:F0},{_playRect.y:F0},{_playRect.width:F0},{_playRect.height:F0}) " +
                $"搜索=({_searchRect.x:F0},{_searchRect.y:F0},{_searchRect.width:F0},{_searchRect.height:F0})");
        }
    }

    /// <summary>按区域隔离绘制异常:同名区域只记录一次错误,其余区域照常绘制。</summary>
    private void Safe(string section, Action draw)
    {
        try
        {
            draw();
        }
        catch (Exception e)
        {
            if (_sectionErrors.Add(section))
                Plugin.Logger.LogError($"绘制[{section}]失败: {e.GetType().Name}: {e.Message}");
        }
    }

    /// <summary>
    /// 创建自定义文本样式(GUI.skin 只在 OnGUI 内可用,故延迟到首次绘制)。
    /// 注意:interop 的 GUIStyle 没有拷贝构造函数,只能 new 出来再逐个属性设置,
    /// 且必须显式带上字体(否则退回内置字体,中日文变方块)。
    /// 所有样式文字色都用白色,实际颜色由 <see cref="Text"/> 通过 GUI.contentColor 相乘给出。
    /// </summary>
    private void EnsureStyles()
    {
        if (_stylesReady)
            return;
        _stylesReady = true;
        try
        {
            // 字号按屏幕整体缩放(0.7.13):数值是 1080p 设计基准,由 S() 换算。
            _stTopTitle = MakeStyle(S(18), bold: true, wrap: false, font: _fSerif);
            _stDetailTitle = MakeStyle(S(21), bold: true, wrap: true, font: _fSerif);
            _stGroup = MakeStyle(S(14), bold: true, wrap: false, font: _fSerif);
            _stCardTitle = MakeStyle(S(13), bold: false, wrap: false, font: _fSans);
            _stMeta = MakeStyle(S(11), bold: false, wrap: false, font: _fSans);
            _stSmall = MakeStyle(S(12), bold: false, wrap: false, font: _fSans);
            // 简介是多行长文本,必须换行(0.7.15);其余用到 _stBody 的文本都比各自矩形短,不受影响。
            _stBody = MakeStyle(BodySize, bold: false, wrap: true, font: _fSans);
            _stKey = MakeStyle(S(11), bold: false, wrap: false, font: _fMono);
            _stRail = MakeStyle(S(13), bold: false, wrap: false, font: _fSans);
            _stBlank = new GUIStyle();
        }
        catch (Exception e)
        {
            // 属性 setter 若被裁剪,退回皮肤默认样式:界面能看,只是没有字号层次。
            Plugin.Logger.LogWarning($"自定义样式创建失败,退回默认样式: {e.GetType().Name}: {e.Message}");
            _stTopTitle = _stDetailTitle = _stGroup = _stCardTitle = _stMeta = _stSmall = _stBody = GUI.skin.label;
            _stKey = _stRail = GUI.skin.label;
            _stBlank = new GUIStyle();
        }
    }

    /// <summary>构造一个白色可染色的文本样式。</summary>
    /// <param name="size">字号。</param>
    /// <param name="bold">是否加粗。</param>
    /// <param name="wrap">是否自动换行。</param>
    /// <param name="font">所用字体。</param>
    private static GUIStyle MakeStyle(int size, bool bold, bool wrap, Font font)
    {
        var st = new GUIStyle
        {
            font = font,
            fontSize = size,
            fontStyle = bold ? FontStyle.Bold : FontStyle.Normal,
            wordWrap = wrap,
            clipping = TextClipping.Clip,
        };
        st.normal.textColor = Color.white;
        return st;
    }

    // ---------------------------------------------------------------- 文本原语

    /// <summary>按指定颜色绘制文本(样式文字色为白,颜色由 contentColor 相乘给出)。</summary>
    private static void Text(Rect rect, string text, GUIStyle style, Color color)
    {
        if (string.IsNullOrEmpty(text))
            return;

        // 字号可能比调用方给的槽位高(整体缩放后尤其如此):放宽矩形高度,避免 CJK 下半被裁掉。
        try
        {
            if (style != null && rect.height < style.fontSize * 1.4f)
                rect.height = style.fontSize * 1.4f;
        }
        catch { /* 读不到字号就按原矩形绘制 */ }

        // 0.7.12 写法:实测在 Label 之前写 GUI.color 会让后续文字变黑,
        // 因此这里不碰 GUI.color/backgroundColor,只按老代码用 contentColor 相乘。
        // 0.7.13 定论(诊断条截图对照):文字异常的根源是自建 OS 动态字体本身渲染失效,
        // 现已统一改用内置字体,这条最小写法保持不变。
        var prev = GUI.contentColor;
        GUI.contentColor = color;
        GUI.Label(rect, text, style);
        GUI.contentColor = prev;
    }

    /// <summary>在矩形内水平居中绘制单行文本(垂直方向按字号粗对齐)。</summary>
    private static void CenterText(Rect rect, string text, GUIStyle style, int fontSize, Color color)
    {
        if (string.IsNullOrEmpty(text))
            return;
        float w = Mathf.Min(TextWidth(style, text, fontSize), rect.width);
        float x = rect.x + Mathf.Max(0f, (rect.width - w) * 0.5f);
        float y = rect.y + Mathf.Max(0f, (rect.height - fontSize * 1.3f) * 0.5f);
        Text(new Rect(x, y, w + 2f, rect.height), text, style, color);
    }

    /// <summary>右对齐绘制单行文本。</summary>
    private static void RightText(Rect rect, string text, GUIStyle style, int fontSize, Color color)
    {
        if (string.IsNullOrEmpty(text))
            return;
        float w = Mathf.Min(TextWidth(style, text, fontSize), rect.width);
        Text(new Rect(rect.xMax - w, rect.y, w + 2f, rect.height), text, style, color);
    }

    /// <summary>计算文本像素宽度(CalcSize 被裁剪时按字符类型估算:全角≈字号,ASCII≈0.55 字号)。</summary>
    private static float TextWidth(GUIStyle style, string text, int fontSize)
    {
        if (string.IsNullOrEmpty(text))
            return 0f;
        try
        {
            return style.CalcSize(GUIContent.Temp(text)).x;
        }
        catch
        {
            float w = 0f;
            foreach (char c in text)
                w += c > 0x2E80 ? fontSize : fontSize * 0.55f;
            return w;
        }
    }

    /// <summary>
    /// 无皮肤背景的点击热区:视觉由调用方自绘,这里只取 IMGUI 的点击语义
    /// (hotControl / MouseDown+MouseUp 配对),避免默认皮肤把控件画成灰圆角按钮。
    /// </summary>
    private bool Clickable(Rect rect) => GUI.Button(rect, "", _stBlank);

    // ---------------------------------------------------------------- 布局

    /// <summary>
    /// 计算界面整体缩放并换算全部布局数值,只在首次打开窗口时执行一次。
    /// 手动值(General/UiScale > 0)直接采用;自动值取「屏幕高 85% / 宽 93%」的小者,
    /// 让 1080×700 的设计窗口尽量铺满又不出屏;小屏保持 1×(不缩小,防止元素重叠)。
    /// </summary>
    private void ApplyUiScale()
    {
        int screenW = Screen.width;
        int screenH = Screen.height;
        // 已应用过且屏幕尺寸没变 → 直接返回;尺寸变了(窗口放大/切全屏)则重算,让面板跟着走。
        if (_scaleApplied && screenW == _lastScreenW && screenH == _lastScreenH)
            return;
        _scaleApplied = true;
        _lastScreenW = screenW;
        _lastScreenH = screenH;
        float manual = Plugin.UiScale.Value;
        _uiScale = manual > 0.01f
            ? Mathf.Clamp(manual, 0.5f, 4f)
            : Mathf.Clamp(
                Mathf.Min(screenH * 0.85f / 700f, screenW * 0.93f / 1080f),
                1f, 2.6f);

        WindowW = S(1080);
        WindowH = S(700);
        RailW = S(72);
        TopH = S(64);
        GridX = S(96);
        GridY = S(88);
        GridW = S(654);
        GridH = S(572);
        DetailW = S(306);
        DetailX = WindowW - DetailW;
        DetailPad = S(20);
        CardW = S(207);
        CardH = S(162);
        CardGap = S(16);
        CardPad = S(7);
        ThumbW = S(193);
        ThumbH = S(108);
        GroupH = S(30);
        GroupGap = S(8);
        SearchW = S(200);
        ControlH = S(30);
        CloseW = S(30);
        TogglePartsW = S(56);
        ToggleR18W = S(64);
        FooterH = S(30);
        BodySize = S(13);

        Plugin.Logger?.LogInfo(
            $"[界面] 缩放 {_uiScale:F2}× ({(manual > 0.01f ? "手动 UiScale" : "自动")}, " +
            $"屏幕 {Screen.width}x{Screen.height}) → 窗口 {WindowW}x{WindowH}");
    }

    /// <summary>计算窗口与各面板的绝对矩形,并重排竖栏条目。</summary>
    private void ComputeLayout()
    {
        _winRect = new Rect(
            Mathf.Round((Screen.width - WindowW) / 2f),
            Mathf.Round((Screen.height - WindowH) / 2f),
            WindowW,
            WindowH);
        float x = _winRect.x;
        float y = _winRect.y;

        _railRect = new Rect(x, y, RailW, WindowH);
        _topRect = new Rect(x + RailW, y, WindowW - RailW, TopH);
        _gridRect = new Rect(x + GridX, y + GridY, GridW, GridH);
        _detailRect = new Rect(x + DetailX, y + TopH, DetailW, WindowH - TopH);
        _footerRect = new Rect(x + GridX, y + WindowH - FooterH + S(6), GridW, S(20));

        // 顶栏右侧:关闭 × | 搜索框 | 续篇 | 仅R18(互不重叠,避免点击互相吞掉)
        _closeRect = new Rect(x + WindowW - S(24) - CloseW, y + S(17), CloseW, ControlH);
        _searchRect = new Rect(_closeRect.x - S(12) - SearchW, y + S(17), SearchW, ControlH);
        _togglePartsRect = new Rect(_searchRect.x - S(12) - TogglePartsW, y + S(17), TogglePartsW, ControlH);
        _toggleR18Rect = new Rect(_togglePartsRect.x - S(10) - ToggleR18W, y + S(17), ToggleR18W, ControlH);

        // 详情栏内部
        int cx = (int)_detailRect.x + DetailPad;
        _bigRect = new Rect(cx, _detailRect.y + S(20), DetailW - DetailPad * 2, S(150));
        _playRect = new Rect(cx, _detailRect.yMax - S(24) - S(44), DetailW - DetailPad * 2, S(44));

        LayoutRail();
    }

    /// <summary>重排左侧系列竖栏(48×48 方块,自顶向下)。</summary>
    private void LayoutRail()
    {
        _rail.Clear();
        int box = S(48);
        float x = _winRect.x + (RailW - box) / 2f;
        float y = _winRect.y + S(100);
        _rail.Add(new RailItem { Rect = new Rect(x, y, box, box), Key = "all", Label = "全部" });
        y += S(58);
        foreach (var s in _db.Series)
        {
            string label = string.IsNullOrEmpty(s.label) ? "其他" : s.label;
            if (label.Length > 4)
                label = label.Substring(0, 4);
            _rail.Add(new RailItem { Rect = new Rect(x, y, box, box), Key = s.key, Label = label });
            y += S(58);
        }
    }

    // ---------------------------------------------------------------- 窗框与顶栏

    /// <summary>窗口底板(圆角 + 1px 描边)。</summary>
    private void DrawWindowFrame()
    {
        UiKit.Panel(_winRect, 10f, ColWindow, ColWindowBorder);
    }

    /// <summary>顶栏:当前分组标题、条目数/状态、R18 与续篇开关、自绘搜索框、关闭按钮。</summary>
    private void DrawTopBar()
    {
        // 顶栏比正文略亮,向下淡出,做出「工具条」层次
        UiKit.Gradient(_topRect, new Color(0.102f, 0.090f, 0.082f, 1f), ColWindow, 4);

        StoryEntry sel = SelectedEntry();
        string title;
        string count;
        if (sel != null)
        {
            string group = sel.SortGroup;
            title = string.IsNullOrEmpty(group) ? SeriesTag(sel.s) : group;
            int groupCount = GroupCountOf(_selCell);
            count = $"{groupCount} 条";
        }
        else
        {
            title = string.IsNullOrEmpty(_search) ? SeriesTitle() : $"搜索结果";
            count = $"{_filtered.Count} 条";
        }
        Text(new Rect(_topRect.x + S(24), _topRect.y + S(12), S(560), S(26)), title, _stTopTitle, ColCream);
        float tw = Mathf.Min(TextWidth(_stTopTitle, title, S(18)), S(540));
        Text(new Rect(_topRect.x + S(24) + tw + S(12), _topRect.y + S(20), S(120), S(16)), count, _stMeta, ColMuted);

        // 第二行:状态提示;没提示时显示候选统计
        string subtitle = string.IsNullOrEmpty(_status)
            ? $"共 {_db.Entries.Count} 条 · 当前 {_filtered.Count} 条"
            : _status;
        Color subColor = _status.StartsWith("播放失败", StringComparison.Ordinal) ? ColAmberLight : ColFaint;
        Text(new Rect(_topRect.x + S(24), _topRect.y + S(40), S(560), S(16)), subtitle, _stMeta, subColor);

        if (TogglePill(_toggleR18Rect, "仅 R18", _onlyR18))
        {
            _onlyR18 = !_onlyR18;
            _filterDirty = true;
        }
        if (TogglePill(_togglePartsRect, "续篇", _showParts))
        {
            _showParts = !_showParts;
            _filterDirty = true;
        }

        DrawSearchBox();
        DrawCloseButton();
    }

    /// <summary>小开关(琥珀描边胶囊);返回 true 表示本帧被点击。</summary>
    private bool TogglePill(Rect rect, string label, bool on)
    {
        bool hover = Event.current != null && rect.Contains(Event.current.mousePosition);
        if (on)
            UiKit.Panel(rect, 8f, ColAmberBg, ColAmber);
        else
            UiKit.Panel(rect, 8f, hover ? ColCard : ColField, ColFieldBorder);
        CenterText(rect, label, _stSmall, S(12), on ? ColAmberLight : ColMuted);
        return Clickable(rect);
    }

    /// <summary>右上角关闭按钮(hover 显示琥珀底)。</summary>
    private void DrawCloseButton()
    {
        bool hover = Event.current != null && _closeRect.Contains(Event.current.mousePosition);
        if (hover)
            UiKit.Panel(_closeRect, 8f, ColAmberBg, ColAmber);
        CenterText(_closeRect, "×", _stTopTitle, S(17), hover ? ColAmberLight : ColMuted);
        if (Clickable(_closeRect))
            Close("按钮");
    }

    /// <summary>
    /// 自绘搜索框(本构建 GUI.TextField 是桩,改由 Input.inputString 采集;
    /// 输入法组合串单独用琥珀色画,并把它接到输入法候选框位置)。
    /// </summary>
    private void DrawSearchBox()
    {
        var ev = Event.current;
        if (ev != null && ev.type == EventType.MouseDown && ev.button == 0)
        {
            bool inSearch = _searchRect.Contains(ev.mousePosition);
            bool inClose = _closeRect.Contains(ev.mousePosition);
            bool inToggle = _toggleR18Rect.Contains(ev.mousePosition) || _togglePartsRect.Contains(ev.mousePosition);
            if (inSearch)
            {
                _searchFocused = true;
                ev.Use();
            }
            else if (!inClose && !inToggle)
            {
                // 点别处即失焦;点关闭键/开关不在这里处理,交给它们自己吃事件
                _searchFocused = false;
            }
        }

        UiKit.Panel(_searchRect, 8f, _searchFocused ? ColCard : ColField,
            _searchFocused ? ColAmber : ColFieldBorder);

        float tx = _searchRect.x + S(12);
        float ty = _searchRect.y + S(6);
        float tw = _searchRect.width - S(24);

        if (string.IsNullOrEmpty(_search) && string.IsNullOrEmpty(_composing) && !_searchFocused)
        {
            Text(new Rect(tx, ty, tw, S(18)), "搜索 标题 / 角色 / 章节 / key", _stSmall, ColPlaceholder);
            return;
        }

        Text(new Rect(tx, ty, tw, S(18)), _search, _stSmall, ColCream);
        float used = Mathf.Min(TextWidth(_stSmall, _search, S(12)), tw);
        float compW = 0f;
        if (!string.IsNullOrEmpty(_composing))
        {
            compW = Mathf.Min(TextWidth(_stSmall, _composing, S(12)), tw - used);
            Text(new Rect(tx + used, ty, Mathf.Max(0f, compW), S(18)), _composing, _stSmall, ColAmberLight);
            // 未确定的预编辑文本画一条琥珀色下划线
            UiKit.Fill(new Rect(tx + used, ty + S(17), Mathf.Max(2f, compW), 1f), ColAmberLight);
        }

        float caretX = tx + Mathf.Min(used + compW, tw - 2f);
        if (_searchFocused && ((int)(Time.unscaledTime * 2f) & 1) == 0)
            UiKit.Fill(new Rect(caretX + 1f, ty + S(2), 1f, S(15)), ColCream);

        if (_searchFocused)
        {
            // 让输入法候选框贴着搜索框显示;坐标只影响候选框位置,失败不影响输入
            try
            {
                Input.compositionCursorPos = new Vector2(caretX, Screen.height - (_searchRect.y + 22f));
            }
            catch
            {
                // 忽略:候选框位置是纯粹的显示优化
            }
        }
    }

    // ---------------------------------------------------------------- 左侧竖栏

    /// <summary>左侧系列竖栏:48×48 方块,选中 = 琥珀实底,悬停 = 卡片底。</summary>
    private void DrawRail()
    {
        UiKit.Panel(_railRect, 10f, ColRail, ColRail);
        UiKit.Fill(new Rect(_railRect.xMax - 1f, _railRect.y, 1f, _railRect.height), ColLine);

        foreach (RailItem item in _rail)
        {
            bool on = _series == item.Key;
            bool hover = Event.current != null && item.Rect.Contains(Event.current.mousePosition);
            if (on)
                UiKit.Panel(item.Rect, 9f, ColAmber, ColAmber);
            else if (hover)
                UiKit.Panel(item.Rect, 9f, ColCard, ColCardBorder);

            Color textColor = on ? ColInk : hover ? ColCream : ColMuted;
            DrawRailLabel(item.Rect, item.Label, textColor);

            if (Clickable(item.Rect) && !on)
                SetSeries(item.Key);
        }
    }

    /// <summary>竖栏文字:2 字一行(4 字标签排成两行),整体居中。</summary>
    private void DrawRailLabel(Rect rect, string label, Color color)
    {
        if (label.Length <= 2)
        {
            CenterText(rect, label, _stRail, S(13), color);
            return;
        }
        string first = label.Substring(0, 2);
        string second = label.Substring(2);
        CenterText(new Rect(rect.x, rect.y + S(8), rect.width, S(16)), first, _stRail, S(13), color);
        CenterText(new Rect(rect.x, rect.y + S(25), rect.width, S(16)), second, _stRail, S(13), color);
    }

    /// <summary>切换系列筛选(相同值时不重建列表)。</summary>
    private void SetSeries(string key)
    {
        if (_series == key)
            return;
        _series = key;
        _filterDirty = true;
    }

    // ---------------------------------------------------------------- 卡片网格

    /// <summary>
    /// 卡片网格:分组标题行 + 3 列卡片;GUI.BeginGroup 裁剪 + 自绘滚动
    /// (避免使用被裁成桩的 GUI.BeginScrollView / GUI.Scroller)。
    /// </summary>
    private void DrawGrid()
    {
        if (_filterDirty)
            RebuildFilter();

        _hoverCell = -1;
        if (_cells.Count == 0)
        {
            Text(new Rect(_gridRect.x, _gridRect.y + S(20), _gridRect.width, S(20)),
                string.IsNullOrEmpty(_db.Error) ? "没有匹配的剧情" : _db.Error, _stBody, ColMuted);
            return;
        }

        HandleGridInput();
        _hoverCell = HoverCell();
        // 显示位置由 Update 的 AdvanceScroll 推进;这里按最新内容/窗口再夹紧一次(内容变化的兜底)。
        float scrollMax = Mathf.Max(0f, _contentH - _gridRect.height);
        _scrollTarget = Mathf.Clamp(_scrollTarget, 0f, scrollMax);
        _scrollY = Mathf.Clamp(_scrollY, 0f, scrollMax);

        int first = RowAt(_scrollY);
        GUI.BeginGroup(_gridRect);
        for (int r = first; r >= 0 && r < _rows.Count; r++)
        {
            float top = _rowTops[r] - _scrollY;
            if (top > _gridRect.height)
                break;
            Row row = _rows[r];
            if (row.Header)
                DrawGroupBand(row, top);
            else
                DrawCardRow(row, r, top);
        }
        GUI.EndGroup();

        DrawScrollBar();
    }

    /// <summary>分组标题带:琥珀竖条 + 宋体分组名 + 右侧条目数。</summary>
    private void DrawGroupBand(Row row, float top)
    {
        UiKit.Fill(new Rect(0f, top, GridW, GroupH), ColBand);
        UiKit.Fill(new Rect(0f, top, S(3), GroupH), ColAmber);
        Text(new Rect(S(14), top + S(5), GridW - S(120), S(20)), row.Text, _stGroup, ColCream);
        RightText(new Rect(GridW - S(104), top + S(7), S(92), S(18)), $"{row.Count} 条", _stMeta, S(11), ColMuted);
    }

    /// <summary>一行卡片(最多 3 张)。</summary>
    private void DrawCardRow(Row row, int rowIndex, float top)
    {
        for (int c = 0; c < row.Items.Length; c++)
        {
            StoryEntry e = row.Items[c];
            var rect = new Rect(c * (CardW + CardGap), top, CardW, CardH);
            bool selected = e.k == _selectedKey;
            bool hover = _hoverCell >= 0 && _hoverCell < _cells.Count
                         && _cells[_hoverCell].Row == rowIndex && _cells[_hoverCell].Col == c;
            DrawCard(rect, e, selected, hover);
        }
    }

    /// <summary>
    /// 单张卡片:圆角底 + 16:9 缩略图 + R18 角标 + 标题 + 元信息。
    /// 选中 = 琥珀描边 + 投影;悬停 = 亮一档描边。
    /// </summary>
    private void DrawCard(Rect rect, StoryEntry e, bool selected, bool hover)
    {
        UiKit.Panel(rect, 8f, hover ? new Color(0.149f, 0.133f, 0.118f, 1f) : ColCard,
            selected ? ColAmber : hover ? ColCardHover : ColCardBorder,
            pad: selected ? 10 : 0, shadowA: selected ? 0.40f : 0f);

        var thumb = new Rect(rect.x + CardPad, rect.y + CardPad, ThumbW, ThumbH);
        UiKit.Fill(thumb, ColPreviewBg);
        UiKit.Image(thumb, _previews?.Get(e.k));
        UiKit.Frame(thumb, ColCardBorder);

        if (e.r18)
        {
            var chip = new Rect(thumb.xMax - S(40), thumb.y + S(7), S(33), S(16));
            UiKit.Panel(chip, 4f, ColR18);
            CenterText(chip, "R18", _stMeta, S(10), ColR18Text);
        }

        string title = e.DisplayTitle;
        Text(new Rect(rect.x + CardPad + S(2), rect.y + CardPad + ThumbH + S(6), ThumbW - S(4), S(18)),
            title, _stCardTitle, ColCream);

        // 元信息:搜索时显示 key(便于对照),否则显示系列/角色 + 分段
        string meta;
        if (!string.IsNullOrEmpty(_search))
        {
            meta = e.k;
        }
        else
        {
            string chara = e.DisplayCharacter;
            meta = _series == "all" && !string.IsNullOrEmpty(e.s)
                ? string.IsNullOrEmpty(chara) ? SeriesTag(e.s) : $"{SeriesTag(e.s)} · {chara}"
                : chara;
        }
        if (e.parts > 1)
            meta = string.IsNullOrEmpty(meta) ? $"{e.part}/{e.parts}" : $"{meta} · {e.part}/{e.parts}";
        Text(new Rect(rect.x + CardPad + S(2), rect.y + CardPad + ThumbH + S(24), ThumbW - S(4), S(15)),
            meta, string.IsNullOrEmpty(_search) ? _stMeta : _stKey,
            string.IsNullOrEmpty(_search) ? ColMuted : ColFaint);
    }

    /// <summary>列表的滚轮与点击处理(单击选中,双击播放)。</summary>
    private void HandleGridInput()
    {
        var ev = Event.current;
        if (ev == null)
            return;

        if (ev.type == EventType.ScrollWheel && _gridRect.Contains(ev.mousePosition))
        {
            // 一格的步长 = 半行卡片(原为一整行,手感过冲);可用配置覆盖(设计像素)。
            // 快速连滚时事件可能带较大 delta:限制单次最多 2 格,避免"一下跳一屏"。
            float step = Plugin.ScrollStep.Value > 0.01f
                ? Plugin.ScrollStep.Value * _uiScale
                : (CardH + CardGap) * 0.5f;
            SetScroll(_scrollTarget + Mathf.Clamp(ev.delta.y, -2f, 2f) * step);
            ev.Use();
            return;
        }

        if (ev.type == EventType.MouseDown && ev.button == 0 && _gridRect.Contains(ev.mousePosition))
        {
            _searchFocused = false;
            int idx = CellAt(ev.mousePosition);
            if (idx >= 0)
            {
                bool same = idx == _selCell;
                if (same && Time.unscaledTime - _lastClickTime < 0.35f)
                {
                    Play(_cells[idx].Entry);
                }
                else
                {
                    _selCell = idx;
                    _selectedKey = _cells[idx].Entry.k;
                    _lastClickTime = Time.unscaledTime;
                }
                ev.Use();
            }
        }
    }

    /// <summary>本帧鼠标悬停的卡片下标(不在网格内或没命中卡片时 -1)。</summary>
    private int HoverCell()
    {
        var ev = Event.current;
        if (ev == null || !_gridRect.Contains(ev.mousePosition))
            return -1;
        return CellAt(ev.mousePosition);
    }

    /// <summary>屏幕坐标命中的卡片下标(逐行二分 + 列定位)。</summary>
    private int CellAt(Vector2 mouse)
    {
        float contentY = _scrollY + mouse.y - _gridRect.y;
        int row = RowAt(contentY);
        if (row < 0 || row >= _rows.Count || _rows[row].Header)
            return -1;
        float localY = contentY - _rowTops[row];
        if (localY > CardH)
            return -1;
        float localX = mouse.x - _gridRect.x;
        int col = (int)(localX / (CardW + CardGap));
        if (col < 0 || col >= _rows[row].Items.Length)
            return -1;
        if (localX - col * (CardW + CardGap) > CardW)
            return -1; // 卡右侧空隙
        for (int i = 0; i < _cells.Count; i++)
        {
            if (_cells[i].Row == row && _cells[i].Col == col)
                return i;
        }
        return -1;
    }

    /// <summary>按内容坐标 y 二分查找行号(空列表返回 -1)。</summary>
    private int RowAt(float contentY)
    {
        if (_rowTops.Count == 0)
            return -1;
        int lo = 0;
        int hi = _rowTops.Count - 1;
        while (lo < hi)
        {
            int mid = (lo + hi + 1) / 2;
            if (_rowTops[mid] <= contentY)
                lo = mid;
            else
                hi = mid - 1;
        }
        return lo;
    }

    /// <summary>右侧细滚动条(位置提示)。</summary>
    private void DrawScrollBar()
    {
        if (_contentH <= _gridRect.height)
            return;
        float trackH = _gridRect.height;
        float thumbH = Mathf.Max(S(28), trackH * _gridRect.height / _contentH);
        float t = _scrollY / Mathf.Max(1f, _contentH - _gridRect.height);
        UiKit.Panel(new Rect(_gridRect.xMax - S(3), _gridRect.y + (trackH - thumbH) * t, S(3), thumbH), 1.5f, ColAmber);
    }

    // ---------------------------------------------------------------- 右侧详情

    /// <summary>右栏:预览大图 + 标题/key/元信息 + 分段步进器 + 简介 + 播放按钮。</summary>
    private void DrawDetail()
    {
        UiKit.Panel(new Rect(_detailRect.x, _detailRect.y, _detailRect.width - 1f, _detailRect.height - 1f),
            9f, ColRail, ColLine);

        StoryEntry sel = SelectedEntry();

        // 预览大图(无图时纯色块)
        UiKit.Fill(_bigRect, ColPreviewBg);
        UiKit.Image(_bigRect, sel == null ? null : _previews?.Get(sel.k), ScaleMode.ScaleToFit);
        UiKit.Frame(_bigRect, ColCardBorder);
        if (sel == null)
        {
            CenterText(_bigRect, "从左侧选择一条剧情", _stBody, BodySize, ColMuted);
        }
        else if (sel.r18)
        {
            var chip = new Rect(_bigRect.xMax - S(47), _bigRect.y + S(8), S(39), S(19));
            UiKit.Panel(chip, 4f, ColR18);
            CenterText(chip, "R18", _stMeta, S(11), ColR18Text);
        }

        float x = _bigRect.x;
        float y = _bigRect.yMax + S(16);
        if (sel == null)
        {
            DrawDetailPlaceholder(x, y);
            return;
        }

        Text(new Rect(x, y, _bigRect.width, S(58)), sel.DisplayTitle, _stDetailTitle, ColCream);
        y += S(60);
        Text(new Rect(x, y, _bigRect.width, S(16)), $"key  {sel.k}", _stKey, ColFaint);
        y += S(22);

        // 元信息:系列 · 角色 · 分组(分组与标题不同时才显示)
        string chara = string.IsNullOrEmpty(sel.DisplayCharacter) ? "—" : sel.DisplayCharacter;
        string meta = $"{SeriesTag(sel.s)} · {chara}";
        string group = sel.SortGroup;
        if (!string.IsNullOrEmpty(group) && group != sel.DisplayTitle)
            meta += $" · {group}";
        Text(new Rect(x, y, _bigRect.width, S(18)), meta, _stSmall, ColSoft);
        y += S(26);

        // 分段步进器(仅多段故事)
        if (sel.parts > 1)
        {
            Text(new Rect(x, y + S(6), S(36), S(18)), "分段", _stMeta, ColMuted);
            var steps = _db.Siblings(sel);
            int count = steps?.Count ?? sel.parts;
            for (int i = 0; i < count && i < 5; i++)
            {
                var step = new Rect(x + S(40) + i * S(42), y, S(34), S(30));
                bool on = sel.part == (steps != null && i < steps.Count ? steps[i].part : i + 1);
                DrawStepButton(step, on, i + 1);
            }
            y += S(44);
        }

        // 简介占满中间剩余空间
        float descBottom = _playRect.y - S(12);
        if (descBottom - y > 24f && !string.IsNullOrEmpty(sel.dz))
            Text(new Rect(x, y, _bigRect.width, descBottom - y), sel.dz, _stBody, ColSoft);

        // 播放按钮(琥珀实底 + hover 提亮)
        bool hoverPlay = Event.current != null && _playRect.Contains(Event.current.mousePosition);
        UiKit.Panel(_playRect, 8f, hoverPlay ? ColAmberLight : ColAmber, ColAmber,
            pad: 10, shadowA: hoverPlay ? 0.45f : 0.30f);
        CenterText(_playRect, "播 放 剧 情", _stBody, S(14), ColInk);
        if (Clickable(_playRect))
            Play(sel);
    }

    /// <summary>分段按钮(选中 = 琥珀描边 + 琥珀底)。</summary>
    private void DrawStepButton(Rect rect, bool on, int number)
    {
        bool hover = Event.current != null && rect.Contains(Event.current.mousePosition);
        UiKit.Panel(rect, 7f, on ? ColAmberBg : hover ? ColCard : ColField, on ? ColAmber : ColFieldBorder);
        string label = number <= 3 ? new[] { "一", "二", "三" }[number - 1] : number.ToString();
        CenterText(rect, label, _stSmall, S(12), on ? ColAmberLight : ColSoft);
        if (Clickable(rect) && !on)
            SelectPart(number);
    }

    /// <summary>未选中时的占位说明:操作提示 + 各系列条目数。</summary>
    private void DrawDetailPlaceholder(float x, float y)
    {
        Text(new Rect(x, y + S(40), _bigRect.width, S(20)), "滚轮或 ↑↓ 浏览卡片,单击选中,双击或回车播放", _stSmall, ColMuted);
        y += S(80);
        foreach (var s in _db.Series)
        {
            string label = string.IsNullOrEmpty(s.label) ? "其他" : s.label;
            Text(new Rect(x, y, _bigRect.width - S(90), S(18)), label, _stSmall, ColMuted);
            RightText(new Rect(x, y, _bigRect.width, S(18)), $"{s.count} 条", _stMeta, S(11), ColFaint);
            y += S(20);
        }
    }

    // ---------------------------------------------------------------- 页脚

    /// <summary>页脚:统计 + 操作提示。</summary>
    private void DrawFooter()
    {
        Text(new Rect(_footerRect.x, _footerRect.y, S(320), S(18)),
            $"共 {_db.Entries.Count} 条 · 当前 {_filtered.Count} 条", _stMeta, ColFaint);
        RightText(new Rect(_footerRect.x, _footerRect.y, _footerRect.width, S(18)),
            "↑↓←→ 选择 · 回车播放 · PgUp/PgDn 翻页 · Esc 关闭", _stMeta, S(11), ColFaint);
    }

    // ---------------------------------------------------------------- 数据与行模型

    /// <summary>当前选中的条目(无选中时 null)。</summary>
    private StoryEntry SelectedEntry() =>
        _selCell >= 0 && _selCell < _cells.Count ? _cells[_selCell].Entry : null;

    /// <summary>选中项所在分组的条目数(无选中时 0)。</summary>
    private int GroupCountOf(int cellIndex)
    {
        if (cellIndex < 0 || cellIndex >= _cells.Count)
            return 0;
        int row = _cells[cellIndex].Row;
        for (int r = row; r >= 0; r--)
        {
            if (_rows[r].Header)
                return _rows[r].Count;
        }
        return _filtered.Count;
    }

    /// <summary>系列短名 → 界面标签(标签为空时显示「其他」)。</summary>
    private string SeriesTag(string key)
    {
        foreach (var s in _db.Series)
        {
            if (s.key == key)
                return string.IsNullOrEmpty(s.label) ? (string.IsNullOrEmpty(key) ? "其他" : key) : s.label;
        }
        return key ?? "";
    }

    /// <summary>当前系列筛选的显示名(全部 / 某系列标签)。</summary>
    private string SeriesTitle() =>
        string.IsNullOrEmpty(_series) || _series == "all" ? "全部剧情" : SeriesTag(_series);

    /// <summary>重建过滤结果与行模型,并尽量保持原选中项。</summary>
    private void RebuildFilter()
    {
        _filtered = _db.Filter(_series, _search, !_showParts, _onlyR18);
        _filterDirty = false;
        BuildRows();
        _scrollY = 0f;
        _scrollTarget = 0f;

        // 按 key 找回原选中项;找不到时选中第一张卡片
        _selCell = -1;
        for (int i = 0; i < _cells.Count; i++)
        {
            if (_cells[i].Entry.k == _selectedKey)
            {
                _selCell = i;
                break;
            }
        }
        if (_selCell < 0 && _cells.Count > 0)
        {
            _selCell = 0;
            _selectedKey = _cells[0].Entry.k;
        }
        EnsureSelectedVisible();
    }

    /// <summary>
    /// 把过滤结果摊平成「分组标题 + 卡片行」的行模型,并预计算每行顶部位置与
    /// 卡片坐标(索引文件已按系列 → 分组 → key 排好序,同一分组天然连续)。
    /// </summary>
    private void BuildRows()
    {
        _rows.Clear();
        _rowTops.Clear();
        _cells.Clear();

        string currentGroup = null;
        var batch = new List<StoryEntry>(CardsPerRow);

        for (int i = 0; i < _filtered.Count; i++)
        {
            StoryEntry e = _filtered[i];
            string group = e.SortGroup;
            bool newGroup = !string.IsNullOrEmpty(group) && group != currentGroup;

            // 一批收满、或要换分组时:先收掉当前这批卡片
            if (batch.Count > 0 && (newGroup || batch.Count == CardsPerRow))
            {
                _rows.Add(new Row { Items = batch.ToArray(), Height = CardH + CardGap });
                batch.Clear();
            }

            if (newGroup)
            {
                int count = 0;
                for (int j = i; j < _filtered.Count && _filtered[j].SortGroup == group; j++)
                    count++;
                _rows.Add(new Row
                {
                    Header = true,
                    Text = _series == "all" ? $"{group} · {SeriesTag(e.s)}" : group,
                    Count = count,
                    Height = GroupH + GroupGap,
                });
            }

            currentGroup = group;
            batch.Add(e);
        }
        if (batch.Count > 0)
            _rows.Add(new Row { Items = batch.ToArray(), Height = CardH + CardGap });

        float top = 0f;
        for (int r = 0; r < _rows.Count; r++)
        {
            _rowTops.Add(top);
            if (!_rows[r].Header)
            {
                for (int c = 0; c < _rows[r].Items.Length; c++)
                    _cells.Add(new Cell { Row = r, Col = c, Entry = _rows[r].Items[c] });
            }
            top += _rows[r].Height;
        }
        _contentH = top;
    }

    // (0.7.13)0.7.11 的文字机制诊断条(8 机制 × 4 字体)已在定性后移除,结论见 EnsureFonts:
    // 自建 OS 动态字体渲染失效(所有标签显示同一串文本),内置字体/LegacyRuntime 正常。
    // 需要复查时看 BepInEx\plugins\StoryViewer\shots 里的历史截图。

    // (诊断工具 DiagModeColor / DiagModeName / DiagBuiltinFont / DrawDiagLabel 已在 0.7.13 一并移除)

    // (DrawDiagLabel 已随诊断条移除,0.7.13)
}

// (0.7.13)TextDiag 文字绘制状态诊断类已随诊断条一并移除。

