#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「ドットアビスX 离线版」完整包:整份 client + 启动器 + 玩家文档(可选打 zip)。

用法(开发机):
  D:\\Python\\python.exe build_full_pack.py                 # 复制 + 生成 + 校验(版本号默认当天)
  D:\\Python\\python.exe build_full_pack.py --zip           # 额外打 zip(约 8 GB,数分钟)
  D:\\Python\\python.exe build_full_pack.py --repo owner/repo
  D:\\Python\\python.exe build_full_pack.py --recopy        # 目标已存在也重抄一遍
  D:\\Python\\python.exe build_full_pack.py --baseline 20260924   # 重发时保持基线不变
  D:\\Python\\python.exe build_full_pack.py --catalog-bin <路径>  # 手动指定 catalog(默认自动取)

产出:
  <仓库>\\dist\\ドットアビスX离线版\\             完整包目录(交付根)
  <仓库>\\dist\\ドットアビスX离线版_<版本>.zip   --zip 时的压缩包

生成阶段会做两件"包级"修改:
  1) 身份隔离:把 ``_Data\\app.info`` 产品名改成 ``_offline`` 后缀
     (LocalLow 存档/缓存、注册表与在线版完全分开);
  2) catalog 种子:把本机 LocalLow 里最近一份 catalog 写入
     ``BepInEx/plugins/StoryViewer/catalog_seed``,新机器首启时由启动器播种到
     LocalLow(插件也优先读种子)。

排除的开发产物:日志、备份、开发截图(shots)、抓包目录(capture)、
Python 残留、以及需要"重新生成"的 dotabyss.storyviewer.cfg /
offline_version.json / launcher.json。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dotabyss_offline_core as core  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_SRC = os.path.join(REPO, "client")
DEFAULT_DIST = os.path.join(REPO, "dist")
PACK_NAME = "ドットアビスX离线版"
DOCS_SRC = os.path.join(REPO, "tools", "launcher", "player_docs")
PLAYER_DOC_TEXTS = ("使用说明.md", "安装排障.md", "启动器使用说明.txt")

# robocopy 排除:目录按绝对路径传 /XD,文件按名字通配传 /XF
EXCLUDE_DIRS = (
    os.path.join("BepInEx", "capture"),
    os.path.join("BepInEx", "plugins", "StoryViewer", "shots"),
    "__pycache__",
)
EXCLUDE_FILES = (
    "*.log", "*.bak*", "*.new", "*.pdb", "*.py", "*.pyc", "update_*.zip",
    core.CONFIG_REL[-1],       # dotabyss.storyviewer.cfg → 重新生成玩家默认档
    core.VERSION_NAME,         # offline_version.json → 重新生成
    core.LAUNCHER_JSON_NAME,   # launcher.json → 重新生成
)
# 玩家默认配置覆盖(开发档里 LogPatches/SkipDebug 是 true,发布关闭)
PLAYER_CFG_OVERRIDES = {
    "LogPatches": "false",
    "SkipDebug": "false",
    "ErrorPopupLog": "true",
}


def _run(cmd: list) -> int:
    """执行外部命令并返回退出码(打印命令,便于复核)。"""
    print("[run]", subprocess.list2cmdline(cmd))
    return subprocess.call(cmd)


def _fail(message: str) -> None:
    """打印失败原因并退出(打包失败不产出半成品交付说明)。"""
    print("[ABORT] " + message)
    raise SystemExit(1)


# ---------------------------------------------------------------- 前置检查

