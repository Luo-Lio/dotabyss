#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dotabyss_launcher 更新流程集成测试:模拟 HTTP,验证安装顺序、校验与失败保护。

运行:``D:\\Python\\python.exe test_launcher_update.py``(需要图形环境,测试里会建 Tk 窗口)。
"""

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dotabyss_offline_core as core  # noqa: E402
import dotabyss_launcher as launcher  # noqa: E402


def _md5(data: bytes) -> str:
    """返回字节串的 MD5(测试用)。"""
    return hashlib.md5(data).hexdigest()


def _zip(entries) -> bytes:
    """把 ``[(name, bytes)]`` 打成内存 zip。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


class UpdateFlowTest(unittest.TestCase):
    """在假游戏目录上跑 ``App._do_update``,断言消息与落盘结果。"""

    NEW_DLL = b"NEW-DLL-BYTES"
    NEW_STORIES = json.dumps({"series": [], "stories": [{"k": "mas_x"}] * 200}).encode()
    NEW_LAUNCHER = b"NEW-LAUNCHER-EXE"
    OLD_DLL = b"old-dll"
    OLD_STORIES = json.dumps({"series": [], "stories": [{"k": "mas_old"}] * 200}).encode()
    DOCS_ZIP = _zip([("使用说明.md", "说明书".encode("utf-8")),
                     ("安装排障.md", "排障".encode("utf-8"))])
    PREVIEWS_ZIP = _zip([("a.png", b"png-a"), ("b.png", b"png-b")])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name
        self._make_game_dir()
        self.root = None
        self.app = None

    def tearDown(self):
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass
        self.tmp.cleanup()

    # ------------------------------------------------------------ 夹具

    def _write(self, rel, data=b"x"):
        """写文件(自动建父目录)。"""
        path = os.path.join(self.game, *rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def _make_game_dir(self):
        """搭出最小可更新目录:骨架文件 + 离线配置 + 旧版本元数据。"""
        self._write((core.EXE_NAME,), b"exe")
        self._write(("winhttp.dll",), b"dll")
        self._write(("BepInEx", "core", "BepInEx.Core.dll"), b"core")
        self._write(("BepInEx", "plugins", "StoryViewer", "StoryViewer.dll"),
                    self.OLD_DLL)
        self._write(("BepInEx", "plugins", "StoryViewer", "stories.json"),
                    self.OLD_STORIES)
        self._write(("BepInEx", "plugins", "StoryViewer", "previews", "old.png"),
                    b"png-old")
        self._write((core.LAUNCHER_EXE_NAME,), self.NEW_LAUNCHER)  # 本地旧启动器先占位
        core.repair_config(self.game)
        core.save_version(self.game, {"version": "20250101", "plugin_version": "0.7.0",
                                      "first_ready": True})

    def _make_app(self):
        """建 App(不跑主循环)并返回。"""
        import tkinter as tk
        self.root = tk.Tk()
        self.app = launcher.App(self.root, game_dir=self.game)
        return self.app

    def _set_repo(self, repo="test/repo"):
        """写 launcher.json。"""
        with open(core.launcher_json_path(self.game), "w", encoding="utf-8") as handle:
            json.dump({"github_repo": repo}, handle)

    def _release_payload(self, stories_md5=None, docs_zip=None):
        """构造 Release API 返回。"""
        return {"tag_name": "20260925", "assets": [
            {"name": "version.json",
             "browser_download_url": "http://x/version.json"},
            {"name": "StoryViewer.dll",
             "browser_download_url": "http://x/StoryViewer.dll"},
            {"name": "stories.json",
             "browser_download_url": "http://x/stories.json"},
            {"name": "previews.zip",
             "browser_download_url": "http://x/previews.zip"},
            {"name": "player_docs.zip",
             "browser_download_url": "http://x/docs.zip"},
            {"name": core.LAUNCHER_EXE_NAME,
             "browser_download_url": "http://x/launcher.exe"},
        ]}

    def _remote_version(self, version="20260925", stories_md5=None, docs_zip=None):
        """构造 version.json 内容。"""
        return {
            "version": version,
            "plugin_version": "0.7.16",
            "plugin_md5": _md5(self.NEW_DLL),
            "stories_md5": stories_md5 or _md5(self.NEW_STORIES),
            "launcher_md5": _md5(self.NEW_LAUNCHER + b"-different"),
            "previews_zip_md5": _md5(self.PREVIEWS_ZIP),
            "player_docs_zip_md5": _md5(docs_zip or self.DOCS_ZIP),
            "notes": "test",
        }

    def _fake_http(self, release, remote, url_bytes=None):
        """返回可注入 ``_http_get`` 的假实现。"""
        mapping = {
            "https://api.github.com/repos/test/repo/releases/latest":
                json.dumps(release).encode("utf-8"),
            "http://x/version.json": json.dumps(remote).encode("utf-8"),
            "http://x/StoryViewer.dll": self.NEW_DLL,
            "http://x/stories.json": self.NEW_STORIES,
            "http://x/previews.zip": self.PREVIEWS_ZIP,
            "http://x/docs.zip": self.DOCS_ZIP,
            "http://x/launcher.exe": self.NEW_LAUNCHER,
        }
        if url_bytes:
            mapping.update(url_bytes)

        def fetch(url, timeout=60):
            """按 URL 返回预置内容。"""
            if url not in mapping:
                raise AssertionError("意外请求:%s" % url)
            return mapping[url]
        return fetch

    def _drain(self):
        """取走日志队列里的全部文本。"""
        texts = []
        while True:
            try:
                item = self.app.q.get_nowait()
            except Exception:
                break
            if item == "__DONE__":
                continue
            texts.append(item[0] if isinstance(item, tuple) else str(item))
        return "\n".join(texts)

    def _read(self, rel):
        """读文件字节。"""
        with open(os.path.join(self.game, *rel), "rb") as handle:
            return handle.read()

    # ------------------------------------------------------------ 用例

    def test_no_repo_warns(self):
        self._make_app()
        self.app._do_update()
        self.assertIn("未配置仓库", self._drain())

    def test_game_running_refuses(self):
        self._set_repo()
        self._make_app()
        with mock.patch.object(core, "game_running", lambda: True):
            self.app._do_update()
        self.assertIn("游戏运行中", self._drain())

    def test_up_to_date(self):
        self._set_repo()
        self._make_app()
        release = self._release_payload()
        remote = self._remote_version(version="20250101")  # 与本地相同
        with mock.patch.object(launcher, "_http_get", self._fake_http(release, remote)):
            self.app._do_update()
        self.assertIn("已是最新。", self._drain())

    def test_full_update_installs_files(self):
        self._set_repo()
        self._make_app()
        release = self._release_payload()
        remote = self._remote_version()
        with mock.patch.object(launcher, "_http_get", self._fake_http(release, remote)):
            self.app._do_update()
        logs = self._drain()
        self.assertIn("更新完成。", logs)
        # 索引 / 插件已换新
        self.assertEqual(self._read(("BepInEx", "plugins", "StoryViewer", "stories.json")),
                         self.NEW_STORIES)
        self.assertEqual(self._read(("BepInEx", "plugins", "StoryViewer", "StoryViewer.dll")),
                         self.NEW_DLL)
        # 封面覆盖(旧文件保留,新文件就位)
        self.assertEqual(self._read(("BepInEx", "plugins", "StoryViewer", "previews", "a.png")),
                         b"png-a")
        self.assertEqual(self._read(("BepInEx", "plugins", "StoryViewer", "previews", "b.png")),
                         b"png-b")
        # 玩家文档落地
        self.assertTrue(os.path.isfile(os.path.join(self.game, "使用说明.md")))
        # 版本元数据更新
        data = core.load_version(self.game)
        self.assertEqual(data["version"], "20260925")
        self.assertEqual(data["plugin_version"], "0.7.16")
        self.assertEqual(data["plugin_md5"], _md5(self.NEW_DLL))
        self.assertTrue(data["first_ready"])
        # 开发模式不换启动器
        self.assertIn("开发模式跳过启动器替换", logs)
        self.assertEqual(self._read((core.LAUNCHER_EXE_NAME,)), self.NEW_LAUNCHER)

    def test_stories_md5_mismatch_keeps_old_and_no_version_bump(self):
        self._set_repo()
        self._make_app()
        release = self._release_payload()
        remote = self._remote_version(stories_md5=_md5(b"other"))
        with mock.patch.object(launcher, "_http_get", self._fake_http(release, remote)):
            self.app._do_update()
        logs = self._drain()
        self.assertIn("更新失败", logs)
        self.assertEqual(self._read(("BepInEx", "plugins", "StoryViewer", "stories.json")),
                         self.OLD_STORIES)
        self.assertEqual(core.load_version(self.game)["version"], "20250101")

    def test_docs_zip_whitelist_rejects_extra_member(self):
        self._set_repo()
        self._make_app()
        bad_docs = _zip([("使用说明.md", b"ok"), ("evil.exe", b"boom")])
        release = self._release_payload()
        remote = self._remote_version(docs_zip=bad_docs)
        with mock.patch.object(launcher, "_http_get",
                               self._fake_http(release, remote,
                                               {"http://x/docs.zip": bad_docs})):
            self.app._do_update()
        logs = self._drain()
        self.assertIn("更新失败", logs)
        self.assertFalse(os.path.isfile(os.path.join(self.game, "evil.exe")))
        self.assertFalse(os.path.isfile(os.path.join(self.game, "使用说明.md")))
        self.assertEqual(core.load_version(self.game)["version"], "20250101")

    def test_previews_zip_md5_mismatch_fails(self):
        self._set_repo()
        self._make_app()
        release = self._release_payload()
        remote = self._remote_version()
        remote["previews_zip_md5"] = _md5(b"other")
        with mock.patch.object(launcher, "_http_get", self._fake_http(release, remote)):
            self.app._do_update()
        logs = self._drain()
        self.assertIn("更新失败", logs)


class VersionLabelTest(unittest.TestCase):
    """_plugin_version_hint 读 DLL 版本(退化路径用配置头注释)。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_dll_version(self):
        game = self.tmp.name
        target = os.path.join(core.plugin_dir(game))
        os.makedirs(target, exist_ok=True)
        shutil.copy2(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "dotabyss_launcher.py"),
            os.path.join(target, "StoryViewer.dll"))
        # 用启动器脚本冒充 DLL:VersionInfo 读不到 → 返回空串而不是崩溃
        self.assertEqual(launcher._plugin_version_hint(game), "")

    def test_cfg_header_fallback_shape(self):
        game = self.tmp.name
        path = core.config_path(game)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("## Settings file was created by plugin StoryViewer v0.7.9\n")
        self.assertEqual(launcher._plugin_version_hint(game), "0.7.9")

    def test_missing_everything(self):
        self.assertEqual(launcher._plugin_version_hint(self.tmp.name), "")


class ChannelUpdateFlowTest(unittest.TestCase):
    """新通道:baseline 门禁、client_body、caches_added、catalog、静默更新检查。"""

    OLD_DLL = b"old-dll"
    NEW_DLL = b"NEW-DLL-BYTES"
    OLD_STORIES = json.dumps({"stories": [{"k": "mas_old"}] * 200}).encode()
    NEW_STORIES = json.dumps({"stories": [{"k": "mas_new"}] * 200}).encode()
    OLD_MANAGED = b"old-managed"
    NEW_MANAGED = b"new-managed"
    SAME_MANAGED = b"same-managed"
    OLD_BUNDLE = b"old-bundle"
    NEW_BUNDLE = b"new-bundle-data"
    OLD_CATALOG = b"OLD-CATALOG-BIN"
    NEW_CATALOG = b"NEW-CATALOG-BIN"
    NEW_CATALOG_HASH = "newcataloghash0123456789abcdef"

    CACHE_REL = "ドットアビスX_Data/Caches/bundleA/h1/__data"
    MANAGED_REL = "ドットアビスX_Data/Managed/Assembly-CSharp.dll"
    SAME_REL = "ドットアビスX_Data/Managed/Unchanged.dll"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = os.path.join(self.tmp.name, "game")
        os.makedirs(self.game, exist_ok=True)
        self.base = os.path.join(self.tmp.name, "LocalLowBase")
        self._old_env = os.environ.get(core.LOCAL_LOW_ENV)
        os.environ[core.LOCAL_LOW_ENV] = self.base
        self.root = None
        self.app = None
        self._make_game_dir()

    def tearDown(self):
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass
        if self._old_env is None:
            os.environ.pop(core.LOCAL_LOW_ENV, None)
        else:
            os.environ[core.LOCAL_LOW_ENV] = self._old_env
        self.tmp.cleanup()

    # ------------------------------------------------------------ 夹具

    def _write_abs(self, path, data=b"x"):
        """按绝对路径写文件(自动建父目录)。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def _write(self, rel, data=b"x"):
        """按元组相对路径写文件。"""
        self._write_abs(os.path.join(self.game, *rel), data)

    def _read(self, rel):
        """读文件字节。"""
        with open(os.path.join(self.game, *rel), "rb") as handle:
            return handle.read()

    def _make_game_dir(self):
        """搭出带身份/catalog 种子/本体文件/缓存条目的可更新目录。"""
        self._write((core.EXE_NAME,), b"exe")
        self._write(("winhttp.dll",), b"dll")
        self._write(("BepInEx", "core", "BepInEx.Core.dll"), b"core")
        self._write(("BepInEx", "plugins", "StoryViewer", "StoryViewer.dll"), self.OLD_DLL)
        self._write(("BepInEx", "plugins", "StoryViewer", "stories.json"), self.OLD_STORIES)
        self._write(("BepInEx", "plugins", "StoryViewer", "previews", "old.png"), b"p")
        self._write((core.DATA_DIR_NAME, core.APP_INFO_NAME),
                    "EXNOA LLC.\nドットアビスX_offline".encode("utf-8"))
        self._write((core.LAUNCHER_EXE_NAME,), b"old-launcher")
        seed = core.catalog_seed_dir(self.game)
        self._write_abs(os.path.join(seed, core.CATALOG_BIN_NAME), self.OLD_CATALOG)
        self._write_abs(os.path.join(seed, core.CATALOG_HASH_NAME), b"oldcataloghash")
        self._write((core.DATA_DIR_NAME, "Managed", "Assembly-CSharp.dll"), self.OLD_MANAGED)
        self._write((core.DATA_DIR_NAME, "Managed", "Unchanged.dll"), self.SAME_MANAGED)
        self._write((core.DATA_DIR_NAME, core.CACHE_DIR_NAME, "bundleA", "h1", "__data"),
                    self.OLD_BUNDLE)
        core.repair_config(self.game)
        core.save_version(self.game, {
            "version": "20250101", "baseline": "20250101", "channel": "baseline",
            "plugin_version": "0.7.0", "catalog_hash": "oldcataloghash",
            "first_ready": True,
        })

    def _make_app(self):
        """建 App(不跑主循环)。"""
        import tkinter as tk
        self.root = tk.Tk()
        self.app = launcher.App(self.root, game_dir=self.game)
        return self.app

    def _set_repo(self, repo="test/repo"):
        """写 launcher.json。"""
        with open(core.launcher_json_path(self.game), "w", encoding="utf-8") as handle:
            json.dump({"github_repo": repo}, handle)

    def _client_body_zip(self):
        """客户端本体更新包(成员路径用 / 分隔)。"""
        return _zip([(self.MANAGED_REL, self.NEW_MANAGED)])

    def _caches_zip(self):
        """bundle 增量包。"""
        return _zip([(self.CACHE_REL, self.NEW_BUNDLE)])

    def _release(self, include_catalog=True):
        """Release API 附件表。"""
        assets = [
            {"name": "version.json", "browser_download_url": "http://x/version.json"},
            {"name": "StoryViewer.dll", "browser_download_url": "http://x/StoryViewer.dll"},
            {"name": "stories.json", "browser_download_url": "http://x/stories.json"},
            {"name": core.LAUNCHER_EXE_NAME, "browser_download_url": "http://x/launcher.exe"},
            {"name": "client_body.zip", "browser_download_url": "http://x/client_body.zip"},
            {"name": "caches_update.zip", "browser_download_url": "http://x/caches_update.zip"},
        ]
        if include_catalog:
            assets += [
                {"name": core.CATALOG_BIN_NAME, "browser_download_url": "http://x/catalog_1.bin"},
                {"name": core.CATALOG_HASH_NAME,
                 "browser_download_url": "http://x/catalog_1.bin.hash"},
            ]
        return {"tag_name": "20260925", "assets": assets}

    def _remote(self, **over):
        """version.json 内容(默认是一次完整可成功的更新)。"""
        body_zip = self._client_body_zip()
        caches_zip = self._caches_zip()
        data = {
            "version": "20260925",
            "baseline": "20250101",
            "channel": "baseline",
            "plugin_version": "0.7.17",
            "plugin_md5": _md5(self.NEW_DLL),
            "stories_md5": _md5(self.NEW_STORIES),
            "launcher_md5": _md5(b"old-launcher"),  # 与本地一致 → 不触发自替换
            "catalog_hash": self.NEW_CATALOG_HASH,
            "catalog_bin_md5": _md5(self.NEW_CATALOG),
            "catalog_hash_md5": _md5(self.NEW_CATALOG_HASH.encode("utf-8")),
            "client_body": {
                "zip_md5": _md5(body_zip),
                "bytes": len(body_zip),
                "files": {
                    self.MANAGED_REL: _md5(self.NEW_MANAGED),
                    self.SAME_REL: _md5(self.SAME_MANAGED),
                },
            },
            "caches_added": {
                "zip_md5": _md5(caches_zip),
                "bytes": len(caches_zip),
                "files": {self.CACHE_REL: _md5(self.NEW_BUNDLE)},
            },
        }
        data.update(over)
        return data

    def _fake_http(self, release, remote):
        """构造 (get, download) 假实现。"""
        mapping = {
            "https://api.github.com/repos/test/repo/releases/latest":
                json.dumps(release).encode("utf-8"),
            "http://x/version.json": json.dumps(remote).encode("utf-8"),
            "http://x/StoryViewer.dll": self.NEW_DLL,
            "http://x/stories.json": self.NEW_STORIES,
            "http://x/launcher.exe": b"old-launcher",
            "http://x/client_body.zip": self._client_body_zip(),
            "http://x/caches_update.zip": self._caches_zip(),
            "http://x/catalog_1.bin": self.NEW_CATALOG,
            "http://x/catalog_1.bin.hash": self.NEW_CATALOG_HASH.encode("utf-8"),
        }

        def get(url, timeout=60):
            """按 URL 返回预置内容。"""
            if url not in mapping:
                raise AssertionError("意外请求:%s" % url)
            return mapping[url]

        def download(url, dest, timeout=600, chunk=1 << 20):
            """把预置内容写到目标文件。"""
            data = get(url, timeout)
            with open(dest, "wb") as handle:
                handle.write(data)
            return len(data)

        return get, download

    def _drain(self):
        """取走日志队列里的全部文本。"""
        texts = []
        while True:
            try:
                item = self.app.q.get_nowait()
            except Exception:
                break
            if item == "__DONE__":
                continue
            texts.append(item[0] if isinstance(item, tuple) else str(item))
        return "\n".join(texts)

    def _run_update(self, release, remote):
        """在打好补丁的 HTTP 假实现下跑一次 _do_update,返回日志。"""
        get, download = self._fake_http(release, remote)
        with mock.patch.object(launcher, "_http_get", get), \
                mock.patch.object(launcher, "_http_download", download):
            self.app._do_update()
        return self._drain()

    # ------------------------------------------------------------ 用例

    def test_baseline_mismatch_blocks_update(self):
        self._set_repo()
        self._make_app()
        logs = self._run_update(self._release(), self._remote(baseline="20240924"))
        self.assertIn("基线不一致", logs)
        self.assertEqual(core.load_version(self.game)["version"], "20250101")
        self.assertEqual(self._read((core.DATA_DIR_NAME, "Managed", "Assembly-CSharp.dll")),
                         self.OLD_MANAGED)

    def test_baseline_mismatch_wins_over_equal_version(self):
        """基线不一致时,即使版本号与本机相同也必须拒绝(否则老基线玩家会被告知"已是最新")。"""
        self._set_repo()
        self._make_app()
        remote = self._remote(baseline="20260101", version="20250101")
        logs = self._run_update(self._release(), remote)
        self.assertIn("基线不一致", logs)
        self.assertNotIn("已是最新", logs)

    def test_full_channel_update_installs_everything(self):
        self._set_repo()
        self._make_app()
        logs = self._run_update(self._release(), self._remote())
        self.assertIn("更新完成。", logs)
        # 客户端本体:变动的换新,未变动的保持原样
        self.assertEqual(self._read((core.DATA_DIR_NAME, "Managed", "Assembly-CSharp.dll")),
                         self.NEW_MANAGED)
        self.assertEqual(self._read((core.DATA_DIR_NAME, "Managed", "Unchanged.dll")),
                         self.SAME_MANAGED)
        # bundle 增量
        self.assertEqual(self._read((core.DATA_DIR_NAME, core.CACHE_DIR_NAME,
                                     "bundleA", "h1", "__data")), self.NEW_BUNDLE)
        # catalog 种子 + LocalLow 播种
        seed_bin = os.path.join(core.catalog_seed_dir(self.game), core.CATALOG_BIN_NAME)
        with open(seed_bin, "rb") as handle:
            self.assertEqual(handle.read(), self.NEW_CATALOG)
        self.assertEqual(core.catalog_seed_hash(self.game), self.NEW_CATALOG_HASH)
        local_low = core.local_low_catalog_dir(self.game)
        with open(os.path.join(local_low, core.CATALOG_BIN_NAME), "rb") as handle:
            self.assertEqual(handle.read(), self.NEW_CATALOG)
        # 版本元数据:保留基线/通道,记录 catalog 哈希
        data = core.load_version(self.game)
        self.assertEqual(data["version"], "20260925")
        self.assertEqual(data["baseline"], "20250101")
        self.assertEqual(data["channel"], "baseline")
        self.assertEqual(data["catalog_hash"], self.NEW_CATALOG_HASH)

    def test_client_body_md5_mismatch_blocks_version(self):
        self._set_repo()
        self._make_app()
        remote = self._remote()
        remote["client_body"] = {
            "zip_md5": _md5(self._client_body_zip()),
            "files": {self.MANAGED_REL: _md5(b"wrong")},
        }
        logs = self._run_update(self._release(), remote)
        self.assertIn("更新失败", logs)
        self.assertEqual(core.load_version(self.game)["version"], "20250101")
        self.assertEqual(self._read((core.DATA_DIR_NAME, "Managed", "Assembly-CSharp.dll")),
                         self.OLD_MANAGED)

    def test_client_body_blocked_path_blocks_update(self):
        self._set_repo()
        self._make_app()
        remote = self._remote()
        remote["client_body"] = {
            "zip_md5": _md5(self._client_body_zip()),
            "files": {"BepInEx/plugins/StoryViewer/StoryViewer.dll": _md5(b"x")},
        }
        logs = self._run_update(self._release(), remote)
        self.assertIn("更新失败", logs)
        self.assertEqual(self._read(("BepInEx", "plugins", "StoryViewer", "StoryViewer.dll")),
                         self.OLD_DLL)

    def test_catalog_asset_missing_fails_closed(self):
        self._set_repo()
        self._make_app()
        remote = self._remote(client_body={}, caches_added={})
        logs = self._run_update(self._release(include_catalog=False), remote)
        self.assertIn("更新失败", logs)
        self.assertIn("catalog", logs)
        self.assertEqual(core.load_version(self.game)["version"], "20250101")

    def test_catalog_same_hash_skips_download(self):
        self._set_repo()
        self._make_app()
        remote = self._remote(catalog_hash="oldcataloghash")
        logs = self._run_update(self._release(include_catalog=False), remote)
        self.assertIn("更新完成。", logs)
        # 种子未被改动
        with open(os.path.join(core.catalog_seed_dir(self.game), core.CATALOG_BIN_NAME),
                  "rb") as handle:
            self.assertEqual(handle.read(), self.OLD_CATALOG)

    def _log_text(self):
        """读日志控件全文(经 _poll_queue 落地后的日志)。"""
        return self.app.txt.get("1.0", "end")

    def test_quiet_check_sets_update_button(self):
        self._set_repo()
        self._make_app()
        remote = self._remote(client_body={}, caches_added={})
        with mock.patch.object(launcher.App, "_fetch_remote",
                               lambda self_: (self._release(), remote)):
            self.app._check_update_quiet()
        self.app._poll_queue()
        self.assertEqual(str(self.app.btn_update["text"]), "有更新")
        self.assertIn("发现新版本", self._log_text())

    def test_quiet_check_baseline_mismatch_sets_reinstall(self):
        self._set_repo()
        self._make_app()
        remote = self._remote(baseline="20260101")
        with mock.patch.object(launcher.App, "_fetch_remote",
                               lambda self_: (self._release(), remote)):
            self.app._check_update_quiet()
        self.app._poll_queue()
        self.assertEqual(str(self.app.btn_update["text"]), "需重装")
        self.assertIn("需重新下载完整包", self._log_text())

    def test_quiet_check_silent_on_error(self):
        self._set_repo()
        self._make_app()
        def _boom(self_):
            """模拟网络失败。"""
            raise RuntimeError("net down")
        with mock.patch.object(launcher.App, "_fetch_remote", _boom):
            self.app._check_update_quiet()
        self.app._poll_queue()
        self.assertEqual(str(self.app.btn_update["text"]), "更新")
        self.assertNotIn("发现新版本", self._log_text())
        self.assertNotIn("基线", self._log_text())

    def test_auto_update_with_dir_fetchers_writes_ok(self):
        self._set_repo()
        release_dir = os.path.join(self.tmp.name, "release")
        os.makedirs(release_dir, exist_ok=True)
        release = self._release()
        remote = self._remote()
        files = {
            "release.json": json.dumps(release).encode("utf-8"),
            "version.json": json.dumps(remote).encode("utf-8"),
            "StoryViewer.dll": self.NEW_DLL,
            "stories.json": self.NEW_STORIES,
            "launcher.exe": b"old-launcher",
            "client_body.zip": self._client_body_zip(),
            "caches_update.zip": self._caches_zip(),
            core.CATALOG_BIN_NAME: self.NEW_CATALOG,
            core.CATALOG_HASH_NAME: self.NEW_CATALOG_HASH.encode("utf-8"),
        }
        for name, data in files.items():
            with open(os.path.join(release_dir, name), "wb") as handle:
                handle.write(data)
        out_path = os.path.join(self.tmp.name, "auto.txt")
        get, download = launcher.make_dir_fetchers(release_dir)
        import tkinter as tk
        self.root = tk.Tk()
        self.app = launcher.App(self.root, game_dir=self.game, auto_out=out_path)
        with mock.patch.object(launcher, "_http_get", get), \
                mock.patch.object(launcher, "_http_download", download):
            self.app._auto_update()
        with open(out_path, "r", encoding="utf-8") as handle:
            first = handle.readline().strip()
        self.assertTrue(first.startswith("OK"), first)
        self.assertEqual(core.load_version(self.game)["version"], "20260925")


class DirFetcherTest(unittest.TestCase):
    """make_dir_fetchers:URL 映射、缺文件 404、download 复制。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _put(self, name, data):
        """在发布目录写文件。"""
        with open(os.path.join(self.dir, name), "wb") as handle:
            handle.write(data)

    def test_get_maps_api_and_asset_names(self):
        self._put("release.json", b"release-bytes")
        self._put("version.json", b"version-bytes")
        get, _download = launcher.make_dir_fetchers(self.dir)
        self.assertEqual(get("https://api.github.com/repos/a/b/releases/latest"), b"release-bytes")
        self.assertEqual(get("http://x/version.json"), b"version-bytes")

    def test_missing_file_raises_404(self):
        get, _download = launcher.make_dir_fetchers(self.dir)
        with self.assertRaises(Exception) as ctx:
            get("http://x/none.zip")
        self.assertIn("404", str(ctx.exception))

    def test_download_copies_to_dest(self):
        self._put("client_body.zip", b"zip-bytes")
        _get, download = launcher.make_dir_fetchers(self.dir)
        dest = os.path.join(self.tmp.name, "out", "body.zip")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        self.assertEqual(download("http://x/client_body.zip", dest), 9)
        with open(dest, "rb") as handle:
            self.assertEqual(handle.read(), b"zip-bytes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
