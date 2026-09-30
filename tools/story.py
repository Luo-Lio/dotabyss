# -*- coding: utf-8 -*-
"""剧情索引:把 master data 里的剧情表整理成「角色/章节 → 系列 → 剧情」结构。

实测表结构(均为「行数组的数组」,无列名,下标是实测值):

- ``m_novel_homes``         个人剧情 men_ : ``[id, key, title, '', order]``
- ``m_novel_characters``    角色/酒馆剧情  : ``[id, key, group, title, desc, character_id, r18, ?, chapter, ?, unlock]``
- ``m_novel_side_stories``  支线 evs_     : ``[id, 系列id, ?, key, title, desc, ?, order]``
- ``m_novel_events``        活动 evs_     : ``[id, 活动id, key, title, desc, ?, order, 开启时间]``
- ``m_novel_prologues``     序章 mas_     : ``[id, ?, key, title, desc, ?, ?, order]``
- ``m_novel_character_skins`` 酒馆衣装剧情 : ``[id, skin_id, key, group, title, desc, ?, ?, ?]``

分组元数据(用于界面把同一章节/活动的剧情归到一组):

- ``m_novel_main_chapters`` 主线章节 : ``[章番号, ?, 章名, 排序, 立绘, 简介]``
- ``m_events``             活动     : ``[活动id, 活动名, …]``(m_novel_events 的第 2 列是活动 id)
- ``m_side_stories``       支线系列 : ``[系列id, 系列名, 开始时间, …]``
  (m_novel_side_stories 第 2 列是「故事 id」,前 7 位即系列 id,如 102200101 → 1022001)

系列与游戏内实态的对应(实测 + metadata 文案证据):

- ``men_`` = 「〇〇の日常そのN」→ 个人剧情
- ``hmr_`` = 酒馆/娼館剧情(metadata 有「酒場(娼館の全年齢表記)ボタン」;简介含「娼館」「酒場の２階」)
- ``hmn_`` = 全年龄角色剧情(每角色固定 3 话)

**数量一律不写死**:某角色有几个个人剧情、几个酒馆剧情完全由表数据决定,
后续版本新增/解锁会自动体现,工具不做任何个数假设。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .masterdata import MasterData, normalize_art_id

# 剧情 key 形如 men_10010100001 / hmr_10010100011;9 位数字段是立绘(皮肤)前缀
KEY_RE = re.compile(r"^(?P<prefix>men|hmn|hmr|mas|evs)_(?P<digits>\d+)$")


@dataclass(frozen=True)
class StorySeries:
    """一个剧情系列(前缀 → 表 → 显示名)。"""

    key: str
    """系列短名(main/home/chara/tavern/side),用作 manifest 键。"""
    label: str
    """界面显示名。"""
    prefix: str
    """剧情 key 前缀(men_/hmn_/hmr_/evs_/mas_)。"""
    table: str
    """主表名。"""
    extra_tables: tuple[str, ...] = ()
    """补充表名(同一前缀的剧情散在多张表里时使用)。"""


# 系列定义顺序即界面展示顺序;标签依据见模块 docstring
SERIES: tuple[StorySeries, ...] = (
    StorySeries("main", "主线剧情", "mas_", "m_novel_mains",
                ("m_novel_prologues", "m_novel_others")),
    StorySeries("home", "个人剧情", "men_", "m_novel_homes"),
    StorySeries("chara", "角色剧情", "hmn_", "m_novel_characters"),
    StorySeries("tavern", "酒馆剧情", "hmr_", "m_novel_characters"),
    StorySeries("side", "支线剧情", "evs_", "m_novel_side_stories",
                ("m_novel_events",)),
)

# m_novel_characters 的实测列下标
CH_ID, CH_KEY, CH_GROUP, CH_TITLE, CH_DESC, CH_CHARACTER, CH_R18, CH_CHAPTER, CH_UNLOCK = 0, 1, 2, 3, 4, 5, 6, 8, 10
# m_novel_homes
HOME_ID, HOME_KEY, HOME_TITLE, HOME_ORDER = 0, 1, 2, 4
# m_novel_side_stories / m_novel_prologues
SIDE_STORY_ID, SIDE_KEY, SIDE_TITLE, SIDE_DESC, SIDE_ORDER = 1, 3, 4, 5, 7
PRO_KEY, PRO_TITLE, PRO_DESC, PRO_ORDER = 2, 3, 4, 7
# m_novel_mains: [id, 章番号, 话番号, key, 标题, 简介, ?, 排序]
MAIN_CHAPTER, MAIN_KEY, MAIN_TITLE, MAIN_DESC, MAIN_ORDER = 1, 3, 4, 5, 7
# m_novel_main_chapters: [章番号, ?, 章名, ?, 立绘, 简介]
CHAPTER_NO, CHAPTER_NAME = 0, 2
# m_novel_others: [id, ?, 分组, key, 标题, 简介, ?, 排序]
OTHER_KEY, OTHER_TITLE, OTHER_DESC, OTHER_GROUP, OTHER_ORDER = 3, 4, 5, 2, 7
# m_novel_events: [id, 活动id, key, 标题, 简介, ?, 排序, 开启时间]
NOVEL_EVENT_ID, EVENT_KEY, EVENT_TITLE, EVENT_DESC, EVENT_ORDER = 1, 2, 3, 4, 6
# m_events: [活动id, 活动名, …]
EVENT_ID, EVENT_NAME = 0, 1
# m_side_stories: [系列id, 系列名, 开始时间, …]
ARC_ID, ARC_NAME = 0, 1
# m_novel_character_skins
CSKIN_KEY, CSKIN_GROUP, CSKIN_TITLE, CSKIN_DESC, CSKIN_SKIN = 2, 3, 4, 5, 1

# 「交流」等杂项主线排在各章之后(章节号用一个大值),序章为 0
MAIN_OTHER_CHAPTER = 900


def _digits_of(key: str) -> str:
    """取剧情 key 的数字段(``men_10010100001`` → ``10010100001``)。"""
    m = KEY_RE.match(key)
    return m.group("digits") if m else ""


def _art_prefix(key: str) -> str:
    """取剧情 key 里的立绘前缀(前 9 位数字),用于反查角色。"""
    digits = _digits_of(key)
    return digits[:9] if len(digits) >= 9 else ""


def _find_key(row: list, prefix: str) -> str:
    """在行里找以指定前缀开头的剧情 key。"""
    for v in row:
        if isinstance(v, str) and v.startswith(prefix):
            return v
    return ""


def _as_int(v: Any) -> int | None:
    """尽力把值转成 int,失败返回 None。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class StoryIndex:
    """剧情索引:entries(逐条)+ 角色归属 + 系列统计。"""

    def __init__(self, master: MasterData) -> None:
        """初始化。

        Args:
            master: master data 视图(提供角色名与立绘 → 角色映射)。
        """
        self.master = master
        self._art2char: dict[str, int] = {}
        for info in master.tables.get("m_character_skins", []):
            art = str(info[11])
            art_id = normalize_art_id(art)
            digits = re.sub(r"\D", "", art_id)[:9]
            if digits:
                self._art2char.setdefault(digits, _as_int(info[1]) or 0)
        self.entries: list[dict] = []
        self.costumes: dict[str, dict] = {}
        # 主线章节号 → 章节名(m_novel_main_chapters)
        self._chapters: dict[int, str] = {}
        for row in master.tables.get("m_novel_main_chapters", []):
            if isinstance(row, list) and len(row) > CHAPTER_NAME:
                self._chapters[_as_int(row[CHAPTER_NO]) or 0] = str(row[CHAPTER_NAME])
        # 活动 id → 活动名(m_events);支线系列 id → 支线名(m_side_stories)
        self._events: dict[int, str] = {}
        for row in master.tables.get("m_events", []):
            if isinstance(row, list) and len(row) > EVENT_NAME:
                self._events[_as_int(row[EVENT_ID]) or 0] = str(row[EVENT_NAME])
        self._arcs: dict[int, str] = {}
        for row in master.tables.get("m_side_stories", []):
            if isinstance(row, list) and len(row) > ARC_NAME:
                self._arcs[_as_int(row[ARC_ID]) or 0] = str(row[ARC_NAME])
        self._build()

    def _character_of(self, key: str) -> int:
        """按立绘前缀反查角色 id(表里没给 character_id 的系列用)。"""
        return self._art2char.get(_art_prefix(key), 0)

    def _row_entry(self, series: StorySeries, key: str, title: str, desc: str,
                   order: int | None, character_id: int, r18: bool,
                   chapter: int | None, unlock: int | None,
                   thumb_kind: str | None = None, chapter_name: str = "") -> dict:
        """组装一条剧情条目。"""
        return {
            "key": key,
            "series": series.key,
            "title": title,
            "desc": desc,
            "order": order,
            "chapter": chapter,
            "chapter_name": chapter_name,
            "unlock": unlock,
            "r18": r18,
            "character_id": character_id,
            "character": self.master.character_name(character_id) if character_id else "",
            "art_id": _art_prefix(key),
            "thumb": thumb_kind or "",
        }

    def _add_costumes(self) -> None:
        """解析酒馆衣装剧情表,把衣装信息挂到对应剧情上。"""
        for row in self.master.tables.get("m_novel_character_skins", []):
            key = str(row[CSKIN_KEY]) if len(row) > CSKIN_KEY else ""
            if not key:
                continue
            self.costumes[key] = {
                "group": str(row[CSKIN_GROUP]) if len(row) > CSKIN_GROUP else "",
                "skin_id": _as_int(row[CSKIN_SKIN]) or 0,
                "title": str(row[CSKIN_TITLE]),
                "desc": str(row[CSKIN_DESC]),
            }

    def _build(self) -> None:
        """遍历各系列表(含补充表),生成 entries 与系列统计。"""
        self._add_costumes()
        for series in SERIES:
            for table in (series.table, *series.extra_tables):
                for row in self.master.tables.get(table, []):
                    if not isinstance(row, list):
                        continue
                    key = _find_key(row, series.prefix)
                    if not key:
                        continue
                    entry = self._entry_of(series, table, row, key)
                    if entry:
                        self.entries.append(entry)
        # 酒馆衣装信息并入对应条目(没有对应条目的衣装剧情单独成条,保证不丢数据)
        known = {e["key"] for e in self.entries}
        for key, costume in self.costumes.items():
            if key in known:
                next(e for e in self.entries if e["key"] == key)["costume"] = costume
            else:
                series = SERIES[2]
                self.entries.append(self._row_entry(series, key, costume["title"], costume["desc"],
                                                    None, self._character_of(key), True, None, None, ""))
                self.entries[-1]["costume"] = costume

    def _entry_of(self, series: StorySeries, table: str, row: list, key: str) -> dict | None:
        """按「系列 + 表」解析一行,返回剧情条目。

        Args:
            series: 系列定义。
            table: 该行所属表名(决定列含义)。
            row: 表行。
            key: 行里的剧情 key。

        Returns:
            dict | None: 剧情条目;无法解析时返回 None。
        """
        if series.key == "home":
            title = str(row[HOME_TITLE]) if len(row) > HOME_TITLE else ""
            order = _as_int(row[HOME_ORDER]) if len(row) > HOME_ORDER else None
            return self._row_entry(series, key, title, "", order, self._character_of(key),
                                   False, order, None)
        if series.key in ("chara", "tavern"):
            title = str(row[CH_TITLE]) if len(row) > CH_TITLE else ""
            desc = str(row[CH_DESC]) if len(row) > CH_DESC else ""
            order = _as_int(row[CH_CHAPTER]) if len(row) > CH_CHAPTER else None
            character_id = _as_int(row[CH_CHARACTER]) if len(row) > CH_CHARACTER else None
            character_id = character_id or self._character_of(key)
            r18 = bool(row[CH_R18]) if len(row) > CH_R18 else (series.prefix == "hmr_")
            group = str(row[CH_GROUP]) if len(row) > CH_GROUP else ""
            # 酒馆剧情的封面缩略图资产名:story_s_<group>(实测,仅 hmr_ 系列有)
            thumb = f"story_s_{group}" if series.prefix == "hmr_" and group.startswith("hmr_") else ""
            return self._row_entry(series, key, title, desc, order, character_id, r18, order,
                                   _as_int(row[CH_UNLOCK]) if len(row) > CH_UNLOCK else None, thumb)
        if series.key == "side":
            if table == "m_novel_events":
                title = str(row[EVENT_TITLE]) if len(row) > EVENT_TITLE else ""
                desc = str(row[EVENT_DESC]) if len(row) > EVENT_DESC else ""
                order = _as_int(row[EVENT_ORDER]) if len(row) > EVENT_ORDER else None
                # 分组 = 活动:chapter 存活动 id,chapter_name 存活动名(界面按活动归组)
                event_id = _as_int(row[NOVEL_EVENT_ID]) or 0
                return self._row_entry(series, key, title, desc, order, 0, False,
                                       event_id, None, "", self._events.get(event_id, ""))
            title = str(row[SIDE_TITLE]) if len(row) > SIDE_TITLE else ""
            desc = str(row[SIDE_DESC]) if len(row) > SIDE_DESC else ""
            order = _as_int(row[SIDE_ORDER]) if len(row) > SIDE_ORDER else None
            # 分组 = 支线系列:故事 id 前 7 位为系列 id(102200101 → 1022001)
            story_id = _as_int(row[SIDE_STORY_ID]) or 0
            arc_id = story_id // 100
            return self._row_entry(series, key, title, desc, order, 0, False,
                                   arc_id, None, "", self._arcs.get(arc_id, ""))
        # 主线:三张表合流,章节名来自 m_novel_main_chapters
        if table == "m_novel_mains":
            chapter_no = _as_int(row[MAIN_CHAPTER]) or 0
            title = str(row[MAIN_TITLE]) if len(row) > MAIN_TITLE else ""
            desc = str(row[MAIN_DESC]) if len(row) > MAIN_DESC else ""
            order = chapter_no * 1000 + (_as_int(row[MAIN_ORDER]) or 0)
            return self._row_entry(series, key, title, desc, order, 0, False, chapter_no, None,
                                   "", self._chapters.get(chapter_no, ""))
        if table == "m_novel_others":
            title = str(row[OTHER_TITLE]) if len(row) > OTHER_TITLE else ""
            desc = str(row[OTHER_DESC]) if len(row) > OTHER_DESC else ""
            order = 900000 + (_as_int(row[OTHER_ORDER]) or 0)
            group = str(row[OTHER_GROUP]) if len(row) > OTHER_GROUP else ""
            # 「交流」等杂项排在各章之后:章节号取大值,章节名沿用分组名
            return self._row_entry(series, key, title, desc, order, 0, False,
                                   MAIN_OTHER_CHAPTER, None, "", group)
        if table == "m_novel_prologues":  # 序章:排在最前
            title = str(row[PRO_TITLE]) if len(row) > PRO_TITLE else ""
            desc = str(row[PRO_DESC]) if len(row) > PRO_DESC else ""
            order = _as_int(row[PRO_ORDER]) if len(row) > PRO_ORDER else None
            return self._row_entry(series, key, title, desc, order, 0, False, 0, None, "", "序章")
        return None

    def series_stats(self) -> list[dict]:
        """按系列统计条目数与覆盖角色数。"""
        out = []
        for series in SERIES:
            rows = [e for e in self.entries if e["series"] == series.key]
            out.append({
                "key": series.key,
                "label": series.label,
                "prefix": series.prefix,
                "count": len(rows),
                "characters": len({e["character_id"] for e in rows if e["character_id"]}),
            })
        return out

    def character_summary(self) -> list[dict]:
        """每角色的各系列条目数(数量取自数据,不做任何上限假设)。"""
        by_char: dict[int, dict[str, int]] = {}
        for e in self.entries:
            cid = e["character_id"]
            if not cid:
                continue
            by_char.setdefault(cid, {})[e["series"]] = by_char.setdefault(cid, {}).get(e["series"], 0) + 1
        out = []
        for cid, counts in by_char.items():
            out.append({
                "character_id": cid,
                "character": self.master.character_name(cid),
                "counts": counts,
                "total": sum(counts.values()),
            })
        out.sort(key=lambda x: (-x["total"], x["character_id"]))
        return out

    def to_dict(self) -> dict:
        """导出为 manifest 可序列化结构。"""
        entries = sorted(self.entries, key=lambda e: (e["series"], e["character_id"], e["order"] or 0, e["key"]))
        return {
            "series": self.series_stats(),
            "characters": self.character_summary(),
            "entries": entries,
        }


def build_story_index(master: MasterData) -> dict:
    """构建剧情索引。

    Args:
        master: master data 视图。

    Returns:
        dict: 含 ``series``(系列统计)、``characters``(每角色数量)、``entries``(逐条剧情)。
    """
    return StoryIndex(master).to_dict()
