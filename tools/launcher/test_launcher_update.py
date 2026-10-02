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

    def test_up_to_date_when_declared_outputs_match(self):
        self._set_repo()
        self._make_app()
        release = self._release_payload()
        remote = self._remote_version(version="20250101")  # 与本地相同
        # 该旧夹具的封面/文档 zip 不是完整发布包,本用例只验证核心文件一致时的同版本判定。
        remote.pop("previews_zip_md5", None)
        remote.pop("player_docs_zip_md5", None)
        self._write(("BepInEx", "plugins", "StoryViewer", "StoryViewer.dll"), self.NEW_DLL)
        self._write(("BepInEx", "plugins", "StoryViewer", "stories.json"), self.NEW_STORIES)
        local = core.load_version(self.game)
        local.update({
            "plugin_md5": remote["plugin_md5"],
            "stories_md5": remote["stories_md5"],
            "launcher_md5": _md5(self.NEW_LAUNCHER),
        })
        core.save_version(self.game, local)
        remote["launcher_md5"] = _md5(self.NEW_LAUNCHER)
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

    def test_short_plugin_version_removes_source_revision(self):
        """带 .NET source revision 的版本只保留基础版本。"""
        self.assertEqual(
            launcher.short_plugin_version(
                "0.7.18+736c5188d8cde3dddc0289a57ec09263b58c987e"),
            "0.7.18")

    def test_short_plugin_version_keeps_clean_version(self):
        """无 source revision 的短版本保持原样。"""
        self.assertEqual(launcher.short_plugin_version("0.7.18"), "0.7.18")

    def test_short_plugin_version_truncates_long_plain_value(self):
        """没有加号但超过显示上限的版本也不能撑破顶栏。"""
        result = launcher.short_plugin_version("123456789012345678901234567890")
        self.assertEqual(result, "12345678901234567890123…")
        self.assertTrue(result.endswith("…"))

    def test_short_plugin_version_empty_values(self):
        """空字符串和 None 均返回空显示值。"""
        self.assertEqual(launcher.short_plugin_version(""), "")
        self.assertEqual(launcher.short_plugin_version(None), "")

    def test_short_plugin_version_empty_base_is_safe(self):
        """加号位于开头时不抛异常且返回空值。"""
        self.assertEqual(launcher.short_plugin_version("+abc"), "")

    def test_startup_logs_full_plugin_version_once(self):
        """启动顶栏显示短版本,日志只记录一次完整版本。"""
        game = self.tmp.name
        core.save_version(game, {
            "version": "20261002",
            "plugin_version": "0.7.18+736c5188d8cde3dddc0289a57ec09263b58c987e",
        })
        import tkinter as tk
        root = tk.Tk()
        try:
            app = launcher.App(root, game_dir=game, smoke_out="unused-smoke.txt")
            app._poll_queue()
            log_text = app.txt.get("1.0", "end")
            self.assertEqual(app._version_text(), "离线包 20261002\n插件 v0.7.18")
            self.assertEqual(log_text.count("插件完整版本: 0.7.18+736c5188d8cde3dddc0289a57ec09263b58c987e"), 1)
        finally:
            root.destroy()


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
    NEW_MASTER_DATA = b"master-data-new"
    MASTER_REL = "DownloadCache/4258a98cad2950fb53a8f5ecba8767f2.dat"

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

    def _master_data_zip(self):
        """主数据增量附件。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            info = zipfile.ZipInfo(self.MASTER_REL, date_time=(2020, 1, 1, 0, 0, 0))
            archive.writestr(info, self.NEW_MASTER_DATA)
        return buffer.getvalue()

    def _release(self, include_catalog=True):
        """Release API 附件表。"""
        assets = [
            {"name": "version.json", "browser_download_url": "http://x/version.json"},
            {"name": "StoryViewer.dll", "browser_download_url": "http://x/StoryViewer.dll"},
            {"name": "stories.json", "browser_download_url": "http://x/stories.json"},
            {"name": core.LAUNCHER_EXE_NAME, "browser_download_url": "http://x/launcher.exe"},
            {"name": "client_body.zip", "browser_download_url": "http://x/client_body.zip"},
            {"name": "caches_update.zip", "browser_download_url": "http://x/caches_update.zip"},
            {"name": "master_data.zip", "browser_download_url": "http://x/master_data.zip"},
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
        master_zip = self._master_data_zip()
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
            "master_data_url": "master_data.zip",
            "master_data_md5": _md5(master_zip),
            "master_data_files": {self.MASTER_REL: _md5(self.NEW_MASTER_DATA)},
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
            "http://x/master_data.zip": self._master_data_zip(),
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

    def _run_update_with_asset_calls(self, release, remote):
        """运行更新并返回日志、实际访问的 Release 资产 URL。"""
        get, download = self._fake_http(release, remote)
        calls = []

        def counted_get(url, timeout=60):
            """记录非 version.json 的资产 GET。"""
            if url.startswith("http://x/") and url != "http://x/version.json":
                calls.append(url)
            return get(url, timeout)

        def counted_download(url, dest, timeout=600, chunk=1 << 20):
            """记录 zip 资产下载。"""
            calls.append(url)
            return download(url, dest, timeout, chunk)

        with mock.patch.object(launcher, "_http_get", counted_get), \
                mock.patch.object(launcher, "_http_download", counted_download):
            self.app._do_update()
        return self._drain(), calls

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

    def test_master_data_update_repairs_old_player_without_seed_dir(self):
        """增量更新应为旧完整包创建种子并把主数据播种到 LocalLow。"""
        self._set_repo()
        self._make_app()
        logs = self._run_update(self._release(), self._remote())

        seed_path = os.path.join(core.local_low_seed_dir(self.game), *self.MASTER_REL.split("/"))
        local_path = os.path.join(core.local_low_dir(self.game), *self.MASTER_REL.split("/"))
        self.assertIn("主数据", logs)
        self.assertEqual(self._read(tuple(["BepInEx", "plugins", "StoryViewer", "local_low_seed"]
                                          + self.MASTER_REL.split("/"))), self.NEW_MASTER_DATA)
        with open(local_path, "rb") as handle:
            self.assertEqual(handle.read(), self.NEW_MASTER_DATA)

    def test_master_data_attachment_missing_fails_closed(self):
        """version.json 声明主数据时,Release 缺附件不能静默完成版本更新。"""
        self._set_repo()
        self._make_app()
        release = self._release()
        release["assets"] = [asset for asset in release["assets"]
                             if asset["name"] != "master_data.zip"]
        logs = self._run_update(release, self._remote())
        self.assertIn("主数据附件", logs)
        self.assertEqual(core.load_version(self.game)["version"], "20250101")

    def test_same_version_missing_master_state_still_repairs_master_data(self):
        """版本号已相同但主数据状态缺失时,仍下载并播种主数据。"""
        self._set_repo()
        self._make_app()
        release = self._release()
        remote = self._remote()
        self._run_update(release, remote)

        local = core.load_version(self.game)
        local.pop("master_data_md5", None)
        core.save_version(self.game, local)
        seed_file = os.path.join(core.local_low_seed_dir(self.game), *self.MASTER_REL.split("/"))
        os.remove(seed_file)

        logs, calls = self._run_update_with_asset_calls(release, remote)

        self.assertIn("主数据", logs)
        self.assertIn("http://x/master_data.zip", calls)
        self.assertTrue(os.path.isfile(seed_file))

    def test_same_version_with_matching_declared_outputs_does_not_download(self):
        """版本号与 Release 声明的产物均一致时,不再发起资产下载。"""
        self._set_repo()
        self._make_app()
        release = self._release()
        remote = self._remote()
        self._run_update(release, remote)

        local = core.load_version(self.game)
        local.update({
            "plugin_md5": remote["plugin_md5"],
            "stories_md5": remote["stories_md5"],
            "catalog_hash": remote["catalog_hash"],
            "catalog_bin_md5": remote["catalog_bin_md5"],
            "master_data_md5": remote["master_data_md5"],
            "version": remote["version"],
        })
        core.save_version(self.game, local)

        logs, calls = self._run_update_with_asset_calls(release, remote)

        self.assertIn("已是最新", logs)
        self.assertEqual(calls, [])

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

    def test_quiet_same_version_missing_master_record_sets_update_button(self):
        """同版本但主数据记录缺失时,静默检查必须提示补齐。"""
        self._set_repo()
        self._make_app()
        release = self._release()
        remote = self._remote()
        self._run_update(release, remote)

        local = core.load_version(self.game)
        self.assertEqual(local["version"], remote["version"])
        local.pop("master_data_md5", None)
        core.save_version(self.game, local)

        with mock.patch.object(launcher.App, "_fetch_remote",
                               lambda self_: (release, remote)):
            self.app._check_update_quiet()
        self.app._poll_queue()

        self.assertEqual(str(self.app.btn_update["text"]), "有更新")
        self.assertIn("本地产物未完全就绪", self._log_text())

    def test_quiet_same_version_with_all_records_ready_is_silent(self):
        """同版本且记录、主数据种子均就绪时,静默检查不改文案也不提示。"""
        self._set_repo()
        self._make_app()
        release = self._release()
        remote = self._remote()
        self._run_update(release, remote)
        before_text = str(self.app.btn_update["text"])
        before_log = self._log_text()

        with mock.patch.object(launcher.App, "_fetch_remote",
                               lambda self_: (release, remote)):
            self.app._check_update_quiet()
        self.app._poll_queue()

        self.assertEqual(str(self.app.btn_update["text"]), before_text)
        self.assertEqual(self._log_text(), before_log)
        self.assertEqual(self._drain(), "")

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
            "master_data.zip": self._master_data_zip(),
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
