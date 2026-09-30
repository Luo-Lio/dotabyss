# -*- coding: utf-8 -*-
"""Addressables catalog 解析。

catalog 是 Unity Addressables 生成的二进制文件,本作实测单条 bundle 记录布局:

    <bundle 名(ASCII,含 .bundle 后缀)>
    <4B 指针> <4B 偏移>            ← 不参与解析,仅占位
    <16B 内容 md5>                 ← 与 bundle 名尾部 32hex 一致
    b" \\x00\\x00\\x00"            ← 分隔符
    <32B ASCII 缓存目录名>          ← 即 Caches 下的一级目录名

因此可以用「bundle 名尾部 md5 + 分隔符 + 32hex 缓存名」三重匹配来定位记录,
匹配失败的候选一律丢弃(实测 21746 条有效 / 21756 条丢弃)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

NAME_RE = re.compile(rb"[\x20-\x7e]{3,240}?\.bundle")
HEX32_RE = re.compile(rb"[0-9a-f]{32}")

# bundle 名里 lazyassets 之后的资产路径分段符:用于把名字切成「组前缀 + 资产路径」
GROUP_SEP = "_assets_assets_project_lazyassets_"
SEPARATOR = b" \x00\x00\x00"


@dataclass(frozen=True)
class BundleRecord:
    """catalog 中的一条远端 bundle 记录。"""

    name: str
    """bundle 名,形如 ``r18-only-charastand_..._g_charastand100101000g.prefab_<md5>.bundle``。"""
    md5: bytes
    """16 字节内容 md5,与 ``name`` 尾部 32hex 相同。"""
    cdn: str
    """32 位十六进制缓存目录名,即 ``Caches`` 下的一级目录。"""

    @property
    def group(self) -> str:
        """组前缀(资源分类),如 ``r18-only-charastand``。"""
        i = self.name.find(GROUP_SEP)
        return self.name[:i] if i >= 0 else ""

    @property
    def asset_hint(self) -> str:
        """组之后的资产路径提示,便于按关键字分类。"""
        i = self.name.find(GROUP_SEP)
        return self.name[i + len(GROUP_SEP):] if i >= 0 else self.name

    @property
    def md5_hex(self) -> str:
        """md5 的十六进制字符串。"""
        return self.md5.hex()


def parse_catalog(path: Path) -> list[BundleRecord]:
    """解析 catalog 文件,返回全部有效 bundle 记录。

    Args:
        path: catalog 的 ``.bin`` 文件路径。

    Returns:
        list[BundleRecord]: 记录列表;顺序与文件内出现顺序一致。
    """
    data = Path(path).read_bytes()
    records: list[BundleRecord] = []
    for m in NAME_RE.finditer(data):
        name = m.group(0).decode("ascii")
        tail = data[m.end(): m.end() + 64]
        md5 = tail[8:24]
        if tail[24:28] != SEPARATOR:
            continue
        hm = HEX32_RE.match(tail, 28)
        if not hm:
            continue
        # 三重校验:名字尾部 32hex 必须与记录的 md5 一致,否则视为误匹配
        expect = name.rsplit("_", 1)[-1][: -len(".bundle")]
        if md5.hex() != expect:
            continue
        records.append(BundleRecord(name=name, md5=md5, cdn=hm.group(0).decode("ascii")))
    return records


def pick_latest_catalog(catalog_dir: Path, explicit: Path | None = None) -> Path:
    """选取当前生效的 catalog。

    游戏每次版本更新会在目录里新增一个 ``<数字>.bin``,旧文件保留。
    默认取修改时间最新的一个;可用 ``explicit`` 覆盖。

    Args:
        catalog_dir: ``com.unity.addressables`` 目录。
        explicit: 显式指定的 catalog 路径。

    Returns:
        Path: 选中的 catalog 文件。

    Raises:
        FileNotFoundError: 目录里没有任何 catalog 时抛出。
    """
    if explicit is not None:
        if not Path(explicit).is_file():
            raise FileNotFoundError(f"指定的 catalog 不存在:{explicit}")
        return Path(explicit)
    candidates = sorted(catalog_dir.glob("*.bin"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"目录里没有 catalog 文件:{catalog_dir}")
    return candidates[0]