def check_source(src: str) -> None:
    """源目录是否具备打包条件(缺任一项直接中止)。"""
    required = [
        (os.path.join(src, core.EXE_NAME), "游戏主程序"),
        (os.path.join(src, "winhttp.dll"), "BepInEx 注入入口"),
        (os.path.join(src, "BepInEx", "core"), "BepInEx 运行时"),
        (core.plugin_dll_path(src), "StoryViewer.dll"),
        (core.stories_path(src), "stories.json"),
        (core.previews_dir(src), "previews 目录"),
        (core.launcher_path(src), "DotabyssOfflineLauncher.exe(先跑 freeze_launcher.ps1)"),
        (core.cache_dir(src), "_Data/Caches 缓存"),
        (core.config_path(src), "StoryViewer 配置"),
        (core.app_info_path(src), "_Data/app.info(身份文件)"),
    ]
    for path, label in required:
        if not os.path.exists(path):
            _fail("源目录缺少 %s:%s" % (label, path))
    stories = core._stories_status(core.stories_path(src))
    if not stories[0]:
        _fail("源 stories.json 不合格:%s" % stories[1])
    preview_count = len(os.listdir(core.previews_dir(src)))
    if preview_count < 100:
        _fail("源 previews 只有 %d 张(疑似不完整)" % preview_count)
    cache_count = core.cache_entry_count(src)
    if cache_count < core.CACHE_MIN_ENTRIES:
        _fail("源 Caches 只有 %d 个条目(需 ≥%d,缓存不完整)" % (cache_count, core.CACHE_MIN_ENTRIES))
    for name in PLAYER_DOC_TEXTS:
        if not os.path.isfile(os.path.join(DOCS_SRC, name)):
            _fail("缺少玩家文档:%s" % os.path.join(DOCS_SRC, name))
    if not os.path.isfile(os.path.join(REPO, "tools", "launcher", "check_health.bat")):
        _fail("缺少检查脚本 tools/launcher/check_health.bat")
    if not core.read_identity(src)[1]:
        _fail("源 _Data/app.info 无法解析(应有两行:公司名、产品名)")
    print("[check] 源目录自检通过(Caches %d 条目、presviews %d 张)" % (cache_count, preview_count))


# ---------------------------------------------------------------- 复制

def copy_layer(src: str, out_dir: str) -> None:
    """robocopy 复制客户端到包目录(排除开发产物)。"""
    cmd = ["robocopy", src, out_dir, "/E", "/MT:16", "/R:2", "/W:2",
           "/NFL", "/NDL", "/NP", "/NJH", "/NJS"]
    for directory in EXCLUDE_DIRS:
        cmd += ["/XD", os.path.join(src, directory)]
    for name in EXCLUDE_FILES:
        cmd += ["/XF", name]
    code = _run(cmd)
    if code >= 8:
        _fail("robocopy 失败,退出码 %d" % code)
    print("[copy] robocopy 完成(退出码 %d:0=无变化,1=已复制,<8 均正常)" % code)


# ---------------------------------------------------------------- 生成物

