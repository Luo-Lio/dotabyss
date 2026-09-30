#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线包构建共享逻辑:客户端本体清单、bundle 增量清单与清单 zip。

供 ``build_full_pack.py`` 与 ``build_github_pack.py`` 使用;运行时不进启动器。
清单语义(与 dotabyss_offline_core 的安装侧一致):
- ``client_body``:包内除插件/缓存/身份/启动器/文档外的全部文件(相对路径 → md5);
- ``caches_added``:相对上一份完整包新增或变化的 ``_Data/Caches/<名>/<哈希>/__data|__info``;
  Addressables 缓存路径里的哈希由内容决定,路径相同即内容相同。
"""

from __future__ import annotations

import os
import zipfile

import dotabyss_offline_core as core


def walk_files(root: str):
    """遍历目录下全部文件,产出 ``(相对路径, 绝对路径)``(相对路径用 / 分隔)。"""
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            yield os.path.relpath(full, root).replace("\\", "/"), full


def client_body_files(pack_dir: str) -> dict:
    """收集客户端本体清单(相对路径 → md5),按核心侧白名单过滤。"""
    files = {}
    for rel, full in walk_files(pack_dir):
        if core.client_body_rel_allowed(rel):
            files[rel] = core.file_md5(full)
    return files


def caches_added_files(pack_dir: str, since_dir: str) -> dict:
    """收集相对 ``since_dir`` 新增/变化的 bundle 缓存文件(路径 → md5)。

    只看 ``_Data/Caches`` 下形如 ``<名>/<哈希>/__data`` 与 ``__info`` 的成员
    (``__lock`` 不入清单);同路径已在旧包里且大小一致时跳过。
    """
    cache_root = core.cache_dir(pack_dir)
    files = {}
    for rel, full in walk_files(cache_root):
        pack_rel = "%s/%s/%s" % (core.DATA_DIR_NAME, core.CACHE_DIR_NAME, rel)
        if not core.caches_rel_allowed(pack_rel):
            continue
        if since_dir:
            old = os.path.join(core.cache_dir(since_dir), *rel.split("/"))
            if os.path.isfile(old) and os.path.getsize(old) == os.path.getsize(full):
                continue
        files[pack_rel] = core.file_md5(full)
    return files


def write_manifest_zip(pack_dir: str, files: dict, zip_path: str,
                       compress: bool = True) -> dict:
    """把清单里的文件按包相对路径写进 zip,返回清单字典(含 zip 摘要与字节数)。

    成员路径先经核心侧校验(不允许逃逸/黑名单),再写入;
    ``compress`` False 时用 STORED(已压缩内容更快)。
    """
    for rel in files:
        if core.rel_path_safe(pack_dir, rel) is None:
            raise ValueError("清单路径不合法:%s" % rel)
    method = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(zip_path, "w", method, allowZip64=True) as archive:
        for rel in sorted(files):
            full = os.path.join(pack_dir, *rel.split("/"))
            if not os.path.isfile(full):
                raise ValueError("清单文件不存在:%s" % rel)
            archive.write(full, rel)
    return {
        "zip": os.path.basename(zip_path),
        "zip_md5": core.file_md5(zip_path),
        "bytes": os.path.getsize(zip_path),
        "files": files,
    }
