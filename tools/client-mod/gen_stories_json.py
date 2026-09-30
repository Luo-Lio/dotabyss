"""从 output/manifest.json + AbyssMod 汉化缓存生成 StoryViewer 插件用的紧凑剧情索引 stories.json。

字段(短键名压体积):
    k=剧情 key(scriptId) / t=标题 / s=系列 / c=角色 / ch=章节或分组 / r18
    g=列表分组标题(主线=「第N章 章名」,活动/支线=活动名,其余=角色名)
    n=主线章节号(用于列表里的金色章号;非主线为 0)
    中文(取自 AbyssMod 的汉化缓存,缺失时为空,界面回退日文):
    tz=中文标题 / cz=中文角色 / chz=中文章节 / dz=中文简介
    分段(前篇/后篇,脚本 key 末位是段号;主数据只有前篇行,续篇继承前篇元数据):
    part=段号(1=前篇) / parts=该故事总段数

排序:系列 → 分组(主线章节号 / 活动 id / 角色名)→ key;
同一分组的条目在 JSON 里连续,界面据此插入分组标题。

用法: python tools/client-mod/gen_stories_json.py
汉化缓存: <client>/BepInEx/plugins/AbyssMod/cache/translations/{static,names}/zh_Hans.json
(缓存不存在时自动跳过汉化,只输出日文)
"""
from __future__ import annotations

import json
import os
import sys

# 控制台编码在中文 Windows 上常是 GBK,分组名里的「・」等字符会让 print 抛异常;
# 统计输出不该影响产物,遇到无法编码的字符一律替换。
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, OSError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))  # tools/client-mod -> 项目根
MANIFEST = os.path.join(PROJECT_ROOT, "output", "manifest.json")
OUT = os.path.join(HERE, "StoryViewer", "stories.json")
TRANSLATIONS = os.path.join(
    PROJECT_ROOT, "client", "BepInEx", "plugins", "AbyssMod", "cache", "translations"
)


def build_zh_map() -> dict[str, str]:
    """汇总 AbyssMod 汉化缓存里的全部「日文 → 中文」字符串映射。

    static/zh_Hans.json 形如 {表名: {字段: {日文: 中文}}},names/zh_Hans.json 是
    {日文名: 中文名};把标题/简介/角色/章节都并进一张大表,避免逐表挑字段。
    """
    out: dict[str, str] = {}
    static_path = os.path.join(TRANSLATIONS, "static", "zh_Hans.json")
    names_path = os.path.join(TRANSLATIONS, "names", "zh_Hans.json")
    try:
        with open(names_path, encoding="utf-8") as fh:
            names = json.load(fh)
        if isinstance(names, dict):
            out.update({k: v for k, v in names.items() if isinstance(v, str)})
    except FileNotFoundError:
        print(f"提示: 未找到汉化角色名表 {names_path},角色名保持日文")
    try:
        with open(static_path, encoding="utf-8") as fh:
            static = json.load(fh)
        for table in (static or {}).values():
            if not isinstance(table, dict):
                continue
            for field in table.values():
                if isinstance(field, dict):
                    for jp, zh in field.items():
                        if isinstance(zh, str) and jp:
                            out.setdefault(jp, zh)
    except FileNotFoundError:
        print(f"提示: 未找到汉化主数据表 {static_path},标题保持日文")
    return out


def zh(zh_map: dict[str, str], text: str) -> str:
    """查中文;查不到时尝试去掉 <…> 后缀再查(如「イライザ<娼館>」)。"""
    if not text:
        return ""
    hit = zh_map.get(text)
    if hit:
        return hit
    base = text.split("<", 1)[0]
    return zh_map.get(base, "") if base != text else ""


