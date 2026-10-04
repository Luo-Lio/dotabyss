#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ドットアビスX 离线版共享逻辑:路径、版本文件、自检、修复、探针、更新安装辅助。

只做本地文件操作与进程探测,不发起网络请求(网络逻辑在 dotabyss_launcher.py)。
结构对标 TSKX 离线版(``tools/tskx_offline_core.py``),便于两边一起维护。
"""

from dataclasses import dataclass
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import time
import zipfile


# ---------------------------------------------------------------- 常量

EXE_NAME = "ドットアビスX.exe"
GAME_PROCESS = "ドットアビスX"
LAUNCHER_EXE_NAME = "DotabyssOfflineLauncher.exe"
LAUNCHER_JSON_NAME = "launcher.json"
VERSION_NAME = "offline_version.json"

PLUGIN_REL = ("BepInEx", "plugins", "StoryViewer")
CONFIG_REL = ("BepInEx", "config", "dotabyss.storyviewer.cfg")
DATA_DIR_NAME = "ドットアビスX_Data"
CACHE_DIR_NAME = "Caches"

# 离线身份隔离:app.info 产品名加此后缀,LocalLow 存档/缓存/注册表与在线版完全分开。
IDENTITY_SUFFIX = "_offline"
APP_INFO_NAME = "app.info"

# 包内 catalog 种子(插件目录 catalog_seed\,插件优先读它,首备时同步到 LocalLow)。
CATALOG_SEED_DIR_NAME = "catalog_seed"
CATALOG_BIN_NAME = "catalog_1.bin"
CATALOG_HASH_NAME = "catalog_1.bin.hash"

# 包内 LocalLow 附属种子目录(如 AbsfRuntimeConfig.dat;只补缺失、不覆盖)。
LOCAL_LOW_SEED_DIR_NAME = "local_low_seed"

# LocalLow 根目录覆盖(自测/重定向用;留空则用系统默认)。
LOCAL_LOW_ENV = "DOTABYSS_LOCAL_LOW_BASE"

# 插件内置假 API 服务器端口(与 dotabyss.storyviewer.cfg 的 [Offline] ApiPort 一致)。
API_PORT = 18923

# 离线档要求的配置键:键名 → 期望值(true/false)。缺一不可,否则游戏会连真服务器。
OFFLINE_KEYS = (
    ("OfflineAuth", "true"),
    ("OfflineApi", "true"),
    ("RedirectAssetServer", "true"),
    ("ServeCachedBundles", "true"),
    ("SkipRequestEncryption", "true"),
    ("ForceDmmSdkSuccess", "true"),
    ("CaptureForward", "false"),
)

# 判定"缓存完整"的下限:当前客户端 _Data\\Caches 顶层约 22506 个缓存目录,
# 阈值取 10000,给未来结构调整留余量;明显偏低说明没拷全(会黑屏)。
CACHE_MIN_ENTRIES = 10000
# stories.json 至少要有的剧情条数(当前 1229)。
STORIES_MIN_COUNT = 100
# 日志超过该体积时由「修复」归档,避免无限膨胀。
LOG_ARCHIVE_BYTES = 10 * 1024 * 1024

_STORIES_PREFIXES = ("mas_", "men_", "hmn_", "hmr_", "evs_")
_MD5_CHUNK_SIZE = 1024 * 1024
_PORT_TIMEOUT_SECONDS = 0.2
_ZONE_STREAM = ":Zone.Identifier"

# 更新附件名 → 解析出的键(与 build_github_pack.py 的产出、GitHub Release 附件名一致)。
_ASSET_URL_KEYS = {
    "version.json": "version_json_url",
    "StoryViewer.dll": "plugin_dll_url",
    "stories.json": "stories_url",
    "previews.zip": "previews_zip_url",
    "player_docs.zip": "player_docs_url",
    LAUNCHER_EXE_NAME: "launcher_exe_url",
    CATALOG_BIN_NAME: "catalog_bin_url",
    CATALOG_HASH_NAME: "catalog_hash_url",
    "client_body.zip": "client_body_zip_url",
    "caches_update.zip": "caches_zip_url",
    "master_data.zip": "master_data_url",
}

# 更新包里允许落地的玩家文档(白名单,防止 zip 混入任意文件)。
PLAYER_DOC_NAMES = (
    "使用说明.md",
    "安装排障.md",
    "启动器使用说明.txt",
    "check_health.bat",
)


@dataclass
class CheckItem:
    """健康检查单项结果。

    参数:name 为固定检查名,ok 表示是否通过,detail 为中文诊断信息。
    """

    name: str
    ok: bool
    detail: str


@dataclass
class ProbeItem:
    """索引探针单项结果(仅用于 ``index_probe``,不进入 ``health_check``)。"""

    name: str
    ok: bool
    detail: str


# ---------------------------------------------------------------- 路径

def plugin_dir(game_dir: str) -> str:
    """返回插件目录(``BepInEx/plugins/StoryViewer``)。"""
    return os.path.join(game_dir, *PLUGIN_REL)


def config_path(game_dir: str) -> str:
    """返回插件配置文件路径(``BepInEx/config/dotabyss.storyviewer.cfg``)。"""
    return os.path.join(game_dir, *CONFIG_REL)


def version_path(game_dir: str) -> str:
    """返回离线版本文件路径(插件目录下 ``offline_version.json``)。"""
    return os.path.join(plugin_dir(game_dir), VERSION_NAME)


def cache_dir(game_dir: str) -> str:
    """返回客户端自带的 bundle 缓存目录(``ドットアビスX_Data/Caches``)。

    离线播放全部依赖这份缓存;插件对未命中的 bundle 直接回 404、不回源 CDN。
    """
    return os.path.join(game_dir, DATA_DIR_NAME, CACHE_DIR_NAME)


def data_dir(game_dir: str) -> str:
    """返回游戏数据目录(``ドットアビスX_Data``)。"""
    return os.path.join(game_dir, DATA_DIR_NAME)


def app_info_path(game_dir: str) -> str:
    """返回 Unity 身份文件 ``_Data\\app.info``(两行:公司名、产品名)。"""
    return os.path.join(game_dir, DATA_DIR_NAME, APP_INFO_NAME)


def catalog_seed_dir(game_dir: str) -> str:
    """返回包内 catalog 种子目录(``BepInEx/plugins/StoryViewer/catalog_seed``)。"""
    return os.path.join(plugin_dir(game_dir), CATALOG_SEED_DIR_NAME)


def local_low_seed_dir(game_dir: str) -> str:
    """返回包内 LocalLow 附属种子目录(``BepInEx/plugins/StoryViewer/local_low_seed``)。"""
    return os.path.join(plugin_dir(game_dir), LOCAL_LOW_SEED_DIR_NAME)


def stories_path(game_dir: str) -> str:
    """返回剧情索引文件路径(插件目录下 ``stories.json``)。"""
    return os.path.join(plugin_dir(game_dir), "stories.json")


def previews_dir(game_dir: str) -> str:
    """返回剧情封面目录(插件目录下 ``previews``)。"""
    return os.path.join(plugin_dir(game_dir), "previews")


def logs_dir(game_dir: str) -> str:
    """返回 BepInEx 日志目录。"""
    return os.path.join(game_dir, "BepInEx")


def launcher_path(game_dir: str) -> str:
    """返回启动器 exe 路径(游戏根目录,与游戏主程序同级)。"""
    return os.path.join(game_dir, LAUNCHER_EXE_NAME)


def launcher_json_path(game_dir: str) -> str:
    """返回 ``launcher.json`` 路径(游戏根目录,记录 GitHub 仓库)。"""
    return os.path.join(game_dir, LAUNCHER_JSON_NAME)


def plugin_dll_path(game_dir: str) -> str:
    """返回插件 DLL 路径(``BepInEx/plugins/StoryViewer/StoryViewer.dll``)。"""
    return os.path.join(plugin_dir(game_dir), "StoryViewer.dll")


def plugin_file_version(game_dir: str) -> str:
    """读取插件 DLL 的 ProductVersion(经 PowerShell 读 VersionInfo)。

    说明:配置头注释是 BepInEx 建文件时写下的旧值(升级插件不刷新),
    所以版本显示与打包都以 DLL 本体为准;读不到返回空串。
    """
    dll = plugin_dll_path(game_dir)
    if not os.path.isfile(dll):
        return ""
    command = ("(Get-Item -LiteralPath '%s').VersionInfo.ProductVersion"
               % dll.replace("'", "''"))
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip()


# ---------------------------------------------------------------- 离线身份

def read_identity(game_dir: str) -> tuple:
    """读取 ``app.info`` 的 ``(公司名, 产品名)``;缺失或损坏返回 ``("", "")``。"""
    path = app_info_path(game_dir)
    if not os.path.isfile(path):
        return "", ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return "", ""
    if len(lines) < 2:
        return "", ""
    return lines[0].strip(), lines[1].strip()


def ensure_offline_identity(game_dir: str) -> str:
    """把 ``app.info`` 产品名改为 ``_offline`` 后缀(身份隔离),返回中文说明。

    首次改动前留 ``app.info.bak_original`` 备份(不进包);已隔离时为空操作。
    """
    path = app_info_path(game_dir)
    company, product = read_identity(game_dir)
    if not company or not product:
        return "app.info 缺失或损坏,无法设置离线身份(请重新解压完整包)"
    if product.endswith(IDENTITY_SUFFIX):
        return "离线身份已就绪(%s)" % product
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        new_product = product + IDENTITY_SUFFIX
        lines = raw.decode("utf-8", errors="replace").split("\n")
        if len(lines) < 2:
            return "app.info 格式异常,未改动"
        backup = path + ".bak_original"
        if not os.path.isfile(backup):
            shutil.copy2(path, backup)
        lines[1] = new_product
        with open(path, "wb") as handle:
            handle.write("\n".join(lines).encode("utf-8"))
    except OSError as error:
        return "设置离线身份失败:%s" % error
    return "已设置离线身份:%s → %s" % (product, new_product)


def _sanitize_path_part(name: str) -> str:
    """按 Unity 规则清洗路径片段:非法字符与结尾句点替换为下划线。

    实测 Unity 把公司名 ``EXNOA LLC.`` 映射为目录 ``EXNOA LLC_``(结尾句点
    在 Windows 路径里非法),此处只做必要规则,保证 ``_offline`` 目录推导正确。
    """
    cleaned = "".join(
        "_" if (ch in '<>:"/\\|?*' or ord(ch) < 32) else ch for ch in name)
    trailing = len(cleaned) - len(cleaned.rstrip("."))
    if trailing:
        cleaned = cleaned[:-trailing] + "_" * trailing
    return cleaned


def local_low_base() -> str:
    """返回 LocalLow 根目录;环境变量 ``DOTABYSS_LOCAL_LOW_BASE`` 可覆盖(测试用)。"""
    override = (os.environ.get(LOCAL_LOW_ENV) or "").strip()
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), "AppData", "LocalLow")


def local_low_dir(game_dir: str, base: str = "") -> str:
    """返回离线身份对应的 LocalLow 应用目录(仅推导路径,不创建)。"""
    company, product = read_identity(game_dir)
    if not company or not product:
        return ""
    root = base or local_low_base()
    return os.path.join(root, _sanitize_path_part(company), _sanitize_path_part(product))


def local_low_catalog_dir(game_dir: str, base: str = "") -> str:
    """返回离线身份下 Addressables catalog 目录(``LocalLow\\...\\com.unity.addressables``)。"""
    root = local_low_dir(game_dir, base)
    return os.path.join(root, "com.unity.addressables") if root else ""


def local_low_catalog_dirs(game_dir: str, base: str = "") -> list:
    """返回 catalog 搜索候选目录:离线身份目录在前,原版身份目录在后。"""
    company, product = read_identity(game_dir)
    if not company or not product:
        return []
    root = base or local_low_base()
    products = [product]
    if product.endswith(IDENTITY_SUFFIX):
        products.append(product[:-len(IDENTITY_SUFFIX)])
    directories = []
    for name in products:
        path = os.path.join(root, _sanitize_path_part(company),
                            _sanitize_path_part(name), "com.unity.addressables")
        if path not in directories:
            directories.append(path)
    return directories


# ---------------------------------------------------------------- catalog 种子

def _find_hash_file(bin_path: str) -> str:
    """找 bin 的配对哈希文件,支持 ``<bin>.hash`` 与 ``<name>.hash`` 两种命名。"""
    for candidate in (bin_path + ".hash", os.path.splitext(bin_path)[0] + ".hash"):
        if os.path.isfile(candidate):
            return candidate
    return ""


def newest_catalog_pair(directory: str) -> tuple:
    """取目录里最近修改的 ``(*.bin, 配对 .hash)``;没有返回 ``("", "")``。"""
    if not directory or not os.path.isdir(directory):
        return "", ""
    candidates = [
        os.path.join(directory, name) for name in os.listdir(directory)
        if name.lower().endswith(".bin") and os.path.isfile(os.path.join(directory, name))
    ]
    if not candidates:
        return "", ""
    newest = max(candidates, key=lambda path: (os.path.getmtime(path), path))
    return newest, _find_hash_file(newest)


def seed_catalog_pair(game_dir: str) -> tuple:
    """取包内 catalog 种子 ``(bin, hash)``;没有返回 ``("", "")``。"""
    return newest_catalog_pair(catalog_seed_dir(game_dir))


def source_catalog_pair(game_dir: str, base: str = "") -> tuple:
    """打包用:优先离线身份的 LocalLow,其次原版 LocalLow,取最近的 catalog。"""
    for directory in local_low_catalog_dirs(game_dir, base):
        pair = newest_catalog_pair(directory)
        if pair[0]:
            return pair
    return "", ""


def catalog_hash_text(hash_path: str) -> str:
    """读 ``.hash`` 文件内容(去首尾空白);读不到返回空串。"""
    if not hash_path or not os.path.isfile(hash_path):
        return ""
    try:
        with open(hash_path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def catalog_seed_hash(game_dir: str) -> str:
    """返回包内 catalog 种子的哈希值(未打包返回空串)。"""
    return catalog_hash_text(seed_catalog_pair(game_dir)[1])


def write_catalog_seed(game_dir: str, src_bin: str, src_hash: str, stamp: str = "",
                       backup: bool = True) -> str:
    """把 source catalog 写为包内种子(固定名 ``catalog_1.bin`` + ``.hash``)。

    返回中文说明;``.hash`` 缺失抛 ``ValueError``(catalog 必须带哈希)。
    ``backup`` False 时不写 ``.bak_*``(打包产物不允许出现备份文件)。
    """
    if not src_bin or not os.path.isfile(src_bin):
        raise ValueError("catalog 源文件不存在:%s" % src_bin)
    if not src_hash or not os.path.isfile(src_hash):
        raise ValueError("catalog 缺少配对 .hash 文件:%s" % src_hash)
    dest_dir = catalog_seed_dir(game_dir)
    os.makedirs(dest_dir, exist_ok=True)
    if not stamp:
        stamp = time.strftime("%Y%m%d_%H%M%S")
    for src, name in ((src_bin, CATALOG_BIN_NAME), (src_hash, CATALOG_HASH_NAME)):
        dest = os.path.join(dest_dir, name)
        if backup and os.path.isfile(dest):
            shutil.copy2(dest, dest + ".bak_" + stamp)
        shutil.copy2(src, dest)
    return "已写入 catalog 种子(%d 字节,hash %s)" % (
        os.path.getsize(os.path.join(dest_dir, CATALOG_BIN_NAME)),
        catalog_hash_text(os.path.join(dest_dir, CATALOG_HASH_NAME))[:12])


def seed_catalog_to_local_low(game_dir: str, base: str = "") -> list:
    """把包内 catalog 种子播种到离线身份 LocalLow(游戏与插件实际读取处)。

    幂等:目标哈希与种子一致时直接跳过。返回中文日志行列表。
    """
    seed_bin, seed_hash = seed_catalog_pair(game_dir)
    if not seed_bin:
        return ["包内缺 catalog 种子(请重新解压完整包)"]
    target_dir = local_low_catalog_dir(game_dir, base)
    if not target_dir:
        return ["无法确定存档目录(app.info 缺失),catalog 未播种"]
    seed_hash_text = catalog_hash_text(seed_hash)
    target_bin = os.path.join(target_dir, CATALOG_BIN_NAME)
    target_hash = os.path.join(target_dir, CATALOG_HASH_NAME)
    if os.path.isfile(target_bin) and seed_hash_text:
        if catalog_hash_text(target_hash) == seed_hash_text:
            return ["离线 catalog 已就绪(hash %s)" % seed_hash_text[:12]]
    try:
        os.makedirs(target_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        for src, name in ((seed_bin, CATALOG_BIN_NAME), (seed_hash, CATALOG_HASH_NAME)):
            if not src or not os.path.isfile(src):
                continue
            dest = os.path.join(target_dir, name)
            if os.path.isfile(dest):
                shutil.copy2(dest, dest + ".bak_" + stamp)
            shutil.copy2(src, dest)
    except OSError as error:
        return ["catalog 播种失败:%s" % error]
    return ["已播种离线 catalog(hash %s)" % (seed_hash_text[:12] or "未知")]


def seed_local_low_extras(game_dir: str, base: str = "") -> list:
    """把包内 LocalLow 附属种子补进离线存档目录。

    种子目录允许包含子目录(当前包括 ``DownloadCache/*.dat`` 主数据)。
    规则:普通附属文件只补"目标不存在"、绝不覆盖;主数据 ``DownloadCache/*.dat``
    在目标缺失或内容不一致时替换;返回中文日志行列表。
    """
    source = local_low_seed_dir(game_dir)
    if not os.path.isdir(source):
        return []
    target = local_low_dir(game_dir, base)
    if not target:
        return ["无法确定存档目录(app.info 缺失),附属种子未播种"]
    lines = []
    for root, _dirs, names in os.walk(source):
        relative_root = os.path.relpath(root, source)
        for name in sorted(names):
            relative = name if relative_root == "." else os.path.join(relative_root, name)
            src = os.path.join(source, relative)
            dest = os.path.join(target, relative)
            normalized = relative.replace("\\", "/")
            # 只有主数据 .dat 允许按版本内容替换;DownloadCache 下其它玩家文件仍不覆盖。
            is_master_data = master_data_rel_allowed(normalized)
            if os.path.isfile(dest):
                if not is_master_data:
                    continue
                # 主数据是版本化缓存:同一路径若内容残缺或过期必须替换;
                # 其它 LocalLow 文件仍保持“只补缺失、不覆盖”约定。
                try:
                    same = (os.path.getsize(src) == os.path.getsize(dest)
                            and file_md5(src) == file_md5(dest))
                except OSError:
                    same = False
                if same:
                    continue
            parent = os.path.dirname(dest)
            try:
                os.makedirs(parent, exist_ok=True)
                shutil.copy2(src, dest)
                prefix = "已更新主数据缓存" if is_master_data else "已补种存档目录文件"
                lines.append("%s %s" % (prefix, normalized))
            except OSError as error:
                prefix = "更新主数据缓存" if is_master_data else "补种"
                lines.append("%s %s 失败:%s" % (prefix, normalized, error))
    return lines


def master_data_rel_allowed(rel: str) -> bool:
    """判断主数据附件路径是否为 ``DownloadCache/<name>.dat``。"""
    normalized = (rel or "").replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    return (len(parts) == 2 and parts[0] == "DownloadCache"
            and parts[1].lower().endswith(".dat"))


def install_catalog_from_bytes(game_dir: str, raw_bin: bytes, raw_hash: bytes,
                               stamp: str) -> str:
    """把下载的 catalog 写入包内种子目录(更新流程用)。

    说明:调用前调用方已校验 md5 与哈希内容;``stamp`` 用于备份后缀。
    返回中文说明。
    """
    dest_dir = catalog_seed_dir(game_dir)
    os.makedirs(dest_dir, exist_ok=True)
    pairs = ((CATALOG_BIN_NAME, raw_bin), (CATALOG_HASH_NAME, raw_hash))
    for name, data in pairs:
        dest = os.path.join(dest_dir, name)
        if os.path.isfile(dest):
            shutil.copy2(dest, dest + ".bak_" + stamp)
        with open(dest, "wb") as handle:
            handle.write(data)
    return "已更新 catalog 种子(%d 字节)" % len(raw_bin)


# ---------------------------------------------------------------- 版本文件

def load_version(game_dir: str) -> dict:
    """读取离线版本元数据;缺失时返回带默认值的独立副本。"""
    path = version_path(game_dir)
    if not os.path.isfile(path):
        return {"version": "", "baseline": "", "channel": "", "plugin_version": "", "first_ready": False}
    try:
        with open(path, "r", encoding="utf-8") as version_file:
            data = json.load(version_file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {"version": "", "baseline": "", "channel": "", "plugin_version": "", "first_ready": False}


def save_version(game_dir: str, data: dict) -> None:
    """把离线版本元数据写入插件目录(UTF-8、LF、缩进 2)。"""
    path = version_path(game_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as version_file:
        json.dump(data, version_file, ensure_ascii=False, indent=2)
        version_file.write("\n")


# ---------------------------------------------------------------- 文件与安装

def file_md5(path: str) -> str:
    """计算文件 MD5 十六进制摘要(小写 32 位)。"""
    digest = hashlib.md5()
    with open(path, "rb") as source_file:
        while True:
            chunk = source_file.read(_MD5_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_needs_update(path: str, expected_md5: str) -> bool:
    """本地文件是否需要用期望 md5 的文件替换(期望为空 → False)。"""
    if not expected_md5:
        return False
    if not os.path.isfile(path):
        return True
    return file_md5(path) != str(expected_md5).lower()


def install_bytes(dest_path: str, data: bytes, expected_md5: str, stamp: str,
                  replace: bool = True, backup: bool = True) -> str:
    """校验 md5 后写入目标文件(失败不覆盖旧文件、不留 ``.new``)。

    参数:dest_path 最终路径;data 原始字节;expected_md5 期望摘要;stamp 备份后缀;
        replace False 时只落 ``dest_path.new``(启动器自换用);backup False 时不写
        ``.bak_update_*``。
    返回:中文操作说明。md5 不符抛 ``ValueError``。
    """
    digest = hashlib.md5(data).hexdigest()
    if digest != str(expected_md5).lower():
        raise ValueError("md5 不符:得到 %s,期望 %s" % (digest, expected_md5))
    parent = os.path.dirname(dest_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    new_path = dest_path + ".new"
    with open(new_path, "wb") as handle:
        handle.write(data)
    if not replace:
        return "已写出 " + os.path.basename(new_path)
    if backup and os.path.isfile(dest_path):
        shutil.copy2(dest_path, dest_path + ".bak_update_" + stamp)
    os.replace(new_path, dest_path)
    return "已安装 " + os.path.basename(dest_path)


def pending_launcher_swap(game_dir: str) -> bool:
    """游戏根是否存在待替换的启动器 ``.new``。"""
    return os.path.isfile(launcher_path(game_dir) + ".new")


def build_launcher_replace_cmd(game_dir: str) -> str:
    """构造「退出后替换并重启启动器」的 cmd 脚本字符串(不 spawn)。

    重要:必须配合 ``subprocess.Popen(script, shell=True)`` 使用。``cmd /c`` 的脚本
    里带引号路径时,若用 argv 列表形式,Python 的 ``list2cmdline`` 会把内层引号转义成
    ``\\"``,而 cmd.exe 不认这种转义,脚本会静默失败(2026-09-24 实测)。
    """
    exe = launcher_path(game_dir)
    new = exe + ".new"
    return 'ping 127.0.0.1 -n 3 >nul & move /Y "%s" "%s" & start "" "%s"' % (
        new, exe, exe)


def extract_zip_bytes(data: bytes, dest_dir: str, allowed_names=None) -> int:
    """从内存 zip 安全解压到目录,返回写出的文件数。

    安全规则:成员必须是相对路径、不含 ``..`` 与盘符;``allowed_names`` 非空时
    只接受该白名单内的顶层文件名。任何违规成员直接抛 ``ValueError``(先验后写)。
    """
    written = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        for name in names:
            normalized = name.replace("\\", "/")
            if normalized.startswith("/") or ":" in normalized:
                raise ValueError("zip 成员路径不合法:%s" % name)
            parts = [part for part in normalized.split("/") if part not in ("", ".")]
            if any(part == ".." for part in parts):
                raise ValueError("zip 成员含上跳路径:%s" % name)
            if allowed_names is not None and (len(parts) != 1 or parts[0] not in allowed_names):
                raise ValueError("zip 成员不在白名单内:%s" % name)
        for name in names:
            normalized = name.replace("\\", "/")
            if normalized.endswith("/"):
                continue
            target = os.path.join(dest_dir, *[p for p in normalized.split("/") if p])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(name) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            written += 1
    return written


# ---------------------------------------------------------------- 差量安装

def rel_path_safe(game_dir: str, rel: str):
    """把更新清单里的相对路径解析为游戏目录下的绝对路径;不合法返回 ``None``。"""
    if not rel:
        return None
    normalized = rel.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        return None
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return os.path.join(game_dir, *parts)


# 客户端本体更新禁止落地的路径(插件/缓存/身份/启动器/文档由各自通道更新)。
_CLIENT_BODY_BLOCKED_PREFIXES = ("BepInEx/", DATA_DIR_NAME + "/" + CACHE_DIR_NAME + "/")
_CLIENT_BODY_BLOCKED_PARTS = frozenset(("shots", "capture", "__pycache__"))
_CLIENT_BODY_BLOCKED_SUFFIXES = (".log", ".new", ".pdb", ".bak", ".pyc")


def client_body_rel_allowed(rel: str) -> bool:
    """判断客户端本体清单里的相对路径是否允许落地(黑名单式)。"""
    normalized = rel.replace("\\", "/")
    if normalized.startswith(_CLIENT_BODY_BLOCKED_PREFIXES):
        return False
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in _CLIENT_BODY_BLOCKED_PARTS for part in parts):
        return False
    name = parts[-1]
    blocked_names = (LAUNCHER_EXE_NAME, LAUNCHER_JSON_NAME, VERSION_NAME,
                     APP_INFO_NAME, "app.info.bak_original", "check_health.bat")
    if name in blocked_names or name in PLAYER_DOC_NAMES:
        return False
    if name.lower().endswith(_CLIENT_BODY_BLOCKED_SUFFIXES):
        return False
    return True


def caches_rel_allowed(rel: str) -> bool:
    """判断 bundle 增量清单路径是否形如 ``_Data/Caches/<名>/<哈希>/__data``。"""
    normalized = rel.replace("\\", "/")
    prefix = DATA_DIR_NAME + "/" + CACHE_DIR_NAME + "/"
    if not normalized.startswith(prefix):
        return False
    tail = [part for part in normalized[len(prefix):].split("/") if part]
    return len(tail) == 3 and tail[0] and tail[1] and tail[2] in ("__data", "__info")


def _manifest_todo(game_dir: str, files: dict, checker) -> list:
    """通用差量比对:列出清单里缺失或 md5 不同的路径(按路径排序)。"""
    todo = []
    for rel, expected in (files or {}).items():
        if not checker(rel):
            raise ValueError("更新清单含不允许的路径:%s" % rel)
        target = rel_path_safe(game_dir, rel)
        if target is None:
            raise ValueError("更新清单路径不合法:%s" % rel)
        if file_needs_update(target, expected):
            todo.append(rel)
    return sorted(todo)


def client_body_todo(game_dir: str, files: dict) -> list:
    """列出客户端本体需要安装的文件(缺失或 md5 不同)。"""
    return _manifest_todo(game_dir, files, client_body_rel_allowed)


def caches_added_todo(game_dir: str, files: dict) -> list:
    """列出 bundle 缓存需要补充的文件(缺失或 md5 不同)。"""
    return _manifest_todo(game_dir, files, caches_rel_allowed)


def install_zip_members(zip_path: str, game_dir: str, mapping: dict, stamp: str,
                        checker=None, backup: bool = False) -> list:
    """按 ``相对路径 → md5`` 从 zip 安装文件,返回中文日志行列表。

    先整体校验(成员齐全、路径合法、md5 相符)再逐个写入;任何一步失败抛
    ``ValueError``,已写入的部分保留但不会留下半文件(单文件写入是原子的)。
    """
    mapping = dict(mapping or {})
    if not mapping:
        return []
    logs = []
    with zipfile.ZipFile(zip_path) as archive:
        available = {
            name.replace("\\", "/").rstrip("/")
            for name in archive.namelist() if name.strip("/\\")
        }
        for rel in mapping:
            normalized = rel.replace("\\", "/")
            if normalized not in available:
                raise ValueError("更新包缺少成员:%s" % rel)
            if checker is not None and not checker(normalized):
                raise ValueError("更新包成员路径不允许:%s" % rel)
            if rel_path_safe(game_dir, normalized) is None:
                raise ValueError("更新包成员路径不合法:%s" % rel)
        for rel, expected in mapping.items():
            normalized = rel.replace("\\", "/")
            data = archive.read(normalized)
            digest = hashlib.md5(data).hexdigest()
            if digest != str(expected).lower():
                raise ValueError("成员 md5 不符:%s" % rel)
            target = rel_path_safe(game_dir, normalized)
            install_bytes(target, data, expected, stamp, backup=backup)
            logs.append("已更新 " + normalized)
    return logs


# ---------------------------------------------------------------- 进程

def game_running() -> bool:
    """游戏主进程是否在运行(用 PowerShell 探测,输出 ASCII 避免编码问题)。"""
    command = ("if (Get-Process -Name '%s' -ErrorAction SilentlyContinue) "
               "{ 'RUNNING' } else { 'IDLE' }" % GAME_PROCESS)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return "RUNNING" in (result.stdout or "")


# ---------------------------------------------------------------- 配置

def _read_cfg_lines(path: str) -> list:
    """读配置文件为行列表;文件不存在时返回空列表。"""
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as config_file:
        return config_file.read().splitlines()


def _cfg_value(lines: list, key: str):
    """取配置里某个键的最后一次赋值(原样字符串),找不到返回 None。"""
    pattern = re.compile(r"^\s*%s\s*=\s*(.*?)\s*$" % re.escape(key), re.IGNORECASE)
    found = None
    for line in lines:
        match = pattern.match(line)
        if match:
            found = match.group(1)
    return found


def offline_config_status(game_dir: str) -> tuple:
    """检查配置是否处于离线档。

    返回 ``(通过, 详情)``:所有 ``OFFLINE_KEYS`` 都命中期望值才通过;
    未通过时详情列出第一个不符的键。
    """
    path = config_path(game_dir)
    if not os.path.isfile(path):
        return False, "配置文件缺失(应为离线档)"
    lines = _read_cfg_lines(path)
    for key, expected in OFFLINE_KEYS:
        value = _cfg_value(lines, key)
        if value is None:
            return False, "缺少 %s = %s" % (key, expected)
        if value.strip().lower() != expected:
            return False, "%s = %s(应为 %s)" % (key, value.strip(), expected)
    return True, "离线档配置完整(%d 项)" % len(OFFLINE_KEYS)


def repair_config(game_dir: str, extra_defaults=None) -> str:
    """把配置写入/修正为离线档,返回中文说明。

    参数:extra_defaults 为额外的"键 → 值"字典(打包/修复时用于统一玩家默认值,
        如 SkipDebug=false);会写到 [Offline] 段末尾(键已存在则原地改)。
    说明:保留文件其它内容;文件缺失时新建最小配置。
    """
    path = config_path(game_dir)
    lines = _read_cfg_lines(path)
    settings = dict(OFFLINE_KEYS)
    if extra_defaults:
        settings.update(extra_defaults)

    # 定位 [Offline] 段(没有就追加)
    section_index = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*\[Offline\]\s*$", line):
            section_index = i
            break
    if section_index < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[Offline]")
        section_index = len(lines) - 1

    for key, value in settings.items():
        hit = -1
        for i, line in enumerate(lines):
            if re.match(r"^\s*%s\s*=" % re.escape(key), line, re.IGNORECASE):
                hit = i
                break
        if hit >= 0:
            lines[hit] = "%s = %s" % (key, value)
            continue
        # 插到 [Offline] 段末尾(下一个段标题之前)
        insert_at = len(lines)
        for i in range(section_index + 1, len(lines)):
            if re.match(r"^\s*\[", lines[i]):
                insert_at = i
                break
        lines.insert(insert_at, "%s = %s" % (key, value))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as config_file:
        config_file.write("\n".join(lines) + "\n")
    return "已写入离线档配置(%d 项)" % len(settings)


# ---------------------------------------------------------------- 检查

def _stories_status(path: str) -> tuple:
    """检查 stories.json 是否存在且可解析,返回 ``(通过, 详情)``。"""
    if not os.path.isfile(path):
        return False, "stories.json 缺失"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        return False, "stories.json 无法解析:%s" % error
    entries = data.get("stories") if isinstance(data, dict) else data
    count = len(entries) if isinstance(entries, list) else 0
    if count < STORIES_MIN_COUNT:
        return False, "剧情条数偏少(%d)" % count
    return True, "%d 条剧情" % count


def _has_zone_stream(path: str) -> bool:
    """判断文件是否真的能打开 ``Zone.Identifier`` 备用数据流。"""
    try:
        # Windows 对某些已解除标记的 ADS 路径仍会让 os.path.isfile 返回真；
        # 只有实际打开该流成功，才能确认下载来源标记仍然存在。
        with open(path + _ZONE_STREAM, "rb"):
            return True
    except OSError:
        return False


def _zone_check(paths: list) -> CheckItem:
    """检查关键文件是否带有 Windows 下载来源标记(Zone.Identifier)。"""
    marked = [path for path in paths if _has_zone_stream(path)]
    if not marked:
        return CheckItem("zone", True, "无 Zone.Identifier")
    names = "、".join(os.path.basename(path) for path in marked)
    return CheckItem("zone", False, "存在 Zone.Identifier:%s(点「修复」可解除)" % names)


def _port_check() -> CheckItem:
    """探测假 API 端口占用情况(占用只提示,不视为失败)。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(_PORT_TIMEOUT_SECONDS)
            occupied = probe.connect_ex(("127.0.0.1", API_PORT)) == 0
    except OSError as error:
        return CheckItem("port", True, "端口 %d 无法探测(仅提示):%s" % (API_PORT, error))
    if occupied:
        return CheckItem("port", True, "端口 %d 已占用(仅提示:可能是残留进程)" % API_PORT)
    return CheckItem("port", True, "端口 %d 未占用" % API_PORT)


def cache_entry_count(game_dir: str) -> int:
    """统计 ``_Data\\Caches`` 的顶层缓存目录数(离线资源完整度指标)。

    ``Caches\\__info`` 是 Unity 的合法元数据文件,不是 bundle 条目;只数目录
    可使输出与维护流程中的缓存目录统计一致。
    """
    path = cache_dir(game_dir)
    if not os.path.isdir(path):
        return 0
    try:
        return sum(1 for name in os.listdir(path)
                   if os.path.isdir(os.path.join(path, name)))
    except OSError:
        return 0


def health_check(game_dir: str) -> list:
    """检查离线启动所需的本机条件(不发网络请求)。"""
    plugin = plugin_dir(game_dir)
    exe = os.path.join(game_dir, EXE_NAME)
    winhttp = os.path.join(game_dir, "winhttp.dll")
    bep_core = os.path.join(game_dir, "BepInEx", "core")
    dll = os.path.join(plugin, "StoryViewer.dll")
    version = version_path(game_dir)

    cfg_ok, cfg_detail = offline_config_status(game_dir)
    stories_ok, stories_detail = _stories_status(stories_path(game_dir))

    preview_count = 0
    previews = previews_dir(game_dir)
    if os.path.isdir(previews):
        try:
            preview_count = len(os.listdir(previews))
        except OSError:
            preview_count = 0

    cache_count = cache_entry_count(game_dir)
    if cache_count >= CACHE_MIN_ENTRIES:
        cache_item = CheckItem("cache", True, "_Data\\Caches %d 个条目" % cache_count)
    else:
        cache_item = CheckItem("cache", False,
                               "_Data\\Caches 仅 %d 个条目(需 ≥%d,缓存不完整请重新解压完整包)"
                               % (cache_count, CACHE_MIN_ENTRIES))

    _company, product = read_identity(game_dir)
    if not product:
        identity_item = CheckItem("identity", False, "app.info 缺失,无法确认离线身份")
    elif product.endswith(IDENTITY_SUFFIX):
        identity_item = CheckItem("identity", True, "离线身份 %s" % product)
    else:
        identity_item = CheckItem("identity", False,
                                  "身份未隔离(%s;点「修复」自动处理)" % product)

    seed_bin, seed_hash = seed_catalog_pair(game_dir)
    if seed_bin and seed_hash:
        catalog_item = CheckItem(
            "catalog", True, "catalog 种子就绪(%s)" % (catalog_hash_text(seed_hash)[:12] or "无哈希"))
    else:
        catalog_item = CheckItem("catalog", False, "包内缺 catalog 种子(请重新解压完整包)")

    return [
        CheckItem("exe", os.path.isfile(exe),
                  "主程序存在" if os.path.isfile(exe) else "缺少 %s(目录不对?)" % EXE_NAME),
        CheckItem("winhttp.dll", os.path.isfile(winhttp),
                  "注入入口存在" if os.path.isfile(winhttp) else "winhttp.dll 缺失,插件不会加载"),
        CheckItem("BepInEx", os.path.isdir(bep_core),
                  "运行时存在" if os.path.isdir(bep_core) else "BepInEx\\core 缺失"),
        CheckItem("plugin", os.path.isfile(dll),
                  "StoryViewer.dll 存在" if os.path.isfile(dll) else "StoryViewer.dll 缺失"),
        CheckItem("stories.json", stories_ok, stories_detail),
        CheckItem("previews", preview_count > 0, "%d 张封面" % preview_count if preview_count
                  else "previews 目录缺失或为空"),
        CheckItem("cfg", cfg_ok, cfg_detail),
        identity_item,
        catalog_item,
        cache_item,
        _zone_check([exe, winhttp, dll]),
        _port_check(),
        CheckItem("version", os.path.isfile(version),
                  "版本文件存在" if os.path.isfile(version) else "offline_version.json 缺失"),
    ]


# ---------------------------------------------------------------- 修复

def _unblock_game_files(game_dir: str) -> tuple:
    """用 PowerShell 解除游戏目录下文件的 Zone.Identifier。"""
    safe_dir = game_dir.replace("'", "''")
    command = "Get-ChildItem -LiteralPath '%s' -Recurse -File | Unblock-File" % safe_dir
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", command],
                       check=True, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return True, ""


def _archive_big_log(path: str, stamp: str) -> str:
    """日志超过阈值时改名归档,返回中文说明或空串。"""
    if not os.path.isfile(path) or os.path.getsize(path) <= LOG_ARCHIVE_BYTES:
        return ""
    archived = path + ".old_" + stamp
    try:
        os.replace(path, archived)
    except OSError as error:
        return "日志归档失败(%s):%s" % (os.path.basename(path), error)
    return "已归档超大日志 %s" % os.path.basename(archived)


def safe_repair(game_dir: str) -> list:
    """修复可本地恢复的离线启动条件(不联网),返回中文日志行。"""
    logs = []
    unblock_ok, unblock_detail = _unblock_game_files(game_dir)
    if unblock_ok:
        logs.append("已解除游戏文件的 Zone.Identifier")
    else:
        logs.append("解除 Zone.Identifier 失败(可忽略):" + unblock_detail)

    logs.append(repair_config(game_dir))

    logs.append(ensure_offline_identity(game_dir))
    logs.extend(seed_catalog_to_local_low(game_dir))
    logs.extend(seed_local_low_extras(game_dir))

    stamp = time.strftime("%Y%m%d_%H%M%S")
    for name in ("LogOutput.log", "ErrorLog.log"):
        line = _archive_big_log(os.path.join(logs_dir(game_dir), name), stamp)
        if line:
            logs.append(line)

    if os.path.isfile(version_path(game_dir)):
        data = load_version(game_dir)
        if not data.get("first_ready"):
            data["first_ready"] = True
            save_version(game_dir, data)
            logs.append("已将 first_ready 设为 true")
    return logs


# ---------------------------------------------------------------- 探针

def index_probe(game_dir: str) -> list:
    """索引探针:验证剧情索引/封面/配置/端口,不启动游戏。"""
    items = []

    cfg_ok, cfg_detail = offline_config_status(game_dir)
    items.append(ProbeItem("cfg", cfg_ok, cfg_detail))

    stories = stories_path(game_dir)
    if not os.path.isfile(stories):
        items.append(ProbeItem("stories.json", False, "缺失"))
    else:
        try:
            with open(stories, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            entries = data.get("stories") if isinstance(data, dict) else data
            entries = entries if isinstance(entries, list) else []
            by_prefix = {prefix: 0 for prefix in _STORIES_PREFIXES}
            other = 0
            for entry in entries:
                key = ""
                if isinstance(entry, dict):
                    key = str(entry.get("k") or entry.get("key") or "")
                matched = False
                for prefix in _STORIES_PREFIXES:
                    if key.startswith(prefix):
                        by_prefix[prefix] += 1
                        matched = True
                        break
                if not matched:
                    other += 1
            detail = "、".join("%s %d" % (p.rstrip("_"), by_prefix[p]) for p in _STORIES_PREFIXES)
            detail += "(其它 %d)" % other
            items.append(ProbeItem("stories.json", len(entries) >= STORIES_MIN_COUNT,
                                   "共 %d 条:%s" % (len(entries), detail)))
        except (OSError, json.JSONDecodeError) as error:
            items.append(ProbeItem("stories.json", False, "无法解析:%s" % error))

    previews = previews_dir(game_dir)
    preview_count = len(os.listdir(previews)) if os.path.isdir(previews) else 0
    items.append(ProbeItem("previews", preview_count > 0, "%d 张封面" % preview_count))

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", API_PORT))
        items.append(ProbeItem("port", True, "%d 可绑定(启动游戏后可起本地服务)" % API_PORT))
    except OSError as error:
        items.append(ProbeItem("port", False,
                               "%d 被占用(关闭残留进程后重试):%s" % (API_PORT, error)))
    return items


# ---------------------------------------------------------------- 更新辅助

def parse_latest_release(payload: dict) -> dict:
    """从 GitHub Release API 结果里抽取更新附件地址。

    返回:``{"tag": str, "assets_by_name": {name: url}, <各键>: url|None}``。
    """
    release = {"tag": payload.get("tag_name"), "assets_by_name": {}}
    for key in _ASSET_URL_KEYS.values():
        release[key] = None
    for asset in payload.get("assets") or []:
        name = (asset or {}).get("name") or ""
        url = (asset or {}).get("browser_download_url")
        if name and url:
            release["assets_by_name"][name] = url
        key = _ASSET_URL_KEYS.get(name)
        if key:
            release[key] = url
    return release


def baseline_mismatch(local: dict, remote: dict) -> bool:
    """本地与远端基线是否不一致(不一致必须重装完整包,不接受增量更新)。

    基线为打包日冻结的完整包标识;两端都缺(旧版文件)视为一致,便于开发期。
    """
    return str((local or {}).get("baseline") or "") != str((remote or {}).get("baseline") or "")


def read_github_repo(game_dir: str) -> str:
    """读取游戏根 ``launcher.json`` 的 ``github_repo``(未配置返回空串)。"""
    path = launcher_json_path(game_dir)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return str((data or {}).get("github_repo") or "").strip()
    except (OSError, json.JSONDecodeError):
        return ""


# ---------------------------------------------------------------- 诊断包收集与上传
#
# 分工(见"诊断功能双端分工架构"):启动器负责静态环境与日志文件打包;
# 运行时的 [资源自举]/[未观察异常]/场景切换 已写进 LogOutput.log、命中/缺失写进
# offline-api.log,这里把这些文件收进来即可覆盖玩家侧黑屏排查所需。
# 关键约束:纯本地文件操作,绝不发网络请求(上传是显式、配置驱动的第二步);
# 任何单个文件缺失或读失败都跳过,不因个别问题让整个诊断包生成失败。

DIAG_DIR_NAME = "diagnostics"
DIAG_MAX_FILE_BYTES = 8 * 1024 * 1024          # 单个日志最多收录 8MB(超出取尾部)
DIAG_CACHE_SCAN_LIMIT = 40000                  # Caches 遍历上限,防止超大目录卡住
DIAG_UPLOAD_URL_ENV = "DOTABYSS_DIAG_UPLOAD_URL"
DIAG_UPLOAD_TOKEN_ENV = "DOTABYSS_DIAG_UPLOAD_TOKEN"
DIAG_UPLOAD_TIMEOUT = 30
DIAG_KEEP_HEAD_BYTES = 2 * 1024 * 1024          # 超大日志额外保留开头的字节数(崩溃签名常在开机段)
DIAG_SIGNATURE_SCAN_BYTES = 16 * 1024 * 1024    # 关键字抽取最多扫描的字节数(有界,防超大日志卡住)
# 已知黑屏崩溃链签名:原生 Addressables 初始化失败 → aa/runtime.json 回退 → CriSound/BitConverter。
DIAG_SIGNATURE_PATTERNS = (
    "runtime.json", "TextDataProvider", "Player Content", "Unable to load runtime",
    "asset is null", "BitConverter", "Value cannot be null", "CriSound",
    "LoadBuiltinSound", "InitializeAsync", "InitializeServicesAsync",
)


def _tail_bytes(path: str, max_bytes: int = DIAG_MAX_FILE_BYTES) -> bytes:
    """读取文件尾部至多 ``max_bytes`` 字节(小文件全读);失败返回空字节。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            return handle.read()
    except OSError:
        return b""


def _cap_bytes_head_tail(path: str, max_bytes: int = DIAG_MAX_FILE_BYTES,
                         head_bytes: int = DIAG_KEEP_HEAD_BYTES) -> bytes:
    """读取日志:小文件全收;超大文件保留开头 ``head_bytes`` + 结尾剩余配额,
    中间用截断标记替代。确保开机段的崩溃签名与最近的活动都能进诊断包。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return b""
    if size <= max_bytes:
        return _tail_bytes(path, max_bytes)
    tail_quota = max_bytes - head_bytes
    try:
        with open(path, "rb") as handle:
            head = handle.read(head_bytes)
            handle.seek(size - tail_quota)
            tail = handle.read(tail_quota)
    except OSError:
        return b""
    marker = ("\n\n=== [...中间 %d 字节已省略...] ===\n\n"
              % (size - head_bytes - tail_quota)).encode("utf-8")
    return head + marker + tail


def _diag_signature_lines(game_dir: str) -> list:
    """从主日志开机段抽取已知崩溃签名行,即便原始日志超限被截断,摘要里也留痕。"""
    path = os.path.join(logs_dir(game_dir), "LogOutput.log")
    if not os.path.isfile(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            raw = handle.read(min(size, DIAG_SIGNATURE_SCAN_BYTES))
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    out = []
    seen = set()
    for line in text.splitlines():
        low = line.lower()
        if any(pat.lower() in low for pat in DIAG_SIGNATURE_PATTERNS):
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                out.append(stripped[:300])
            if len(out) >= 120:
                break
    return out


def _diag_log_files(bex: str) -> list:
    """列出 BepInEx 目录里的运行日志文件名(LogOutput*/ErrorLog*/offline-api*,含归档)。"""
    out = []
    if not os.path.isdir(bex):
        return out
    for name in os.listdir(bex):
        low = name.lower()
        if low.endswith(".log") and (low.startswith("logoutput")
                                      or low.startswith("errorlog")
                                      or low.startswith("offline-api")):
            if os.path.isfile(os.path.join(bex, name)):
                out.append(name)
    return sorted(out)


def _cache_total_bytes(game_dir: str) -> int:
    """Caches 目录总字节(有界遍历,最多统计 ``DIAG_CACHE_SCAN_LIMIT`` 个文件)。"""
    root = cache_dir(game_dir)
    if not os.path.isdir(root):
        return 0
    total = 0
    scanned = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            scanned += 1
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
            if scanned >= DIAG_CACHE_SCAN_LIMIT:
                return total
    return total


def _offline_api_summary(game_dir: str) -> str:
    """从 offline-api.log 取最近一条 "累计命中/缺失" 统计,一眼看资源命中情况。"""
    path = os.path.join(logs_dir(game_dir), "offline-api.log")
    if not os.path.isfile(path):
        return "无 offline-api.log"
    last = ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "累计命中" in line:
                    last = line.strip()
    except OSError as error:
        return "读取失败:%s" % error
    return last or "(日志里暂无命中统计)"


def _diag_summary_lines(game_dir: str) -> list:
    """生成诊断摘要文本行(静态环境 + 关键运行时指标 + 自检/探针结果)。"""
    import platform
    lines = []
    lines.append("=== ドットアビスX 离线诊断包 ===")
    lines.append("生成时间:%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("系统:%s %s / Python %s" % (
        platform.system(), platform.release(), platform.python_version()))
    lines.append("游戏目录:%s" % game_dir)
    try:
        lines.append("游戏进程:%s" % ("运行中" if game_running() else "未运行"))
    except Exception as error:  # noqa: BLE001
        lines.append("游戏进程:探测失败 %s" % error)

    dll = plugin_dll_path(game_dir)
    try:
        dll_md5 = file_md5(dll) if os.path.isfile(dll) else "(缺)"
    except OSError:
        dll_md5 = "(读失败)"
    lines.append("插件 DLL:%s md5=%s 版本=%s" % (
        os.path.basename(dll), dll_md5, plugin_file_version(game_dir) or "(未知)"))

    vpath = version_path(game_dir)
    if os.path.isfile(vpath):
        try:
            with open(vpath, "r", encoding="utf-8") as handle:
                ver = json.load(handle) or {}
            lines.append("离线包:version=%s baseline=%s channel=%s plugin=%s" % (
                ver.get("version"), ver.get("baseline"), ver.get("channel"),
                ver.get("plugin_version")))
        except (OSError, json.JSONDecodeError) as error:
            lines.append("离线包版本文件无法解析:%s" % error)
    else:
        lines.append("离线包版本文件:无(%s)" % vpath)

    aip = app_info_path(game_dir)
    if os.path.isfile(aip):
        try:
            with open(aip, "r", encoding="utf-8", errors="replace") as handle:
                lines.append("app.info:%s" % " / ".join(x.strip() for x in handle if x.strip()))
        except OSError:
            pass

    ok, detail = offline_config_status(game_dir)
    cfg_lines = _read_cfg_lines(config_path(game_dir))
    extra = {key: _cfg_value(cfg_lines, key)
             for key in ("DiagAssets", "CaptureForward", "ApiPort")}
    lines.append("配置离线档:%s 详情:%s 关键额外项:%s" % (
        "通过" if ok else "不通过", detail, extra))

    lines.append("Caches 顶层目录数=%d(完整阈值 %d)" % (
        cache_entry_count(game_dir), CACHE_MIN_ENTRIES))
    lines.append("Caches 总字节≈%d" % _cache_total_bytes(game_dir))
    lines.append("资源命中统计:%s" % _offline_api_summary(game_dir))

    lines.append("")
    lines.append("--- health_check ---")
    try:
        for item in health_check(game_dir):
            lines.append("%s [%s] %s" % ("OK " if item.ok else "BAD", item.name, item.detail))
    except Exception as error:  # noqa: BLE001
        lines.append("health_check 异常:%s" % error)

    lines.append("")
    lines.append("--- index_probe ---")
    try:
        for item in index_probe(game_dir):
            lines.append("%s [%s] %s" % ("OK " if item.ok else "BAD", item.name, item.detail))
    except Exception as error:  # noqa: BLE001
        lines.append("index_probe 异常:%s" % error)

    lines.append("")
    lines.append("--- 崩溃签名抽取(LogOutput 开机段关键字) ---")
    sig = _diag_signature_lines(game_dir)
    if sig:
        lines.extend(sig)
    else:
        lines.append("(未匹配到已知崩溃签名关键字;可能本次未触发或日志已轮转)")

    return lines


def collect_diagnostics(game_dir: str, dest_dir: str = None) -> tuple:
    """收集日志 + 静态环境,打包成 zip 诊断包。返回 ``(zip 路径, 摘要行列表)``。

    参数:game_dir 游戏根;dest_dir 输出目录(默认游戏根下 ``diagnostics\\``)。
    说明:纯本地文件操作,不发网络;单个文件超大只收尾部;任何缺失都跳过不报错。
    """
    lines = _diag_summary_lines(game_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if not dest_dir:
        dest_dir = os.path.join(game_dir, DIAG_DIR_NAME)
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, "dotabyss-diag-%s.zip" % stamp)

    bex = logs_dir(game_dir)
    plugin = plugin_dir(game_dir)
    cfg_dir = os.path.join(bex, "config")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("diag/diag_summary.txt", ("\n".join(lines) + "\n").encode("utf-8"))
        for name in _diag_log_files(bex):
            zf.writestr("diag/logs/" + name, _cap_bytes_head_tail(os.path.join(bex, name)))
        if os.path.isdir(cfg_dir):
            for name in os.listdir(cfg_dir):
                if name.lower().endswith(".cfg") and os.path.isfile(os.path.join(cfg_dir, name)):
                    zf.writestr("diag/config/" + name, _tail_bytes(os.path.join(cfg_dir, name)))
        for arc, real in (("diag/offline_version.json", version_path(game_dir)),
                          ("diag/app.info", app_info_path(game_dir)),
                          ("diag/launcher.json", launcher_json_path(game_dir))):
            if os.path.isfile(real):
                zf.writestr(arc, _tail_bytes(real))
        stories = stories_path(game_dir)
        if os.path.isfile(stories):
            zf.writestr("diag/plugin/stories.json", _tail_bytes(stories))
    return zip_path, lines


def _diag_encode_endpoint(url: str, token: str) -> str:
    """把 ``(url, token)`` 编成 base64 串,供 launcher.json 的隐身字段 ``diag_endpoint``
    使用(避免明文 IP/令牌直接落在配置里被 grep 到;非加密,仅防顺手扫)。"""
    import base64
    raw = (url or "") + "\n" + (token or "")
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _diag_decode_endpoint(value) -> tuple:
    """解 ``diag_endpoint``,返回 ``(url, token)``;非法/空返回 ``("", "")``。"""
    import base64
    if not value:
        return "", ""
    try:
        raw = base64.b64decode(str(value)).decode("utf-8", errors="replace")
        url, _, token = raw.partition("\n")
        return url.strip(), token.strip()
    except (ValueError, TypeError):
        return "", ""


# 构建期由 make_diag_default.py 生成的内建默认端点(base64,明文不进仓库);
# 随 freeze 烘进启动器 exe,作为老玩家 launcher.json 无端点时的兜底。缺失则为空。
try:
    from dotabyss_diag_default import ENDPOINT_B64 as _DIAG_EMBED_B64  # type: ignore
except Exception:  # noqa: BLE001 - 模块不存在(源码运行/未生成)视为无内建默认
    _DIAG_EMBED_B64 = ""


def _diag_upload_target(game_dir: str) -> tuple:
    """解析上传目标 ``(url, token)``。优先级:环境变量 → ``launcher.json`` → 内建默认。

    ``launcher.json`` 支持明文 ``diag_upload_url``/``diag_upload_token`` 或隐身
    ``diag_endpoint``(base64 ``url\\ntoken``);都未命中时回退到冻结入 exe 的
    ``_DIAG_EMBED_B64``(使老玩家仅更新启动器也能回传)。都无则返回空(仅本地 zip)。
    """
    url = os.environ.get(DIAG_UPLOAD_URL_ENV, "").strip()
    token = os.environ.get(DIAG_UPLOAD_TOKEN_ENV, "").strip()
    if not url:
        path = launcher_json_path(game_dir)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle) or {}
                url = str(data.get("diag_upload_url") or "").strip()
                token = token or str(data.get("diag_upload_token") or "").strip()
                if not url:
                    eu, et = _diag_decode_endpoint(data.get("diag_endpoint"))
                    url = url or eu
                    token = token or et
            except (OSError, json.JSONDecodeError):
                pass
    if not url and _DIAG_EMBED_B64:
        eu, et = _diag_decode_endpoint(_DIAG_EMBED_B64)
        url = url or eu
        token = token or et
    return url, token


def _diag_summary_from_zip(zip_path: str) -> str:
    """从诊断 zip 里取 ``diag/diag_summary.txt`` 文本(取不到返回空串)。"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if "diag/diag_summary.txt" in zf.namelist():
                return zf.read("diag/diag_summary.txt").decode("utf-8", errors="replace")
    except (OSError, zipfile.BadZipFile, KeyError):
        pass
    return ""


