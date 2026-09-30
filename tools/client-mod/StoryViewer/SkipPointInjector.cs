using System;
using System.Collections.Generic;
using System.Text;

namespace StoryViewer;

/// <summary>
/// 剧本 csv 的「跳过落点」注入器(纯文本变换,不依赖 Unity/il2cpp,便于单独验证)。
/// <para>
/// 背景:游戏只给 R18 剧情的第 1 段(全年龄铺垫)写了跳过落点:
/// <code>
/// labeljump,b      ← 正常播放时越过落点
/// :SkipPoint       ← 按「跳过」时引擎跳到这里
/// uivisible,off
/// cleanskip        ← 结束跳过态并清理画面
/// :b
/// </code>
/// 后续第 2 段(R18 场景,以 adultui,on 开头)、第 3 段(尾声,以 adultui,off 开头)
/// 都没有这段,所以播到第 2 段后按「跳过」没有任何反应。
/// </para>
/// <para>
/// 本类给每个 R18 段落(以 adultui,on / adultui,off 标记开头)在收尾的 window,off 之前
/// 补一份同样的落点。不含 uivisible,off:尾声段不会再显示 UI,照抄官方写法会把界面留在隐藏态。
/// </para>
/// <para>
/// 幂等:段内已有 :SkipPoint 时该段原样保留。同时兼容两种加载方式——
/// 引擎逐段调用 InitCsv(各段文本内各注入一处),或把多段拼成一条 csv(同样各注入一处,
/// 且守卫标签各不重名,不影响引擎「从当前位置向前找下一个 SkipPoint」的解析)。
/// </para>
/// </summary>
public static class SkipPointInjector
{
    /// <summary>跳过落点标签名(游戏引擎按此名跳转)。</summary>
    public const string SkipLabel = "SkipPoint";

    /// <summary>落点命令:结束跳过态并清理画面。</summary>
    public const string CleanSkipCommand = "cleanskip";

    /// <summary>
    /// 在剧本 csv 中注入跳过落点。
    /// </summary>
    /// <param name="csv">引擎传给 NovelScriptCommands.InitCsv 的整段剧本文本;可为 null/空。</param>
    /// <param name="report">注入摘要(用于日志):每段的位置、是否已有点、是否注入。</param>
    /// <returns>
    /// 注入后的文本;无需改动时返回 <paramref name="csv"/> 本身(引用相等,调用方可据此跳过日志/替换)。
    /// </returns>
    public static string Inject(string csv, out string report)
    {
        report = null;
        if (string.IsNullOrEmpty(csv))
            return csv;

        // 按行切分并保留行尾,重组时原样保留原文的换行风格。
        List<string> lines = SplitKeepEndings(csv);

        // 段落起点 = adultui,on / adultui,off 所在行;段的范围到下一个这样的行(不含)为止。
        var segStarts = new List<int>();
        for (int i = 0; i < lines.Count; i++)
        {
            if (IsAdultUiLine(lines[i]))
                segStarts.Add(i);
        }
        if (segStarts.Count == 0)
        {
            report = "无 adultui 段标记(非 R18 分段剧本)";
            return csv;
        }

        HashSet<string> labels = CollectLabels(lines);
        var notes = new List<string>();
        var insertBefore = new Dictionary<int, List<string>>();

        for (int s = 0; s < segStarts.Count; s++)
        {
            int start = segStarts[s];
            int end = (s + 1 < segStarts.Count) ? segStarts[s + 1] - 1 : lines.Count - 1;

            bool hasSkipPoint = false;
            int anchor = -1;   // 段内最后一个 window,off:官方落点所在的收尾位置
            int terminal = -1; // 段内最后一个 cleanall / endof:没有 window,off 时的兜底锚点
            for (int i = start; i <= end; i++)
            {
                string t = TrimLine(lines[i]);
                if (t.Equals(":" + SkipLabel, StringComparison.Ordinal))
                    hasSkipPoint = true;
                if (t.StartsWith("window,off", StringComparison.Ordinal))
                    anchor = i;
                if (t.StartsWith("cleanall,", StringComparison.Ordinal) || t.Equals("endof", StringComparison.Ordinal))
                    terminal = i;
            }

            if (hasSkipPoint)
            {
                notes.Add($"段@{Row(start)}(行{start + 1}-{end + 1})已有 {SkipLabel},原样保留");
                continue;
            }

            // 落在段内最后一个 window,off 之前:与官方落点位置一致(收尾序列照常执行)。
            // 个别测试脚本没有 window,off,则退到 cleanall / endof 之前;都没有才追加到段尾。
            int insertAt = anchor >= 0
                ? anchor
                : (terminal >= 0 ? terminal : Math.Min(end + 1, lines.Count));
            string guard = MakeGuard(labels);
            if (!insertBefore.TryGetValue(insertAt, out List<string> guards))
                insertBefore[insertAt] = guards = new List<string>();
            guards.Add(guard);
            notes.Add($"段@{Row(start)}(行{start + 1}-{end + 1})在行{insertAt + 1}前注入落点({guard})");
        }

        if (insertBefore.Count == 0)
        {
            report = string.Join("; ", notes);
            return csv;
        }

        string nl = DetectNewline(lines);
        var sb = new StringBuilder(csv.Length + insertBefore.Count * 4 * (nl.Length + 24));
        for (int i = 0; i <= lines.Count; i++)
        {
            if (insertBefore.TryGetValue(i, out List<string> guards))
            {
                foreach (string guard in guards)
                {
                    // 文本末尾没有换行符时先把落点与上一行隔开,否则会粘成一行(实库存在这种脚本)。
                    if (sb.Length > 0 && sb[sb.Length - 1] != '\n')
                        sb.Append(nl);
                    // 与官方写法同构:正常播放由 labeljump 越过落点,跳过时落到 :SkipPoint。
                    sb.Append("labeljump,").Append(guard).Append(nl);
                    sb.Append(':').Append(SkipLabel).Append(nl);
                    sb.Append(CleanSkipCommand).Append(nl);
                    sb.Append(':').Append(guard).Append(nl);
                }
            }
            if (i < lines.Count)
                sb.Append(lines[i]);
        }

        report = string.Join("; ", notes);
        // 保持「结尾是否有换行」与原文一致:段尾追加时若原文无结尾换行,这里也不留。
        if (!csv.EndsWith("\n", StringComparison.Ordinal) && sb.Length >= nl.Length
            && sb.ToString(sb.Length - nl.Length, nl.Length) == nl)
        {
            sb.Length -= nl.Length;
        }
        return sb.ToString();
    }