def main() -> None:
    """读取 manifest → 写 stories.json,并打印统计。"""
    with open(MANIFEST, encoding="utf-8") as fh:
        manifest = json.load(fh)

    scripts: dict = manifest.get("scripts") or {}
    story_block = manifest.get("stories") or {}
    entries: list = story_block.get("entries") or []
    series_defs: list = story_block.get("series") or []
    zh_map = build_zh_map()

    by_key = {e["key"]: e for e in entries if e.get("key")}
    series_order = {s["key"]: i for i, s in enumerate(series_defs)}

    # 1) 有主数据行的是「前篇」;其余脚本是续篇,按 key 末位段号归并到前篇
    primaries = [k for k in scripts if k in by_key]
    parts_of: dict[str, list[str]] = {}
    orphans: list[str] = []
    for key in scripts:
        if key in by_key:
            continue
        parent = None
        for cand in (key[:-1] + "1", key[:-1]):
            if cand in by_key:
                parent = cand
                break
        if parent:
            parts_of.setdefault(parent, []).append(key)
        else:
            orphans.append(key)

    def make_entry(key: str, src: dict | None, part: int, parts: int) -> dict:
        """构造一条索引;src 为 None 表示无元数据(仅调试脚本)。

        分组标题 g 按系列类型决定:主线「第N章 章名」、活动/支线「活动名/系列名」、
        其余(个人/角色/酒馆)「角色名」——界面直接用它做分组标题。
        """
        title = (src or {}).get("title") or ""
        chara = (src or {}).get("character") or ""
        series = (src or {}).get("series") or ""
        chapter_name = (src or {}).get("chapter_name") or ""
        chapter_no = (src or {}).get("chapter") if isinstance((src or {}).get("chapter"), int) else 0
        desc = (src or {}).get("desc") or ""

        # 章节/分组标签:主线补「第N章」前缀(章名可能没翻译,回退日文)
        chapter_zh = zh(zh_map, chapter_name) or chapter_name
        if series == "main" and chapter_name and 1 <= chapter_no <= 99:
            chapter_label = f"第{chapter_no}章 {chapter_name}"
            chapter_label_zh = f"第{chapter_no}章 {chapter_zh}"
        else:
            chapter_label = chapter_name
            chapter_label_zh = chapter_zh

        if series in ("main", "side"):
            group = chapter_label_zh
        else:
            # 分组名:去掉「<娼館>」这类变体后缀,让同一角色的所有条目排在一起、共用一个分组标题
            group = (zh(zh_map, chara) or chara).split("<", 1)[0]

        return {
            "k": key,
            "t": title,
            "s": series,
            "c": chara,
            "ch": chapter_label,
            "r18": bool((src or {}).get("r18")),
            "tz": zh(zh_map, title),
            "cz": zh(zh_map, chara),
            "chz": chapter_label_zh,
            "dz": zh(zh_map, desc),
            "part": part,
            "parts": parts,
            "g": group,
            # 主线章节号:界面用来画金色章号;序章/交流与其它系列为 0(不画章号)
            "n": chapter_no if (series == "main" and 1 <= chapter_no <= 99) else 0,
            # 临时排序键:分组序号(主线章节号 / 活动 id),写完 JSON 前删除
            "_ord": chapter_no,
        }

    stories: list[dict] = []
    for key in primaries:
        group = parts_of.get(key, [])
        parts = 1 + len(group)
        stories.append(make_entry(key, by_key[key], 1, parts))
        for cont in sorted(group):
            # 段号取 key 末位(2/3/4…);异常时记 2
            digit = cont[-1]
            stories.append(make_entry(cont, by_key[key], int(digit) if digit.isdigit() else 2, parts))
    for key in orphans:
        stories.append(make_entry(key, None, 1, 1))

    # 2) 排序:系列 → 分组(主线章节号 / 活动 id / 角色名)→ key;
    #    同一分组连续,界面据此插入分组标题
    def sort_key(e: dict):
        group_order = e.get("_ord", 0) if e["s"] in ("main", "side") else 0
        return (
            series_order.get(e["s"], 99),
            group_order if isinstance(group_order, int) else 0,
            0 if e["g"] else 1,
            e["g"],
            e["k"],
        )

    stories.sort(key=sort_key)
    for e in stories:
        e.pop("_ord", None)

    out_series = [
        {"key": s["key"], "label": s["label"], "count": sum(1 for x in stories if x["s"] == s["key"])}
        for s in series_defs
    ]

    payload = {"series": out_series, "stories": stories}
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))

    zh_titles = sum(1 for s in stories if s["tz"])
    zh_chars = sum(1 for s in stories if s["cz"])
    prim = sum(1 for s in stories if s["part"] == 1)
    size_kb = os.path.getsize(OUT) / 1024
    print(f"写出 {OUT} ({size_kb:.1f} KB)")
    print(f"剧情 {len(stories)} 条(前篇 {prim} / 续篇 {len(stories) - prim})"
          f";中文标题 {zh_titles} 条,中文角色 {zh_chars} 条;无元数据 {len(orphans)} 条 {orphans}")
    print(f"系列统计: {[(s['key'], s['count']) for s in out_series]}")
    print("分组明细(按 JSON 顺序):")
    for series in series_defs:
        groups: list[tuple[str, int]] = []
        for e in stories:
            if e["s"] != series["key"]:
                continue
            if not groups or groups[-1][0] != e["g"]:
                groups.append((e["g"] or "(无分组)", 0))
            groups[-1] = (groups[-1][0], groups[-1][1] + 1)
        print(f"  [{series['key']}] " + "; ".join(f"{name}×{cnt}" for name, cnt in groups))


if __name__ == "__main__":
    main()