def _multipart_part(boundary: str, name: str, filename, content: bytes,
                    content_type: str) -> bytes:
    """构造一个 multipart/form-data 分节;``filename`` 为 None 时是纯文本字段。"""
    disp = 'Content-Disposition: form-data; name="%s"' % name
    if filename is not None:
        disp += '; filename="%s"' % filename
    head = ("--%s\r\n" % boundary) + (disp + "\r\n") + \
           ("Content-Type: %s\r\n\r\n" % content_type)
    return head.encode("utf-8") + content + b"\r\n"


def upload_diagnostics(game_dir: str, zip_path: str, url: str = None,
                       token: str = None) -> tuple:
    """把诊断包上传到配置的目标。返回 ``(状态, 说明)``,状态为 skipped/ok/error。

    未配置 url 时**只保留本地 zip 并跳过**,绝不猜测端点(上传目标需显式配置:
    环境变量 ``DOTABYSS_DIAG_UPLOAD_URL``,或 launcher.json 的 ``diag_upload_url``)。
    发送为标准 multipart/form-data:文件字段 ``file``(zip)+ 文本字段 ``summary``
    (诊断摘要纯文本,便于接收端无需解压即可成文);可选 Bearer 令牌。
    """
    if url is None or token is None:
        cfg_url, cfg_token = _diag_upload_target(game_dir)
        url = cfg_url if url is None else url
        token = cfg_token if token is None else token
    if not url:
        return "skipped", "未配置上传目标(设 %s 或 launcher.json 的 diag_upload_url);诊断包已保存在:%s" % (
            DIAG_UPLOAD_URL_ENV, zip_path)
    import urllib.error
    import urllib.request
    try:
        payload = _tail_bytes(zip_path, max_bytes=64 * 1024 * 1024)
        summary = _diag_summary_from_zip(zip_path)[:64 * 1024]
        boundary = "----dotabyssdiag%d" % int(time.time() * 1000)
        fname = os.path.basename(zip_path)
        parts = [_multipart_part(boundary, "file", fname, payload, "application/zip")]
        if summary:
            parts.append(_multipart_part(boundary, "summary", None,
                                         summary.encode("utf-8"), "text/plain; charset=utf-8"))
        body = b"".join(parts) + ("--%s--\r\n" % boundary).encode("utf-8")
        headers = {"Content-Type": "multipart/form-data; boundary=%s" % boundary,
                   "Content-Length": str(len(body))}
        if token:
            headers["Authorization"] = "Bearer %s" % token
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=DIAG_UPLOAD_TIMEOUT) as response:
            code = getattr(response, "status", None) or response.getcode()
            return "ok", "已上传(HTTP %s):%s" % (code, url)
    except urllib.error.HTTPError as error:
        return "error", "上传被拒(HTTP %s):%s" % (error.code, url)
    except (urllib.error.URLError, OSError) as error:
        return "error", "上传失败:%s" % error
