using System;
using System.Collections.Generic;
using UnityEngine;

namespace StoryViewer;

/// <summary>
/// 界面自绘原语:圆角/描边/投影贴图全部在运行时程序化生成并缓存,
/// 再用 GUI.DrawTexture 平涂绘制。
/// <para>
/// 为什么不用 GUI 皮肤:本作的 Unity 6 IL2CPP 构建把一部分 IMGUI 方法裁成了桩
/// (见 ViewerBehaviour 的说明),默认皮肤的 box/button 是浅灰圆角贴图,染色后发灰发脏;
/// 因此界面统一改为「自己生成贴图 + 平涂」,视觉完全可控。
/// </para>
/// <para>
/// 容错:贴图生成或绘制任一环节不可用(极少数被裁剪的 API)时,自动退回纯色方角绘制,
/// 界面功能不受影响,只在日志里记一次警告。
/// </para>
/// </summary>
internal static class UiKit
{
    /// <summary>圆角面板贴图缓存;键含尺寸/圆角/颜色/投影参数,null 也缓存以避免重复尝试。</summary>
    private static readonly Dictionary<string, Texture2D> PanelCache = new();

    /// <summary>白纹理(纯色平涂用);曾取失败时为 null,后续直接走回退分支。</summary>
    private static Texture2D _white;
    private static bool _whiteTried;
    private static bool _panelFailed;
    private static bool _warned;
    private static bool _loggedFirstPanel;

    /// <summary>取 1×1 白纹理;不可用时返回 null(调用方回退 GUI.Box)。</summary>
    private static Texture2D White()
    {
        if (!_whiteTried)
        {
            _whiteTried = true;
            try
            {
                _white = Texture2D.whiteTexture;
            }
            catch (Exception e)
            {
                Warn($"白纹理不可用: {e.GetType().Name}: {e.Message}");
            }
        }
        return _white;
    }

    /// <summary>贴图相关失败只记一次,避免刷日志。</summary>
    private static void Warn(string message)
    {
        if (_warned)
            return;
        _warned = true;
        Plugin.Logger?.LogWarning($"自绘贴图不可用,改用纯色方角绘制: {message}");
    }

    /// <summary>纯色填充矩形(白纹理 + GUI.color)。</summary>
    internal static void Fill(Rect rect, Color color)
    {
        if (rect.width <= 0f || rect.height <= 0f)
            return;
        var prev = GUI.color;
        GUI.color = color;
        Texture2D tex = White();
        if (tex != null)
            GUI.DrawTexture(rect, tex, ScaleMode.StretchToFill, true);
        else
            GUI.Box(rect, "");
        GUI.color = prev;
    }

    /// <summary>1px 描边(画在矩形内侧)。</summary>
    internal static void Frame(Rect rect, Color color)
    {
        Fill(new Rect(rect.x, rect.y, rect.width, 1f), color);
        Fill(new Rect(rect.x, rect.yMax - 1f, rect.width, 1f), color);
        Fill(new Rect(rect.x, rect.y, 1f, rect.height), color);
        Fill(new Rect(rect.xMax - 1f, rect.y, 1f, rect.height), color);
    }

    /// <summary>竖直渐变(等宽条带近似,条数越多越平滑)。</summary>
    internal static void Gradient(Rect rect, Color top, Color bottom, int bands = 8)
    {
        bands = Mathf.Max(1, bands);
        float h = rect.height / bands;
        for (int i = 0; i < bands; i++)
        {
            float t = bands == 1 ? 0f : i / (float)(bands - 1);
            Fill(new Rect(rect.x, rect.y + i * h, rect.width, h + 0.5f), new Color(
                top.r + (bottom.r - top.r) * t,
                top.g + (bottom.g - top.g) * t,
                top.b + (bottom.b - top.b) * t,
                top.a + (bottom.a - top.a) * t));
        }
    }

    /// <summary>
    /// 圆角面板:填充 + 内侧 1px 描边,可选向外柔和投影。
    /// <para>
    /// fill/border 可带透明;border 传 alpha=0 表示不描边。
    /// pad&gt;0 且 shadowA&gt;0 时贴图会向外扩 pad 像素绘制投影,
    /// 调用方传入的 rect 是要显示的面板本体矩形(投影会自动画到外面)。
    /// </para>
    /// </summary>
    internal static void Panel(Rect rect, float radius, Color fill, Color border = default,
                               int pad = 0, float shadowA = 0f, float shadowBlur = 7f)
    {
        if (rect.width <= 0f || rect.height <= 0f)
            return;

        bool wantShadow = pad > 0 && shadowA > 0f;
        if (!_panelFailed && radius > 0.5f)
        {
            Texture2D tex = GetPanelTex(Mathf.RoundToInt(rect.width), Mathf.RoundToInt(rect.height),
                radius, fill, border, wantShadow ? pad : 0, wantShadow ? shadowA : 0f, shadowBlur);
            if (tex != null)
            {
                Rect draw = wantShadow
                    ? new Rect(rect.x - pad, rect.y - pad, rect.width + pad * 2f, rect.height + pad * 2f)
                    : rect;
                // 注意(0.7.11 诊断结论):此前在 DrawTexture 前写 GUI.color=白 做归位,实测反而
                // 让后续文字被画成黑色;贴图本身颜色已烘焙进纹理,不需要 GUI.color 参与。
                // 这里不再改 GUI.color,保持与 0.7.9 相同的最小写法。
                GUI.DrawTexture(draw, tex, ScaleMode.StretchToFill, true);
                return;
            }
        }

        // 回退:近似投影 + 方角填充/描边
        if (wantShadow)
            Fill(new Rect(rect.x - 2f, rect.y + 2f, rect.width + 4f, rect.height + 2f),
                new Color(0f, 0f, 0f, shadowA * 0.35f));
        if (border.a > 0f)
        {
            Fill(rect, border);
            Fill(new Rect(rect.x + 1f, rect.y + 1f, rect.width - 2f, rect.height - 2f), fill);
        }
        else
        {
            Fill(rect, fill);
        }
    }

