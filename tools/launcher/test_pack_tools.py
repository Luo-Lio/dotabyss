#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dotabyss_pack_tools 单元测试:客户端本体清单、bundle 增量清单、清单 zip。

运行:``D:\\Python\\python.exe test_pack_tools.py``(标准库 unittest)。
"""

import hashlib
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dotabyss_offline_core as core  # noqa: E402
import dotabyss_pack_tools as pack_tools  # noqa: E402


def _md5(data: bytes) -> str:
    """返回字节串的 MD5 十六进制摘要(测试用)。"""
    return hashlib.md5(data).hexdigest()


class PackFixture(unittest.TestCase):
    """搭一个最小"完整包"目录。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pack = os.path.join(self.tmp.name, "pack")
        os.makedirs(self.pack, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _put(self, rel, data=b"x"):
        """按 / 分隔的相对路径写文件。"""
        path = os.path.join(self.pack, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def _cache_rel(self, name, digest, leaf="__data"):
        """bundle 缓存成员的相对路径。"""
        return "%s/%s/%s/%s/%s" % (core.DATA_DIR_NAME, core.CACHE_DIR_NAME,
                                   name, digest, leaf)


class ClientBodyFilesTest(PackFixture):
    """client_body_files:收录本体文件,排除插件/缓存/身份/启动器/文档。"""

    def test_includes_body_and_excludes_reserved(self):
        self._put("ドットアビスX.exe", b"exe")
        self._put("ドットアビスX_Data/Managed/Assembly-CSharp.dll", b"managed")
        self._put("winhttp.dll", b"winhttp")
        self._put("BepInEx/plugins/StoryViewer/StoryViewer.dll", b"plugin")
        self._put(core.VERSION_NAME, b"{}")
        self._put(core.LAUNCHER_JSON_NAME, b"{}")
        self._put(core.LAUNCHER_EXE_NAME, b"exe")
        self._put("使用说明.md", b"doc")
        self._put("check_health.bat", b"bat")
        self._put("%s/%s" % (core.DATA_DIR_NAME, core.APP_INFO_NAME), b"id")
        self._put(self._cache_rel("bn", "a" * 32), b"bundle")
        files = pack_tools.client_body_files(self.pack)
        self.assertIn("ドットアビスX.exe", files)
        self.assertIn("winhttp.dll", files)
        self.assertIn("ドットアビスX_Data/Managed/Assembly-CSharp.dll", files)
        for rel in ("BepInEx/plugins/StoryViewer/StoryViewer.dll", core.VERSION_NAME,
                    core.LAUNCHER_JSON_NAME, core.LAUNCHER_EXE_NAME, "使用说明.md",
                    "check_health.bat", "%s/%s" % (core.DATA_DIR_NAME, core.APP_INFO_NAME),
                    self._cache_rel("bn", "a" * 32)):
            self.assertNotIn(rel, files, rel)
        self.assertEqual(files["winhttp.dll"], _md5(b"winhttp"))

    def test_empty_pack(self):
        self.assertEqual(pack_tools.client_body_files(self.pack), {})


class CachesAddedFilesTest(PackFixture):
    """caches_added_files:相对旧包只收新增/变化的 __data 与 __info。"""

    def test_new_entry_included_and_old_skipped(self):
        old = os.path.join(self.tmp.name, "old")
        os.makedirs(old, exist_ok=True)
        # 旧包已有 bundleA;bundleB 是本次新增
        for root in (self.pack, old):
            path = os.path.join(root, *self._cache_rel("bundleA", "a" * 32).split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"same-bundle")
        self._put(self._cache_rel("bundleB", "b" * 32), b"new-bundle")
        added = pack_tools.caches_added_files(self.pack, old)
        self.assertIn(self._cache_rel("bundleB", "b" * 32), added)
        self.assertNotIn(self._cache_rel("bundleA", "a" * 32), added)
        self.assertEqual(added[self._cache_rel("bundleB", "b" * 32)], _md5(b"new-bundle"))

    def test_same_path_different_size_included(self):
        old = os.path.join(self.tmp.name, "old2")
        path = os.path.join(old, *self._cache_rel("bundleC", "c" * 32).split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"short")
        self._put(self._cache_rel("bundleC", "c" * 32), b"much-longer-content")
        added = pack_tools.caches_added_files(self.pack, old)
        self.assertIn(self._cache_rel("bundleC", "c" * 32), added)

    def test_lock_and_bad_shape_skipped(self):
        self._put(self._cache_rel("bn", "d" * 32, "__lock"), b"lock")
        self._put("%s/%s/notahash/__data" % (core.DATA_DIR_NAME, core.CACHE_DIR_NAME), b"bad")
        self._put("%s/%s/loose.bin" % (core.DATA_DIR_NAME, core.CACHE_DIR_NAME), b"bad")
        self.assertEqual(pack_tools.caches_added_files(self.pack, ""), {})

    def test_info_leaf_included(self):
        self._put(self._cache_rel("bn", "e" * 32, "__info"), b"info")
        added = pack_tools.caches_added_files(self.pack, "")
        self.assertIn(self._cache_rel("bn", "e" * 32, "__info"), added)

    def test_no_since_includes_everything_valid(self):
        self._put(self._cache_rel("bn", "f" * 32), b"one")
        self._put(self._cache_rel("bn2", "0" * 32), b"two")
        added = pack_tools.caches_added_files(self.pack, "")
        self.assertEqual(len(added), 2)


class WriteManifestZipTest(PackFixture):
    """write_manifest_zip:成员写入、清单字段、路径与缺文件保护。"""

    def test_writes_members_and_returns_manifest(self):
        self._put("ドットアビスX_Data/Managed/A.dll", b"aaa")
        self._put("ドットアビスX_Data/Managed/B.dll", b"bbb")
        files = {"ドットアビスX_Data/Managed/A.dll": _md5(b"aaa"),
                 "ドットアビスX_Data/Managed/B.dll": _md5(b"bbb")}
        zip_path = os.path.join(self.tmp.name, "body.zip")
        manifest = pack_tools.write_manifest_zip(self.pack, files, zip_path, compress=True)
        self.assertEqual(manifest["zip"], "body.zip")
        self.assertEqual(manifest["files"], files)
        self.assertEqual(manifest["bytes"], os.path.getsize(zip_path))
        with open(zip_path, "rb") as handle:
            self.assertEqual(manifest["zip_md5"], _md5(handle.read()))
        with zipfile.ZipFile(zip_path) as archive:
            self.assertEqual(sorted(archive.namelist()), sorted(files))
            self.assertEqual(archive.read("ドットアビスX_Data/Managed/A.dll"), b"aaa")

    def test_rejects_traversal_path(self):
        zip_path = os.path.join(self.tmp.name, "bad.zip")
        with self.assertRaises(ValueError):
            pack_tools.write_manifest_zip(self.pack, {"../evil.dll": _md5(b"x")}, zip_path)

    def test_missing_file_raises(self):
        zip_path = os.path.join(self.tmp.name, "missing.zip")
        with self.assertRaises(ValueError):
            pack_tools.write_manifest_zip(self.pack, {"no/such.dll": _md5(b"x")}, zip_path)

    def test_empty_files_writes_empty_zip(self):
        zip_path = os.path.join(self.tmp.name, "empty.zip")
        manifest = pack_tools.write_manifest_zip(self.pack, {}, zip_path)
        self.assertEqual(manifest["files"], {})
        with zipfile.ZipFile(zip_path) as archive:
            self.assertEqual(archive.namelist(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
