using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using BepInEx;

namespace StoryViewer;

/// <summary>单条剧情(字段名刻意取短,压低随插件分发的 JSON 体积)。</summary>
internal class StoryEntry
{
    /// <summary>剧情 key(即游戏的 novelId / scriptId,如 mas_1001011001)。</summary>
    public string k { get; set; }

    /// <summary>标题(来自 master data;可能为空)。</summary>
    public string t { get; set; }

    /// <summary>系列短名(main/home/chara/tavern/side)。</summary>
    public string s { get; set; }

    /// <summary>角色名(可能为空)。</summary>
    public string c { get; set; }

    /// <summary>章节名/分组(可能为空)。</summary>
    public string ch { get; set; }

    /// <summary>是否 R18 剧情。</summary>
    public bool r18 { get; set; }

    /// <summary>中文标题(取自 AbyssMod 汉化缓存;为空时界面回退 <see cref="t"/>)。</summary>
    public string tz { get; set; }

    /// <summary>中文角色名(为空时回退 <see cref="c"/>)。</summary>
    public string cz { get; set; }

    /// <summary>中文章节名(为空时回退 <see cref="ch"/>)。</summary>
    public string chz { get; set; }

    /// <summary>中文剧情简介(用于详情栏;可能为空)。</summary>
    public string dz { get; set; }

    /// <summary>段号(1=前篇;≥2 表示是同一故事的续篇脚本)。</summary>
    public int part { get; set; }

    /// <summary>该故事的总段数(1 表示不分段)。</summary>
    public int parts { get; set; }

    /// <summary>分组名(列表里的分组标题:主线「第N章 章名」、活动「活动名」、其余「角色名」)。</summary>
    public string g { get; set; }

    /// <summary>主线章节号(1..N;用于列表里的金色章号,非主线/序章为 0)。</summary>
    public int n { get; set; }

    /// <summary>界面显示用标题(中文优先)。</summary>
    internal string DisplayTitle => string.IsNullOrEmpty(tz) ? (string.IsNullOrEmpty(t) ? k : t) : tz;

    /// <summary>界面显示用角色名(中文优先)。</summary>
    internal string DisplayCharacter => string.IsNullOrEmpty(cz) ? c : cz;

    /// <summary>界面显示用系列标签用的短名。</summary>
    internal string SortGroup => string.IsNullOrEmpty(g) ? "" : g;
}

/// <summary>系列信息(用于列表分组与标签)。</summary>
internal class StorySeriesInfo
{
    /// <summary>系列短名。</summary>
    public string key { get; set; }

    /// <summary>界面显示名。</summary>
    public string label { get; set; }

    /// <summary>该系列条目数(便于排查数据缺失)。</summary>
    public int count { get; set; }
}

/// <summary>随插件分发的剧情索引文件。</summary>
internal class StoryFile
{
    /// <summary>系列清单(顺序即界面展示顺序)。</summary>
    public List<StorySeriesInfo> series { get; set; } = new();

    /// <summary>全部可播放剧情。</summary>
    public List<StoryEntry> stories { get; set; } = new();
}

/// <summary>剧情索引的加载与查询。</summary>
internal sealed class StoryDatabase
{
    /// <summary>全部剧情(按 JSON 中的顺序)。</summary>
    internal List<StoryEntry> Entries { get; private set; } = new();

    /// <summary>系列清单。</summary>
    internal List<StorySeriesInfo> Series { get; private set; } = new();

    /// <summary>加载失败原因(成功时为空)。</summary>
    internal string Error { get; private set; }

    /// <summary>索引文件路径(插件目录下的 stories.json)。</summary>
    private static string FilePath => Path.Combine(Paths.PluginPath, "StoryViewer", "stories.json");

