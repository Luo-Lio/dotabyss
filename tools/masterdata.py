# -*- coding: utf-8 -*-
"""master data 读取与名称映射。

master data 是 msgpack 序列化的表集合(实测 406 张表),每张表是「行数组的数组」,
字段无列名,需按实测下标取值。本模块只依赖以下三张实测表:

m_characters        [0]=character_id  [1]=角色名
m_character_skins   [0]=skin_id  [1]=character_id  [4]=皮肤名  [11]=立绘 id  [12]=背景 id
m_character_profiles[1]=character_id  [2]=角色介绍  [3]=称号

立绘/背景 id 形如 ``100401000G``(大写字母结尾),bundle 名里是小写,
故提供 :func:`normalize_art_id` 做统一。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import msgpack

# m_character_skins 的列下标(实测)
SKIN_ID = 0
SKIN_CHARACTER_ID = 1
SKIN_NAME = 4
SKIN_ART_ID = 11
SKIN_BG_ID = 12

CHARACTER_ID = 0
CHARACTER_NAME = 1

PROFILE_CHARACTER_ID = 1
PROFILE_TEXT = 2
PROFILE_TITLE = 3


@dataclass(frozen=True)
class SkinInfo:
    """一条皮肤记录及其所属角色。"""

    skin_id: int
    character_id: int
    character_name: str
    skin_name: str
    art_id: str
    bg_id: str


def normalize_art_id(raw: str) -> str:
    """把 bundle 名/资产名里的立绘 id 归一化为大写形式。

    Args:
        raw: 例如 ``100101000g`` 或 ``100101000G``。

    Returns:
        str: 形如 ``100101000G`` 的归一化 id;无法识别时原样返回。
    """
    s = raw.strip()
    if len(s) >= 2 and s[-1].isalpha():
        return s[:-1] + s[-1].upper()
    return s


class MasterData:
    """master data 的只读视图,提供 id → 名称映射。"""

    def __init__(self, tables: dict[str, list]) -> None:
        """初始化。

        Args:
            tables: 表名 → 行数组。
        """
        self.tables = tables
        self._char_name: dict[int, str] = {}
        for row in tables.get("m_characters", []):
            self._char_name[int(row[CHARACTER_ID])] = str(row[CHARACTER_NAME])
        self._profile: dict[int, tuple[str, str]] = {}
        for row in tables.get("m_character_profiles", []):
            self._profile[int(row[PROFILE_CHARACTER_ID])] = (str(row[PROFILE_TITLE]), str(row[PROFILE_TEXT]))
        self._by_art: dict[str, SkinInfo] = {}
        for row in tables.get("m_character_skins", []):
            art = normalize_art_id(str(row[SKIN_ART_ID]))
            char_id = int(row[SKIN_CHARACTER_ID])
            info = SkinInfo(
                skin_id=int(row[SKIN_ID]),
                character_id=char_id,
                character_name=self._char_name.get(char_id, ""),
                skin_name=str(row[SKIN_NAME]),
                art_id=art,
                bg_id=str(row[SKIN_BG_ID]),
            )
            self._by_art.setdefault(art, info)

    def character_name(self, character_id: int) -> str:
        """返回角色名,未知返回空串。"""
        return self._char_name.get(character_id, "")

    def profile(self, character_id: int) -> tuple[str, str]:
        """返回 (称号, 介绍),未知返回空串对。"""
        return self._profile.get(character_id, ("", ""))

    def skin_by_art(self, art_id: str) -> SkinInfo | None:
        """按立绘 id 反查皮肤信息。"""
        return self._by_art.get(normalize_art_id(art_id))

    def skin_by_bg(self, bg_id: str) -> SkinInfo | None:
        """按背景 id 反查皮肤信息(背景 id 与皮肤一一对应)。"""
        for info in self._by_art.values():
            if info.bg_id == bg_id:
                return info
        return None


def load_master_data(download_cache_dir: Path, explicit: Path | None = None) -> MasterData:
    """读取 master data。

    目录里可能有多个 .dat(历史版本),默认取体积最大的一个。

    Args:
        download_cache_dir: ``DownloadCache`` 目录。
        explicit: 显式指定的 .dat 路径。

    Returns:
        MasterData: 表集合视图。

    Raises:
        FileNotFoundError: 找不到任何 .dat 时抛出。
    """
    if explicit is not None:
        path = Path(explicit)
    else:
        candidates = sorted(Path(download_cache_dir).glob("*.dat"), key=lambda p: p.stat().st_size, reverse=True)
        if not candidates:
            raise FileNotFoundError(f"目录里没有 master data:{download_cache_dir}")
        path = candidates[0]
    with open(path, "rb") as fh:
        tables = msgpack.unpackb(fh.read(), raw=False, strict_map_key=False)
    return MasterData(tables)
