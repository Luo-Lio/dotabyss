#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 GitHub Release 更新资产(启动器「更新」按钮消费的那一组文件)。

用法(开发机):
  D:\\Python\\python.exe build_github_pack.py                       # 版本号默认当天
  D:\\Python\\python.exe build_github_pack.py --notes "本次更新说明"
  D:\\Python\\python.exe build_github_pack.py --caches-since <旧完整包目录>   # 生成素材增量

产出 <仓库>\\dist\\release_<版本>\\:
  version.json                更新清单(版本号/基线/各资产 md5/文件清单)
  StoryViewer.dll             插件本体
  stories.json                剧情索引
  DotabyssOfflineLauncher.exe 启动器(自替换用)
  previews.zip                剧情封面
  player_docs.zip             玩家文档(使用说明/安装排障/启动器使用说明/check_health.bat)
  catalog_1.bin               资源 catalog
  catalog_1.bin.hash          catalog 哈希
  client_body.zip             客户端本体(相对完整包的差异文件集,启动器按 md5 只装缺的)
  caches_update.zip           素材增量(仅 --caches-since 时;新角色/新剧情 bundle)
  master_data.zip             主数据缓存(DownloadCache/*.dat,每次发布必带)

上传:把该目录里全部文件作为同一 Release 的附件(名字必须与上面完全一致);
同版本号会被启动器视为「已是最新」,重发必须换版本号。
基线(baseline)来自完整包的 offline_version.json:基线不一致的玩家会被拒绝增量更新,
必须重新下载完整包。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dotabyss_offline_core as core  # noqa: E402
import dotabyss_pack_tools as pack_tools  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS_SRC = os.path.join(REPO, "tools", "launcher", "player_docs")
DIST = os.path.join(REPO, "dist")
DEFAULT_PACK = os.path.join(DIST, "ドットアビスX离线版")
CHECK_HEALTH = os.path.join(REPO, "tools", "launcher", "check_health.bat")


def _zip_dir(source_dir: str, zip_path: str, arc_prefix: str = "") -> int:
    """把目录下的文件打成 zip(不压缩内容,PNG/JPG 已压缩过),返回文件数。"""
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for name in sorted(os.listdir(source_dir)):
            path = os.path.join(source_dir, name)
            if os.path.isfile(path):
                archive.write(path, arc_prefix + name)
                count += 1
    return count


def _zip_files(paths: list, zip_path: str) -> None:
    """把指定文件打成 zip(启压缩,都是小文本)。"""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in paths:
            archive.write(path, os.path.basename(path))


def _copy_file(path: str, out_dir: str) -> str:
    """复制单个文件到发布目录,返回目标路径。"""
    target = os.path.join(out_dir, os.path.basename(path))
    with open(path, "rb") as source, open(target, "wb") as dest:
        dest.write(source.read())
    return target


def _zip_master_data(seed_dir: str, zip_path: str) -> dict:
    """把完整包内主数据种子打成 ``DownloadCache/*.dat`` 附件并返回清单。"""
    source = os.path.join(seed_dir, "DownloadCache")
    if not os.path.isdir(source):
        raise ValueError("完整包缺少主数据种子目录:%s" % source)
    files = {}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for root, _dirs, names in os.walk(source):
            for name in sorted(names):
                if not name.lower().endswith(".dat"):
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, seed_dir).replace("\\", "/")
                if not core.master_data_rel_allowed(rel):
                    raise ValueError("主数据种子含非法路径:%s" % rel)
                files[rel] = core.file_md5(path)
                archive.write(path, rel)
    if not files:
        raise ValueError("主数据种子目录没有 .dat 文件:%s" % source)
    return {"zip": "master_data.zip", "zip_md5": core.file_md5(zip_path),
            "bytes": os.path.getsize(zip_path), "files": files}


def _fail(message: str) -> int:
    """打印失败原因并返回 1。"""
    print("[ABORT] " + message)
    return 1


def main() -> int:
    """命令行入口:生成全部更新资产并打印上传提示。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="构建 GitHub 更新资产")
    parser.add_argument("--version", default=time.strftime("%Y%m%d"), help="版本号(默认当天)")
    parser.add_argument("--notes", default="", help="更新说明(写进 version.json)")
    parser.add_argument("--pack", default=DEFAULT_PACK, help="完整包目录(默认 dist/ドットアビスX离线版)")
    parser.add_argument("--baseline", default="", help="基线版本号(默认取完整包 offline_version.json)")
    parser.add_argument("--channel", default="", help="更新通道(默认取完整包;再默认 baseline)")
    parser.add_argument("--caches-since", default="", help="旧完整包目录(生成 bundle 素材增量)")
    parser.add_argument("--no-client-body", action="store_true", help="不生成 client_body.zip")
    args = parser.parse_args()

    pack = os.path.abspath(args.pack)
    out_dir = os.path.join(DIST, "release_%s" % args.version)
    os.makedirs(out_dir, exist_ok=True)

    plugin_dll = core.plugin_dll_path(pack)
    stories = core.stories_path(pack)
    launcher_exe = core.launcher_path(pack)
    previews = core.previews_dir(pack)
    seed_bin, seed_hash = core.seed_catalog_pair(pack)
    for path, label in ((plugin_dll, "StoryViewer.dll"), (stories, "stories.json"),
                        (launcher_exe, "DotabyssOfflineLauncher.exe"),
                        (previews, "previews 目录"), (pack, "完整包目录")):
        if not os.path.exists(path):
            return _fail("缺少 %s:%s" % (label, path))
    if not (seed_bin and seed_hash):
        return _fail("完整包内缺 catalog 种子(先生成完整包):%s" % core.catalog_seed_dir(pack))
    master_data_path = os.path.join(out_dir, "master_data.zip")
    # 失败时清掉旧附件,避免复用旧 Release 目录里的过期主数据包。
    try:
        os.remove(master_data_path)
    except FileNotFoundError:
        pass
    try:
        master_data = _zip_master_data(core.local_low_seed_dir(pack), master_data_path)
    except (OSError, ValueError) as error:
        try:
            os.remove(master_data_path)
        except OSError:
            pass
        return _fail(str(error))

    stories_ok, stories_detail = core._stories_status(stories)
    if not stories_ok:
        return _fail("stories.json 不合格:%s" % stories_detail)

    pack_version = core.load_version(pack)
    baseline = args.baseline or str(pack_version.get("baseline") or "")
    channel = args.channel or str(pack_version.get("channel") or "") or "baseline"
    if str(pack_version.get("version") or "") != args.version:
        print("[warn] 版本号与完整包不一致(包 %s,本次 %s),确认无误再上传。"
              % (pack_version.get("version") or "(空)", args.version))

    # 小文件直接复制(名字保持与 Release 附件约定一致)
    for path in (plugin_dll, stories, launcher_exe, seed_bin, seed_hash):
        target = _copy_file(path, out_dir)
        print("[copy] %s(%.1f MB)" % (os.path.basename(path),
                                      os.path.getsize(target) / 1048576.0))

    preview_zip = os.path.join(out_dir, "previews.zip")
    preview_count = _zip_dir(previews, preview_zip)
    print("[zip] previews.zip:%d 张封面(%.1f MB)"
          % (preview_count, os.path.getsize(preview_zip) / 1048576.0))

    docs_paths = [os.path.join(DOCS_SRC, name) for name in core.PLAYER_DOC_NAMES[:-1]]
    docs_paths.append(CHECK_HEALTH)
    for path in docs_paths:
        if not os.path.isfile(path):
            return _fail("缺少玩家文档:%s" % path)
    docs_zip = os.path.join(out_dir, "player_docs.zip")
    _zip_files(docs_paths, docs_zip)
    print("[zip] player_docs.zip:%d 个文件" % len(docs_paths))
    print("[zip] master_data.zip:%d 个主数据文件(%.1f MB)"
          % (len(master_data["files"]), master_data["bytes"] / 1048576.0))

    version = {
        "version": args.version,
        "baseline": baseline,
        "channel": channel,
        "notes": args.notes,
        "plugin_version": core.plugin_file_version(pack),
        "plugin_md5": core.file_md5(plugin_dll),
        "stories_md5": core.file_md5(stories),
        "launcher_md5": core.file_md5(launcher_exe),
        "previews_zip_md5": core.file_md5(preview_zip),
        "player_docs_zip_md5": core.file_md5(docs_zip),
        "catalog_hash": core.catalog_hash_text(seed_hash),
        "catalog_bin_md5": core.file_md5(seed_bin),
        "catalog_hash_md5": core.file_md5(seed_hash),
        "master_data_url": "master_data.zip",
        "master_data_md5": master_data["zip_md5"],
        "master_data_files": master_data["files"],
    }

    names = ["version.json", "StoryViewer.dll", "stories.json",
             "DotabyssOfflineLauncher.exe", "previews.zip", "player_docs.zip",
             core.CATALOG_BIN_NAME, core.CATALOG_HASH_NAME]
    names.append("master_data.zip")

    if not args.no_client_body:
        body_files = pack_tools.client_body_files(pack)
        body = pack_tools.write_manifest_zip(
            pack, body_files, os.path.join(out_dir, "client_body.zip"), compress=True)
        version["client_body"] = body
        names.append("client_body.zip")
        print("[zip] client_body.zip:%d 个文件(%.1f MB)"
              % (len(body["files"]), body["bytes"] / 1048576.0))

    if args.caches_since:
        since = os.path.abspath(args.caches_since)
        if not os.path.isdir(core.cache_dir(since)):
            return _fail("旧完整包目录缺少 Caches:%s" % core.cache_dir(since))
        added = pack_tools.caches_added_files(pack, since)
        if added:
            delta = pack_tools.write_manifest_zip(
                pack, added, os.path.join(out_dir, "caches_update.zip"), compress=False)
            version["caches_added"] = delta
            names.append("caches_update.zip")
            print("[zip] caches_update.zip:%d 个 bundle 文件(%.1f MB)"
                  % (len(delta["files"]), delta["bytes"] / 1048576.0))
        else:
            print("[zip] 素材增量:相对旧包无新增(不产出 caches_update.zip)")

    with open(os.path.join(out_dir, "version.json"), "w", encoding="utf-8",
              newline="\n") as handle:
        json.dump(version, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("[gen] version.json:版本 %s,基线 %s,通道 %s,插件 %s"
          % (version["version"], version["baseline"] or "(空)", version["channel"],
             version["plugin_version"]))

    print("\n[upload] 把下列文件作为同一个 Release(标签 %s)的附件上传:" % args.version)
    for name in names:
        print("  %s" % os.path.join(out_dir, name))
    print("\n示例(需已登录 gh):\n  gh release create %s --title \"离线包 %s\" "
          "--notes \"%s\" dist\\release_%s\\*"
          % (args.version, args.version, args.notes or "见 version.json", args.version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