def write_player_config(out_dir: str, src: str) -> str:
    """从源配置生成玩家默认配置(离线键 + 关闭排查日志 + 刷新头注释版本)。

    返回:写入的插件版本(取自 DLL,读不到则保留原文案),供日志打印。
    """
    src_cfg = core.config_path(src)
    dst_cfg = core.config_path(out_dir)
    os.makedirs(os.path.dirname(dst_cfg), exist_ok=True)
    shutil.copy2(src_cfg, dst_cfg)
    core.repair_config(out_dir, extra_defaults=PLAYER_CFG_OVERRIDES)
    plugin_version = core.plugin_file_version(src)
    if plugin_version:
        with open(dst_cfg, "r", encoding="utf-8") as handle:
            text = handle.read()
        text = re.sub(r"(created by plugin StoryViewer v)[\d.]+",
                      r"\g<1>%s" % plugin_version, text, count=1)
        with open(dst_cfg, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    return plugin_version


def write_identity(out_dir: str) -> str:
    """把包内 app.info 设为离线身份(产品名 ``_offline`` 后缀)。

    说明:``app.info.bak_original`` 属于开发机备份,不进包(打包后清掉)。
    """
    message = core.ensure_offline_identity(out_dir)
    if "_offline" not in message:
        _fail("身份隔离失败:%s" % message)
    backup = core.app_info_path(out_dir) + ".bak_original"
    if os.path.isfile(backup):
        os.remove(backup)
    return message


def write_catalog_seed(out_dir: str, src: str, catalog_bin: str = "") -> str:
    """从源 LocalLow(或 ``--catalog-bin`` 指定文件)取 catalog 写入包内种子。

    说明:写入前清空包内种子目录,不写 ``.bak_*``(交付目录不允许备份残留)。
    """
    if catalog_bin:
        pair = (os.path.abspath(catalog_bin), core._find_hash_file(os.path.abspath(catalog_bin)))
    else:
        pair = core.source_catalog_pair(src)
    if not pair[0]:
        _fail("找不到 catalog 源(LocalLow 里没有 *.bin;可用 --catalog-bin 指定)")
    seed_dir = core.catalog_seed_dir(out_dir)
    if os.path.isdir(seed_dir):
        shutil.rmtree(seed_dir)
    return core.write_catalog_seed(out_dir, pair[0], pair[1], backup=False)


# 附属运行时文件:新机器缺省时由启动器补种(只补缺失、不覆盖)。
LOCAL_LOW_EXTRA_FILES = ("AbsfRuntimeConfig.dat",)
LOCAL_LOW_MASTER_DATA_DIR = "DownloadCache"


def _master_data_files(src: str) -> list:
    """返回在线优先的 LocalLow 主数据文件路径列表。"""
    app_dirs = [os.path.dirname(path) for path in core.local_low_catalog_dirs(src)]
    for app_dir in reversed(app_dirs):
        source_dir = os.path.join(app_dir, LOCAL_LOW_MASTER_DATA_DIR)
        if not os.path.isdir(source_dir):
            continue
        files = [os.path.join(source_dir, name) for name in sorted(os.listdir(source_dir))
                 if name.lower().endswith(".dat")
                 and os.path.isfile(os.path.join(source_dir, name))]
        if files:
            return files
    return []


def write_local_low_seed(out_dir: str, src: str) -> list:
    """把源机 LocalLow 的运行时文件与主数据放进包内种子目录。

    ``DownloadCache/*.dat`` 是游戏 ``MasterDataStore`` 的首下磁盘缓存;
    不播种它时,新机器会在 ``MBuildings`` 等依赖主数据的路径上失败。
    """
    app_dirs = [os.path.dirname(path) for path in core.local_low_catalog_dirs(src)]
    copied = []
    target_dir = core.local_low_seed_dir(out_dir)
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
    for name in LOCAL_LOW_EXTRA_FILES:
        for app_dir in app_dirs:
            path = os.path.join(app_dir, name)
            if not os.path.isfile(path):
                continue
            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(path, os.path.join(target_dir, name))
            copied.append(name)
            break
    # 优先在线身份目录:离线目录可能残留旧版主数据,不能遮蔽在线新版缓存。
    for source in _master_data_files(src):
        name = os.path.basename(source)
        os.makedirs(os.path.join(target_dir, LOCAL_LOW_MASTER_DATA_DIR), exist_ok=True)
        shutil.copy2(source, os.path.join(target_dir, LOCAL_LOW_MASTER_DATA_DIR, name))
        copied.append(os.path.join(LOCAL_LOW_MASTER_DATA_DIR, name).replace("\\", "/"))
    return copied


def write_version_and_repo(out_dir: str, version: str, repo: str, src: str,
                           baseline: str, channel: str) -> dict:
    """写 offline_version.json 与 launcher.json,返回版本元数据。"""
    plugin_version = core.plugin_file_version(src)
    seed_bin, seed_hash = core.seed_catalog_pair(out_dir)
    data = {
        "version": version,
        "baseline": baseline or version,
        "channel": channel or "baseline",
        "plugin_version": plugin_version,
        "plugin_md5": core.file_md5(core.plugin_dll_path(out_dir)),
        "stories_md5": core.file_md5(core.stories_path(out_dir)),
        "launcher_md5": core.file_md5(core.launcher_path(out_dir)),
        "catalog_hash": core.catalog_hash_text(seed_hash),
        "catalog_bin_md5": core.file_md5(seed_bin) if seed_bin else "",
        "first_ready": False,
    }
    core.save_version(out_dir, data)
    with open(core.launcher_json_path(out_dir), "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"github_repo": repo}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return data


def copy_player_files(out_dir: str) -> None:
    """复制玩家文档与 check_health.bat 到包根。"""
    for name in PLAYER_DOC_TEXTS:
        shutil.copy2(os.path.join(DOCS_SRC, name), os.path.join(out_dir, name))
        print("[docs] %s" % name)
    bat_src = os.path.join(REPO, "tools", "launcher", "check_health.bat")
    shutil.copy2(bat_src, os.path.join(out_dir, "check_health.bat"))
    print("[docs] check_health.bat")


# ---------------------------------------------------------------- 校验

def _is_forbidden(rel_path: str) -> bool:
    """相对路径是否命中"绝不能进包"的规则(开发产物/临时文件)。"""
    name = os.path.basename(rel_path)
    lower = name.lower()
    if lower.endswith((".py", ".pyc", ".pdb", ".new", ".log")):
        return True
    if ".bak" in lower:
        return True
    parts = rel_path.replace("\\", "/").lower().split("/")
    if "shots" in parts or "capture" in parts or "__pycache__" in parts:
        return True
    return False


def verify(out_dir: str, version: str, src: str) -> bool:
    """核对包内容:必需文件、缓存条目、生成物正确性、禁止文件扫描。"""
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        """打印一项校验结果并累计状态。"""
        nonlocal ok
        print("[check] %-34s %s%s" % (label, "OK" if passed else "MISSING/BAD",
                                      ("  " + detail) if detail else ""))
        ok = ok and passed

    check("主程序", os.path.isfile(os.path.join(out_dir, core.EXE_NAME)))
    check("winhttp.dll", os.path.isfile(os.path.join(out_dir, "winhttp.dll")))
    check("BepInEx 运行时", os.path.isdir(os.path.join(out_dir, "BepInEx", "core")))
    check("StoryViewer.dll", os.path.isfile(core.plugin_dll_path(out_dir)))
    check("stories.json", core._stories_status(core.stories_path(out_dir))[0])
    preview_count = len(os.listdir(core.previews_dir(out_dir))) \
        if os.path.isdir(core.previews_dir(out_dir)) else 0
    check("previews", preview_count >= 100, "%d 张" % preview_count)
    cache_count = core.cache_entry_count(out_dir)
    check("Caches", cache_count >= core.CACHE_MIN_ENTRIES, "%d 个条目" % cache_count)
    check("启动器 exe", os.path.isfile(core.launcher_path(out_dir)))
    for name in PLAYER_DOC_TEXTS + ("check_health.bat",):
        check("玩家文档 " + name, os.path.isfile(os.path.join(out_dir, name)))

    cfg_ok, cfg_detail = core.offline_config_status(out_dir)
    check("离线档配置", cfg_ok, cfg_detail)
    debug_ok = True
    cfg_text = ""
    if os.path.isfile(core.config_path(out_dir)):
        with open(core.config_path(out_dir), "r", encoding="utf-8") as handle:
            cfg_text = handle.read()
    for key, expected in PLAYER_CFG_OVERRIDES.items():
        if not re.search(r"^\s*%s\s*=\s*%s\s*$" % (key, expected), cfg_text,
                         re.IGNORECASE | re.MULTILINE):
            debug_ok = False
    check("玩家默认(排查日志关闭)", debug_ok)

    repo = core.read_github_repo(out_dir)
    check("launcher.json", os.path.isfile(core.launcher_json_path(out_dir)),
          "github_repo=%s" % (repo or "(空)") if repo is not None else "")
    data = core.load_version(out_dir)
    check("offline_version.json", data.get("version") == version,
          "version=%s plugin=%s" % (data.get("version"), data.get("plugin_version")))
    check("first_ready 待首启", data.get("first_ready") is False)

    _company, product = core.read_identity(out_dir)
    check("离线身份(_offline)", bool(product) and product.endswith(core.IDENTITY_SUFFIX),
          product or "(app.info 缺失)")
    seed_bin, seed_hash = core.seed_catalog_pair(out_dir)
    check("catalog 种子", bool(seed_bin) and bool(seed_hash),
          core.catalog_hash_text(seed_hash)[:12])
    check("catalog_hash 一致", bool(seed_hash)
          and data.get("catalog_hash") == core.catalog_hash_text(seed_hash))
    check("baseline 已冻结", bool(data.get("baseline")), data.get("baseline") or "(空)")
    check("channel", bool(data.get("channel")), data.get("channel") or "(空)")
    check("无身份备份残留", not os.path.isfile(core.app_info_path(out_dir) + ".bak_original"))
    seed_root = core.local_low_seed_dir(out_dir)
    extras = []
    for root, _dirs, names in os.walk(seed_root) if os.path.isdir(seed_root) else []:
        for name in names:
            extras.append(os.path.relpath(os.path.join(root, name), seed_root).replace("\\", "/"))
    print("[check] %-34s %s" % ("附属种子(可选)", "、".join(extras) if extras else "(无)"))

    leaks = []
    total_bytes = 0
    file_count = 0
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, out_dir)
            total_bytes += os.path.getsize(path)
            file_count += 1
            if _is_forbidden(rel):
                leaks.append(rel)
    check("无开发产物泄漏", not leaks, "%d 处" % len(leaks))
    for rel in leaks[:20]:
        print("        LEAK", rel)
    print("[stats] %d 个文件,合计 %.2f GB" % (file_count, total_bytes / (1 << 30)))
    return ok


# ---------------------------------------------------------------- zip

def make_zip(out_dir: str, zip_path: str) -> None:
    """把包目录压成 zip(已压缩内容用 STORED,速度优先;启用 zip64)。"""
    print("[zip] 写入 %s(约 8 GB,请耐心等待)…" % zip_path)
    started = time.time()
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        for root, _dirs, files in os.walk(out_dir):
            for name in files:
                path = os.path.join(root, name)
                rel = os.path.relpath(path, out_dir).replace("\\", "/")
                archive.write(path, PACK_NAME + "/" + rel)
                count += 1
                if count % 5000 == 0:
                    print("[zip]   %d 个文件…" % count)
    size = os.path.getsize(zip_path)
    print("[zip] 完成:%d 个文件,%.2f GB,用时 %.0f 秒"
          % (count, size / (1 << 30), time.time() - started))


# ---------------------------------------------------------------- 入口

def main() -> int:
    """命令行入口:复制 → 生成 → 校验 →(可选)压缩。"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="构建ドットアビスX 离线版完整包")
    parser.add_argument("--src", default=DEFAULT_SRC, help="源 client 目录")
    parser.add_argument("--dist", default=DEFAULT_DIST, help="输出根目录(默认 <仓库>/dist)")
    parser.add_argument("--version", default=time.strftime("%Y%m%d"), help="离线包版本号")
    parser.add_argument("--baseline", default="", help="基线版本号(默认=本包版本;重发保持旧基线)")
    parser.add_argument("--channel", default="baseline", help="更新通道(默认 baseline)")
    parser.add_argument("--catalog-bin", default="", help="手动指定 catalog bin(默认自动取 LocalLow 最近一份)")
    parser.add_argument("--repo", default="", help="GitHub 仓库 owner/name(写入 launcher.json)")
    parser.add_argument("--recopy", action="store_true", help="目标已存在也重抄")
    parser.add_argument("--zip", action="store_true", help="额外打 zip")
    args = parser.parse_args()

    src = os.path.abspath(args.src)
    out_dir = os.path.join(os.path.abspath(args.dist), PACK_NAME)
    if not os.path.isdir(src):
        _fail("源目录不存在:%s" % src)

    check_source(src)
    os.makedirs(os.path.abspath(args.dist), exist_ok=True)

    already = os.path.isfile(os.path.join(out_dir, core.EXE_NAME))
    if already and not args.recopy:
        print("[resume] 目标已存在,跳过 robocopy(要重抄加 --recopy)")
    else:
        copy_layer(src, out_dir)

    plugin_version = write_player_config(out_dir, src)
    print("[identity] %s" % write_identity(out_dir))
    print("[catalog] %s" % write_catalog_seed(out_dir, src, args.catalog_bin))
    extras = write_local_low_seed(out_dir, src)
    print("[seed] %s" % ("、".join(extras) if extras else "(无附属种子,可忽略)"))
    repo = args.repo or core.read_github_repo(src)
    data = write_version_and_repo(out_dir, args.version, repo, src,
                                  args.baseline, args.channel)
    copy_player_files(out_dir)
    print("[gen] 插件 v%s,版本 %s,基线 %s,仓库 %s"
          % (plugin_version or "(未知)", data["version"], data["baseline"], repo or "(未配置)"))

    if not verify(out_dir, args.version, src):
        _fail("校验未通过,修正后再打包(不要交付该目录)")

    if args.zip:
        zip_path = os.path.join(os.path.abspath(args.dist),
                                "%s_%s.zip" % (PACK_NAME, args.version))
        make_zip(out_dir, zip_path)
    print("[done] 完整包就绪:%s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