    /// <summary>取(按需生成)圆角面板贴图;生成失败返回 null 并置 _panelFailed。</summary>
    private static Texture2D GetPanelTex(int w, int h, float radius, Color fill, Color border,
                                         int pad, float shadowA, float shadowBlur)
    {
        string key = w + "x" + h + "r" + radius.ToString("0.##") + "p" + pad
                     + "f" + ColorKey(fill) + "b" + ColorKey(border)
                     + "s" + shadowA.ToString("0.##") + "-" + shadowBlur.ToString("0.##");
        if (PanelCache.TryGetValue(key, out Texture2D cached)) return cached;

        Texture2D tex = null;
        try
        {
            tex = BuildPanel(w, h, radius, fill, border, pad, shadowA, shadowBlur);
            if (tex != null && !_loggedFirstPanel)
            {
                _loggedFirstPanel = true;
                Plugin.Logger?.LogInfo($"[界面] 自绘圆角贴图已生成(首个 {w}x{h}):圆角/描边/投影可用");
            }
        }
        catch (Exception e)
        {
            _panelFailed = true;
            Warn($"生成圆角贴图失败: {e.GetType().Name}: {e.Message}");
        }
        if (PanelCache.Count > 256)
            PanelCache.Clear();
        PanelCache[key] = tex;
        return tex;
    }

    /// <summary>颜色缓存键(只用到 0..1 的少量取值,四位小数足够区分)。</summary>
    private static string ColorKey(Color c) =>
        ((int)(c.r * 255f)) + "." + ((int)(c.g * 255f)) + "." + ((int)(c.b * 255f)) + "." + ((int)(c.a * 255f));

    /// <summary>
    /// 逐像素生成圆角矩形贴图:内部为填充色,边界向内有 1px 描边,
    /// 外部向外是二次衰减的黑色投影(d&nbsp;→&nbsp;shadowBlur 范围内)。
    /// 距离场:轴对齐圆角矩形的有符号距离,0.5px 羽化做边缘抗锯齿。
    /// </summary>
    private static Texture2D BuildPanel(int w, int h, float radius, Color fill, Color border,
                                        int pad, float shadowA, float shadowBlur)
    {
        int W = w + pad * 2;
        int H = h + pad * 2;
        float r = Mathf.Clamp(radius, 0f, Mathf.Min(w, h) * 0.5f);
        float halfW = w * 0.5f;
        float halfH = h * 0.5f;
        float cx = W * 0.5f;
        float cy = H * 0.5f;

        var px = new Color32[W * H];
        for (int y = 0; y < H; y++)
        {
            for (int x = 0; x < W; x++)
            {
                // 圆角矩形有符号距离场(标准公式):
                //   q = |p - 中心| - (半宽 - 圆角);d = length(max(q,0)) + min(max(q.x,q.y),0) - 圆角
                // 旧写法少了内区那项 - 圆角,导致内部区域边界收缩、四个圆角盘外露,
                // 圆角矩形被画成「内矩形 + 四个圆形凸包」(狗骨形)。此处必须用完整公式。
                float dx = Mathf.Abs(x + 0.5f - cx) - (halfW - r);
                float dy = Mathf.Abs(y + 0.5f - cy) - (halfH - r);
                float qx = Mathf.Max(dx, 0f);
                float qy = Mathf.Max(dy, 0f);
                float d = Mathf.Sqrt(qx * qx + qy * qy) + Mathf.Min(Mathf.Max(dx, dy), 0f) - r;

                Color c;
                if (d <= 0.5f)
                {
                    // 内部:距边界 1px 内的像素画描边色(有描边时)
                    c = border.a > 0f && d > -1f ? border : fill;
                    c.a *= Mathf.Clamp01(0.5f - d);
                }
                else if (shadowA > 0f && shadowBlur > 0f)
                {
                    float t = Mathf.Clamp01(1f - d / shadowBlur);
                    c = new Color(0f, 0f, 0f, shadowA * t * t);
                }
                else
                {
                    c = new Color(0f, 0f, 0f, 0f);
                }
                px[y * W + x] = c;
            }
        }

        var tex = new Texture2D(W, H, TextureFormat.RGBA32, false);
        tex.SetPixels32(px);
        tex.Apply(false, false);
        return tex;
    }

    /// <summary>绘制图片;tex 为 null 时什么都不画(不再改 GUI.color,原因见 <see cref="Panel"/>)。</summary>
    internal static void Image(Rect rect, Texture2D tex, ScaleMode mode = ScaleMode.ScaleAndCrop)
    {
        if (tex == null || rect.width <= 0f || rect.height <= 0f)
            return;
        GUI.DrawTexture(rect, tex, mode, true);
    }
}
