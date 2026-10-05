#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一次发布的更新资产打包成「离线更新包」zip(给连不上 GitHub 的玩家用启动器本地导入)。

用法(开发机):
  D:\\Python\\python.exe build_update_pack.py                      # 自动取 dist 下最新的 release_*
  D:\\Python\\python.exe build_update_pack.py --release-dir dist\\release_20261005
  D:\\Python\\python.exe build_update_pack.py --version 20261005   # 覆盖输出文件名的版本号

前置:先用 build_github_pack.py 生成好某一版的全部资产(version.json + StoryViewer.dll +
stories.json + previews.zip + player_docs.zip + catalog_1.bin/.hash + master_data.zip +
client_body.zip + caches_update.zip + DotabyssOfflineLauncher.exe)。本脚本只是把这一整套
原样打成一个 zip,不做任何加工。

产出:
  <仓库>\\dist\\ドットアビスX_更新包_<版本>.zip

玩家侧:启动器「高级 ▾ → 离线更新包」选这个 zip → 自动解压、校验基线/各资产 md5、
套用与在线完全相同的更新流程(全程不联网)。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIST = os.path.join(REPO, "dist")
PACK_PREFIX = "ドットアビスX_更新包"


def _latest_release_dir() -> str:
    """dist 下按名字排序取最新的 release_* 目录。"""
    dirs = [d for d in glob.glob(os.path.join(DIST, "release_*")) if os.path.isdir(d)]
    if not dirs:
        return ""
    return sorted(dirs)[-1]


def main() -> int:
    """命令行入口:校验发布目录 → 打成离线更新包 zip。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="构建离线更新包 zip")
    parser.add_argument("--release-dir", default="", help="发布资产目录(默认取 dist 下最新 release_*)")
    parser.add_argument("--version", default="", help="输出文件名里的版本号(默认读 version.json)")
    parser.add_argument("--out", default=DIST, help="zip 输出目录(默认 <仓库>/dist)")
    args = parser.parse_args()

    release = os.path.abspath(args.release_dir) if args.release_dir else _latest_release_dir()
    if not release or not os.path.isdir(release):
        print("[ABORT] 找不到发布资产目录:%s(先跑 build_github_pack.py)" % (release or "(无)"))
        return 1
    vpath = os.path.join(release, "version.json")
    if not os.path.isfile(vpath):
        print("[ABORT] 发布目录缺少 version.json:%s" % release)
        return 1
    with open(vpath, "r", encoding="utf-8") as handle:
        version = json.load(handle) or {}
    ver = args.version or str(version.get("version") or "")
    if not ver:
        print("[ABORT] version.json 里没有 version 字段,且未用 --version 指定")
        return 1

    files = []
    for base, _dirs, names in os.walk(release):
        for name in sorted(names):
            path = os.path.join(base, name)
            arc = os.path.relpath(path, release).replace("\\", "/")
            files.append((path, arc))
    if len(files) < 2:
        print("[ABORT] 发布目录里文件过少(%d),不像完整的一组资产" % len(files))
        return 1

    os.makedirs(os.path.abspath(args.out), exist_ok=True)
    zip_path = os.path.join(os.path.abspath(args.out), "%s_%s.zip" % (PACK_PREFIX, ver))
    # 资产多为已压缩内容(zip/dll/bin),用 STORED 速度优先;允许超大包用 zip64。
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path, arc in files:
            archive.write(path, arc)
            print("[pack] %s (%.1f MB)" % (arc, os.path.getsize(path) / 1048576.0))

    print("\n[done] 离线更新包就绪:%s" % zip_path)
    print("       版本 %s / 插件 %s / 基线 %s,%d 个文件,合计 %.1f MB" % (
        version.get("version"), version.get("plugin_version"),
        version.get("baseline") or "(空)", len(files),
        os.path.getsize(zip_path) / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