    /// <summary>
    /// 从插件目录读取剧情索引。
    /// </summary>
    /// <returns>StoryDatabase:失败时 Error 为原因,Entries 为空列表。</returns>
    internal static StoryDatabase Load()
    {
        var db = new StoryDatabase();
        try
        {
            string path = FilePath;
            if (!File.Exists(path))
            {
                db.Error = $"找不到剧情索引: {path}";
                return db;
            }

            var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
            var file = JsonSerializer.Deserialize<StoryFile>(File.ReadAllText(path), options);
            db.Entries = file?.stories ?? new List<StoryEntry>();
            db.Series = file?.series ?? new List<StorySeriesInfo>();
            Plugin.Logger.LogInfo($"剧情索引加载完成: {db.Entries.Count} 条 / {db.Series.Count} 个系列");
        }
        catch (Exception e)
        {
            db.Error = e.Message;
            Plugin.Logger.LogError($"剧情索引加载失败: {e}");
        }
        return db;
    }

    /// <summary>
    /// 按系列与关键字过滤。
    /// </summary>
    /// <param name="series">系列短名;null/空/"all" 表示不过滤。</param>
    /// <param name="search">关键字(匹配 key/日文标题/中文标题/角色名/章节或活动名,忽略大小写);空表示不过滤。</param>
    /// <param name="hideParts">true 时只保留前篇(隐藏续篇脚本,游戏本体也只列前篇)。</param>
    /// <param name="onlyR18">true 时只保留 R18 剧情。</param>
    /// <returns>过滤后的条目列表(保持索引文件里的顺序:系列 → 分组 → key)。</returns>
    internal List<StoryEntry> Filter(string series, string search, bool hideParts, bool onlyR18)
    {
        var outList = new List<StoryEntry>(Entries.Count);
        bool allSeries = string.IsNullOrEmpty(series) || series == "all";
        string needle = string.IsNullOrEmpty(search) ? null : search.Trim().ToLowerInvariant();
        foreach (var e in Entries)
        {
            if (!allSeries && e.s != series)
                continue;
            if (hideParts && e.part > 1)
                continue;
            if (onlyR18 && !e.r18)
                continue;
            if (needle != null)
            {
                bool hit = Contains(e.k, needle)
                           || Contains(e.t, needle)
                           || Contains(e.tz, needle)
                           || Contains(e.c, needle)
                           || Contains(e.cz, needle)
                           || Contains(e.ch, needle)
                           || Contains(e.chz, needle)
                           || Contains(e.g, needle);
                if (!hit)
                    continue;
            }
            outList.Add(e);
        }
        return outList;
    }

    /// <summary>大小写无关的子串匹配;源为 null/空时返回 false。</summary>
    private static bool Contains(string source, string loweredNeedle) =>
        !string.IsNullOrEmpty(source) && source.ToLowerInvariant().Contains(loweredNeedle);

    /// <summary>分段缓存:故事标识(系列 + 标题)→ 按 part 升序的条目列表。</summary>
    private Dictionary<string, List<StoryEntry>> _siblings;

    /// <summary>
    /// 取同一故事的分段条目(按 part 升序),用于详情栏的「分段」步进器。
    /// 分段判定:同一系列下标题相同且 parts&gt;1 的条目为一组。
    /// </summary>
    /// <param name="entry">当前条目;null 或不分段时返回 null。</param>
    internal List<StoryEntry> Siblings(StoryEntry entry)
    {
        if (entry == null || entry.parts <= 1)
            return null;
        if (_siblings == null)
            _siblings = BuildSiblingIndex();
        return _siblings.TryGetValue(SiblingKey(entry), out var list) ? list : null;
    }

    /// <summary>分组键:系列 + 标题(中文优先,与条目标题口径一致)。</summary>
    private static string SiblingKey(StoryEntry e) =>
        (e.s ?? "") + "\n" + (string.IsNullOrEmpty(e.tz) ? e.t : e.tz);

    /// <summary>构建分段索引(只在首次需要时做一次)。</summary>
    private Dictionary<string, List<StoryEntry>> BuildSiblingIndex()
    {
        var map = new Dictionary<string, List<StoryEntry>>();
        foreach (var e in Entries)
        {
            if (e.parts <= 1)
                continue;
            string key = SiblingKey(e);
            if (!map.TryGetValue(key, out var list))
            {
                list = new List<StoryEntry>();
                map[key] = list;
            }
            list.Add(e);
        }
        foreach (var list in map.Values)
            list.Sort((a, b) => a.part.CompareTo(b.part));
        return map;
    }
}