    /// <summary>按 '\n' 切分,每项保留自己的行尾(\r\n 或 \n);最后一个无行尾的残行也计入。</summary>
    private static List<string> SplitKeepEndings(string s)
    {
        var lines = new List<string>();
        int start = 0;
        for (int i = 0; i < s.Length; i++)
        {
            if (s[i] == '\n')
            {
                lines.Add(s.Substring(start, i - start + 1));
                start = i + 1;
            }
        }
        if (start < s.Length)
            lines.Add(s.Substring(start));
        return lines;
    }

    /// <summary>去空白并去掉可能残留在行首的 UTF-8 BOM(剧本首行存在该情况)。</summary>
    private static string TrimLine(string line)
    {
        string t = line.Trim(' ', '\t', '\r', '\n');
        if (t.Length > 0 && t[0] == '\uFEFF')
            t = t.Substring(1).Trim(' ', '\t');
        return t;
    }

    /// <summary>是否 R18 段落起始命令(adultui,on / adultui,off;容忍参数后带额外字段)。</summary>
    private static bool IsAdultUiLine(string line)
    {
        string t = TrimLine(line);
        if (t.Length == 0 || t[0] == ':')
            return false;
        int comma = t.IndexOf(',');
        if (comma <= 0 || !t.Substring(0, comma).Equals("adultui", StringComparison.OrdinalIgnoreCase))
            return false;
        string arg = t.Substring(comma + 1);
        int comma2 = arg.IndexOf(',');
        if (comma2 >= 0)
            arg = arg.Substring(0, comma2);
        arg = arg.Trim(' ', '\t');
        return arg.Equals("on", StringComparison.OrdinalIgnoreCase)
            || arg.Equals("off", StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>收集全文本已有标签(用于守卫标签避重)。</summary>
    private static HashSet<string> CollectLabels(List<string> lines)
    {
        var set = new HashSet<string>(StringComparer.Ordinal);
        foreach (string line in lines)
        {
            string t = TrimLine(line);
            if (t.Length > 1 && t[0] == ':')
                set.Add(t.Substring(1));
        }
        return set;
    }

    /// <summary>生成全文本唯一的守卫标签(同名标签的解析顺序未知,必须避重)。</summary>
    private static string MakeGuard(HashSet<string> labels)
    {
        for (int i = 1; ; i++)
        {
            string name = "__sv_skip_" + i;
            if (labels.Add(name))
                return name;
        }
    }

    /// <summary>换行风格:取文本中出现的第一个行尾(\r\n 优先按内容判断),全无换行时用 \n。</summary>
    private static string DetectNewline(List<string> lines)
    {
        foreach (string line in lines)
        {
            if (line.EndsWith("\r\n", StringComparison.Ordinal))
                return "\r\n";
            if (line.EndsWith("\n", StringComparison.Ordinal))
                return "\n";
        }
        return "\n";
    }

    /// <summary>日志用的人类可读行号(1 起)。</summary>
    private static int Row(int index) => index + 1;
}
