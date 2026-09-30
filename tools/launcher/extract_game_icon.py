#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从游戏 exe 抽出多尺寸 ICO 到 tools/launcher/dotabyss_launcher.ico。

用法:``D:\\Python\\python.exe extract_game_icon.py``(依赖 pefile)。
"""

from __future__ import annotations

import os
import struct
import sys

import pefile

RT_ICON = 3
RT_GROUP_ICON = 14
GAME_EXE_NAME = "ドットアビスX.exe"
ICO_NAME = "dotabyss_launcher.ico"


def _first_data(pe, directory_entry):
    """取资源目录下第一份语言数据,不存在返回 None。"""
    for name_entry in directory_entry.directory.entries:
        for lang_entry in name_entry.directory.entries:
            info = lang_entry.data.struct
            return pe.get_data(info.OffsetToData, info.Size)
    return None


def _icon_map(pe, directory_entry):
    """``RT_ICON id -> 原始字节`` 映射。"""
    out = {}
    for name_entry in directory_entry.directory.entries:
        icon_id = name_entry.id
        if icon_id is None:
            continue
        for lang_entry in name_entry.directory.entries:
            info = lang_entry.data.struct
            out[icon_id] = pe.get_data(info.OffsetToData, info.Size)
            break
    return out


def build_ico(group_data, icons):
    """把 GROUP_ICON 记录与 RT_ICON 数据拼成 .ico 文件字节。"""
    _reserved, _type, count = struct.unpack_from("<HHH", group_data, 0)
    entries = []
    offset = 6
    for _ in range(count):
        record = struct.unpack_from("<BBBBHHIH", group_data, offset)
        offset += 14
        width, height, colors, _res, planes, bits, _nbytes, icon_id = record
        blob = icons.get(icon_id)
        if not blob:
            continue
        entries.append((width, height, colors, planes, bits, blob))
    if not entries:
        raise RuntimeError("no icon images in group")
    header = struct.pack("<HHH", 0, 1, len(entries))
    directory_size = 6 + 16 * len(entries)
    chunks = [header]
    payload = b""
    cursor = directory_size
    for width, height, colors, planes, bits, blob in entries:
        chunks.append(struct.pack("<BBBBHHII", width, height, colors, 0,
                                  planes, bits, len(blob), cursor))
        payload += blob
        cursor += len(blob)
    return b"".join(chunks) + payload


def extract(exe_path, out_path):
    """从 exe 写 ICO,返回 ``(路径, 字节数, 图像数)``。"""
    pe = pefile.PE(exe_path)
    group_data = None
    icons = {}
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if entry.id == RT_GROUP_ICON:
            group_data = _first_data(pe, entry)
        elif entry.id == RT_ICON:
            icons.update(_icon_map(pe, entry))
    if not group_data:
        raise RuntimeError("RT_GROUP_ICON missing: %s" % exe_path)
    data = build_ico(group_data, icons)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as handle:
        handle.write(data)
    return out_path, len(data), struct.unpack_from("<HHH", data, 0)[2]


def main():
    """默认从 ``<仓库>/client/ドットアビスX.exe`` 抽图标。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    game_dir = os.environ.get("DOTABYSS_GAME_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(script_dir)), "client")
    exe = os.path.join(game_dir, GAME_EXE_NAME)
    out = os.path.join(script_dir, ICO_NAME)
    path, size, count = extract(exe, out)
    print("wrote %s bytes %d images %d" % (path, size, count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
