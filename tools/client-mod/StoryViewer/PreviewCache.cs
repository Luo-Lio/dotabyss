using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;
using UnityEngine;

namespace StoryViewer;

/// <summary>
/// 预览图缓存:按剧情 key 读取 <c>previews/&lt;key&gt;.jpg</c>,解码为 Texture2D 并做 LRU 缓存。
///
/// 本游戏是裁剪过的 IL2CPP 构建,Texture2D 构造与 <c>ImageConversion.LoadImage</c>
/// 是否可用无法静态确认(IMGUI 里有大量被裁成桩的方法),因此首次加载就当作一次自检:
/// 成功/失败各写一条日志;失败后整体退化为纯色块,不再反复尝试。
/// </summary>
internal sealed class PreviewCache
{
    /// <summary>同时缓存的纹理上限(可见行 + 详情大图足够用)。</summary>
    private const int MaxCached = 64;

    private readonly Dictionary<string, Texture2D> _textures = new(StringComparer.Ordinal);
    private readonly List<string> _order = new();
    private readonly HashSet<string> _available = new(StringComparer.Ordinal);
    private bool _broken;
    private bool _selfTested;

    /// <summary>预览图目录(插件目录下的 previews)。</summary>
    private static string Root => Path.Combine(Paths.PluginPath, "StoryViewer", "previews");

    /// <summary>扫描预览目录,建立可用 key 集合。</summary>
    internal PreviewCache()
    {
        try
        {
            if (Directory.Exists(Root))
            {
                foreach (string file in Directory.GetFiles(Root, "*.jpg"))
                    _available.Add(Path.GetFileNameWithoutExtension(file));
            }
        }
        catch (Exception e)
        {
            Plugin.Logger.LogWarning($"预览图目录扫描失败: {e.Message}");
        }
        Plugin.Logger.LogInfo($"预览图已载入索引: {_available.Count} 张");
    }

    /// <summary>该剧情是否有预览图(且纹理加载未被判定为不可用)。</summary>
    /// <param name="key">剧情 key。</param>
    /// <returns>true 表示可尝试 Get。</returns>
    internal bool Has(string key) => !_broken && !string.IsNullOrEmpty(key) && _available.Contains(key);

    /// <summary>取预览纹理(带缓存);不可用或加载失败返回 null,由界面退化为纯色块。</summary>
    /// <param name="key">剧情 key。</param>
    /// <returns>纹理;null 表示没有预览图。</returns>
    internal Texture2D Get(string key)
    {
        if (!Has(key))
            return null;

        if (_textures.TryGetValue(key, out var cached) && cached != null)
        {
            Touch(key);
            return cached;
        }

        try
        {
            byte[] bytes = File.ReadAllBytes(Path.Combine(Root, key + ".jpg"));
            var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            // interop 提供 byte[] → Il2CppStructArray<byte> 的隐式转换。
            if (!ImageConversion.LoadImage(tex, bytes))
            {
                _broken = true;
                Plugin.Logger.LogError("预览图自检失败: LoadImage 返回 false(纹理加载不可用)");
                return null;
            }
            try
            {
                tex.wrapMode = TextureWrapMode.Clamp;
                tex.filterMode = FilterMode.Bilinear;
            }
            catch
            {
                // 个别属性被裁剪时不影响显示,保持默认即可。
            }
            tex.hideFlags = HideFlags.HideAndDontSave;
            _textures[key] = tex;
            Touch(key);
            Trim();
            if (!_selfTested)
            {
                _selfTested = true;
                Plugin.Logger.LogInfo($"预览图自检成功: {tex.width}x{tex.height} ({key})");
            }
            return tex;
        }
        catch (Exception e)
        {
            _broken = true;
            Plugin.Logger.LogError($"预览图自检失败: {e.GetType().Name}: {e.Message}");
            return null;
        }
    }

    /// <summary>销毁全部缓存纹理(组件销毁时调用)。</summary>
    internal void Dispose()
    {
        foreach (var tex in _textures.Values)
        {
            if (tex != null)
            {
                try { UnityEngine.Object.Destroy(tex); } catch { /* 退出流程中失败可忽略 */ }
            }
        }
        _textures.Clear();
        _order.Clear();
    }

    /// <summary>把 key 记为最近使用。</summary>
    private void Touch(string key)
    {
        _order.Remove(key);
        _order.Add(key);
    }

    /// <summary>超出上限时淘汰最久未用的纹理。</summary>
    private void Trim()
    {
        while (_order.Count > MaxCached)
        {
            string oldest = _order[0];
            _order.RemoveAt(0);
            if (_textures.TryGetValue(oldest, out var tex))
            {
                _textures.Remove(oldest);
                if (tex != null)
                {
                    try { UnityEngine.Object.Destroy(tex); } catch { /* 忽略 */ }
                }
            }
        }
    }
}
