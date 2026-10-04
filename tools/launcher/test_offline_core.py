#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dotabyss_offline_core 单元测试:版本文件、配置检查/修复、安装、探针与更新解析。

运行:``D:\\Python\\python.exe test_offline_core.py``(标准库 unittest)。
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dotabyss_offline_core as core  # noqa: E402


def _md5(data: bytes) -> str:
    """返回字节串的 MD5 十六进制摘要(测试用)。"""
    return hashlib.md5(data).hexdigest()


def _asset(name, url):
    """构造 GitHub Release 附件字典。"""
    return {"name": name, "browser_download_url": url}


class ParseLatestReleaseTest(unittest.TestCase):
    """parse_latest_release:空/缺失/完整附件表。"""

    def test_empty_assets(self):
        parsed = core.parse_latest_release({"tag_name": "20260101", "assets": []})
        self.assertEqual(parsed["tag"], "20260101")
        self.assertIsNone(parsed["plugin_dll_url"])
        self.assertIsNone(parsed["version_json_url"])

    def test_missing_assets_key(self):
        parsed = core.parse_latest_release({})
        self.assertIsNone(parsed["stories_url"])
        self.assertEqual(parsed["assets_by_name"], {})

    def test_full_assets(self):
        payload = {"tag_name": "20260102", "assets": [
            _asset("version.json", "http://x/version.json"),
            _asset("StoryViewer.dll", "http://x/dll"),
            _asset("stories.json", "http://x/stories"),
            _asset("previews.zip", "http://x/previews.zip"),
            _asset("player_docs.zip", "http://x/docs.zip"),
            _asset(core.LAUNCHER_EXE_NAME, "http://x/launcher.exe"),
            _asset("master_data.zip", "http://x/master_data.zip"),
        ]}
        parsed = core.parse_latest_release(payload)
        self.assertEqual(parsed["version_json_url"], "http://x/version.json")
        self.assertEqual(parsed["plugin_dll_url"], "http://x/dll")
        self.assertEqual(parsed["stories_url"], "http://x/stories")
        self.assertEqual(parsed["previews_zip_url"], "http://x/previews.zip")
        self.assertEqual(parsed["player_docs_url"], "http://x/docs.zip")
        self.assertEqual(parsed["launcher_exe_url"], "http://x/launcher.exe")
        self.assertEqual(parsed["master_data_url"], "http://x/master_data.zip")

    def test_case_sensitive_names(self):
        payload = {"assets": [_asset("storyviewer.dll", "http://x/wrong")]}
        parsed = core.parse_latest_release(payload)
        self.assertIsNone(parsed["plugin_dll_url"])
        self.assertEqual(parsed["assets_by_name"]["storyviewer.dll"], "http://x/wrong")

    def test_asset_without_url_is_skipped(self):
        payload = {"assets": [{"name": "stories.json"}]}
        parsed = core.parse_latest_release(payload)
        self.assertIsNone(parsed["stories_url"])


class FileNeedsUpdateTest(unittest.TestCase):
    """file_needs_update:空期望/缺文件/相同/不同。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "data.bin")

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_expected_is_false(self):
        self.assertFalse(core.file_needs_update(self.path, ""))

    def test_missing_file_true(self):
        self.assertTrue(core.file_needs_update(self.path, _md5(b"x")))

    def test_same_md5_false(self):
        with open(self.path, "wb") as handle:
            handle.write(b"abc")
        self.assertFalse(core.file_needs_update(self.path, _md5(b"abc")))

    def test_different_md5_true(self):
        with open(self.path, "wb") as handle:
            handle.write(b"abc")
        self.assertTrue(core.file_needs_update(self.path, _md5(b"abd")))

    def test_uppercase_expected_matches(self):
        with open(self.path, "wb") as handle:
            handle.write(b"abc")
        self.assertFalse(core.file_needs_update(self.path, _md5(b"abc").upper()))


class InstallBytesTest(unittest.TestCase):
    """install_bytes:写入/备份/校验失败不留半截文件。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "sub", "target.bin")

    def tearDown(self):
        self.tmp.cleanup()

    def test_replace_writes_and_backs_up(self):
        os.makedirs(os.path.dirname(self.dest), exist_ok=True)
        with open(self.dest, "wb") as handle:
            handle.write(b"old")
        message = core.install_bytes(self.dest, b"new", _md5(b"new"), "20260101")
        self.assertIn("已安装", message)
        with open(self.dest, "rb") as handle:
            self.assertEqual(handle.read(), b"new")
        self.assertTrue(os.path.isfile(self.dest + ".bak_update_20260101"))

    def test_replace_false_leaves_new_only(self):
        os.makedirs(os.path.dirname(self.dest), exist_ok=True)
        with open(self.dest, "wb") as handle:
            handle.write(b"old")
        core.install_bytes(self.dest, b"new", _md5(b"new"), "20260101", replace=False)
        with open(self.dest, "rb") as handle:
            self.assertEqual(handle.read(), b"old")
        with open(self.dest + ".new", "rb") as handle:
            self.assertEqual(handle.read(), b"new")

    def test_bad_md5_keeps_old_and_no_new(self):
        os.makedirs(os.path.dirname(self.dest), exist_ok=True)
        with open(self.dest, "wb") as handle:
            handle.write(b"old")
        with self.assertRaises(ValueError):
            core.install_bytes(self.dest, b"new", _md5(b"other"), "20260101")
        with open(self.dest, "rb") as handle:
            self.assertEqual(handle.read(), b"old")
        self.assertFalse(os.path.exists(self.dest + ".new"))

    def test_missing_parent_created(self):
        core.install_bytes(self.dest, b"new", _md5(b"new"), "20260101")
        self.assertTrue(os.path.isfile(self.dest))

    def test_backup_false_skips_bak_update(self):
        os.makedirs(os.path.dirname(self.dest), exist_ok=True)
        with open(self.dest, "wb") as handle:
            handle.write(b"old")
        core.install_bytes(self.dest, b"new", _md5(b"new"), "20260101", backup=False)
        self.assertFalse(os.path.exists(self.dest + ".bak_update_20260101"))


class LauncherReplaceCmdTest(unittest.TestCase):
    """build_launcher_replace_cmd 与 pending_launcher_swap(含真实替换演练)。"""

    def test_cmd_script_quotes_paths(self):
        game_dir = tempfile.mkdtemp()
        script = core.build_launcher_replace_cmd(game_dir)
        self.assertIsInstance(script, str)
        self.assertIn('move /Y "', script)
        self.assertIn(".new", script)
        self.assertIn(core.LAUNCHER_EXE_NAME, script)
        self.assertIn('start ""', script)

    def test_pending_true_iff_new_exists(self):
        game_dir = tempfile.mkdtemp()
        self.assertFalse(core.pending_launcher_swap(game_dir))
        with open(core.launcher_path(game_dir) + ".new", "wb") as handle:
            handle.write(b"x")
        self.assertTrue(core.pending_launcher_swap(game_dir))

    def test_replace_script_actually_replaces_exe(self):
        """回归测试:cmd /c 脚本必须以 shell 形式执行,argv 列表形式会静默失败。

        用 ping 127.0.0.1 -n 2 缩短等待(约 1 秒),轮询目标文件内容变化。
        """
        game_dir = tempfile.mkdtemp(prefix="dotabyss_replace_")
        exe = core.launcher_path(game_dir)
        with open(exe, "wb") as handle:
            handle.write(b"old-launcher")
        with open(exe + ".new", "wb") as handle:
            handle.write(b"new-launcher")
        script = core.build_launcher_replace_cmd(game_dir).replace("-n 3", "-n 2")
        script = script.replace('start "" "%s"' % exe, "rem skip-start")
        subprocess.Popen(script, shell=True, cwd=game_dir, close_fds=True,
                         creationflags=0x00000008 | 0x00000200)
        deadline = time.time() + 15
        content = b"old-launcher"
        while time.time() < deadline:
            with open(exe, "rb") as handle:
                content = handle.read()
            if content == b"new-launcher":
                break
            time.sleep(0.5)
        self.assertEqual(content, b"new-launcher")
        self.assertFalse(os.path.isfile(exe + ".new"))


class VersionFileTest(unittest.TestCase):
    """load_version/save_version 往返与容错。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip(self):
        core.save_version(self.tmp.name, {"version": "20260925", "first_ready": True})
        data = core.load_version(self.tmp.name)
        self.assertEqual(data["version"], "20260925")
        self.assertTrue(data["first_ready"])

    def test_missing_returns_defaults(self):
        data = core.load_version(self.tmp.name)
        self.assertEqual(data["version"], "")
        self.assertFalse(data["first_ready"])

    def test_broken_json_returns_defaults(self):
        path = core.version_path(self.tmp.name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        data = core.load_version(self.tmp.name)
        self.assertEqual(data["version"], "")

    def test_defaults_are_independent_copies(self):
        first = core.load_version(self.tmp.name)
        first["version"] = "mutated"
        second = core.load_version(self.tmp.name)
        self.assertEqual(second["version"], "")


class ConfigStatusRepairTest(unittest.TestCase):
    """offline_config_status / repair_config:齐全/缺失/错值/保留其它段。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def _write_cfg(self, text):
        """把文本写进插件配置文件。"""
        path = core.config_path(self.tmp.name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    def _offline_cfg(self):
        """返回一份所有离线键都正确的配置文本。"""
        return "[Offline]\n" + "\n".join(
            "%s = %s" % pair for pair in core.OFFLINE_KEYS) + "\n"

    def test_missing_file(self):
        ok, detail = core.offline_config_status(self.tmp.name)
        self.assertFalse(ok)
        self.assertIn("缺失", detail)

    def test_full_offline_cfg_passes(self):
        self._write_cfg(self._offline_cfg())
        ok, detail = core.offline_config_status(self.tmp.name)
        self.assertTrue(ok)

    def test_wrong_value_fails(self):
        self._write_cfg(self._offline_cfg().replace("OfflineAuth = true",
                                                    "OfflineAuth = false"))
        ok, detail = core.offline_config_status(self.tmp.name)
        self.assertFalse(ok)
        self.assertIn("OfflineAuth", detail)

    def test_case_insensitive_value(self):
        self._write_cfg(self._offline_cfg().replace("OfflineAuth = true",
                                                    "OfflineAuth = True"))
        ok, _ = core.offline_config_status(self.tmp.name)
        self.assertTrue(ok)

    def test_repair_creates_file(self):
        core.repair_config(self.tmp.name)
        ok, _ = core.offline_config_status(self.tmp.name)
        self.assertTrue(ok)

    def test_repair_preserves_other_sections_and_fixes_value(self):
        self._write_cfg("[General]\nSkipDebug = true\n\n[Offline]\nOfflineAuth = false\n")
        core.repair_config(self.tmp.name)
        ok, _ = core.offline_config_status(self.tmp.name)
        self.assertTrue(ok)
        with open(core.config_path(self.tmp.name), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("SkipDebug = true", text)
        self.assertNotIn("OfflineAuth = false", text)

    def test_repair_is_idempotent(self):
        core.repair_config(self.tmp.name)
        core.repair_config(self.tmp.name)
        ok, _ = core.offline_config_status(self.tmp.name)
        self.assertTrue(ok)

    def test_repair_extra_defaults(self):
        core.repair_config(self.tmp.name, extra_defaults={"SkipDebug": "false"})
        with open(core.config_path(self.tmp.name), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("SkipDebug = false", text)

    def test_repair_inserts_into_existing_offline_section(self):
        self._write_cfg("[Offline]\nApiPort = 18923\n\n[Debug]\nSkipDebug = true\n")
        core.repair_config(self.tmp.name)
        with open(core.config_path(self.tmp.name), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("ApiPort = 18923", text)
        # 新键必须位于 [Offline] 段内,而不是越过 [Debug] 掉到文末
        offline_part = text.split("[Debug]")[0]
        self.assertIn("OfflineAuth = true", offline_part)


class ExtractZipBytesTest(unittest.TestCase):
    """extract_zip_bytes:正常解压/上跳拒绝/盘符拒绝/白名单。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def _zip(self, entries):
        """把 ``[(name, bytes)]`` 打成内存 zip。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return buffer.getvalue()

    def test_plain_relative_paths(self):
        raw = self._zip([("previews/a.png", b"1"), ("previews/b.png", b"2")])
        count = core.extract_zip_bytes(raw, self.tmp.name)
        self.assertEqual(count, 2)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "previews", "a.png")))

    def test_parent_path_rejected_and_nothing_written(self):
        raw = self._zip([("ok.png", b"1"), ("../evil.txt", b"2")])
        with self.assertRaises(ValueError):
            core.extract_zip_bytes(raw, self.tmp.name)
        self.assertFalse(os.path.isfile(os.path.join(self.tmp.name, "ok.png")))

    def test_absolute_path_rejected(self):
        raw = self._zip([("/abs.txt", b"1")])
        with self.assertRaises(ValueError):
            core.extract_zip_bytes(raw, self.tmp.name)

    def test_drive_letter_rejected(self):
        raw = self._zip([("C:/abs.txt", b"1")])
        with self.assertRaises(ValueError):
            core.extract_zip_bytes(raw, self.tmp.name)

    def test_whitelist_allows_only_listed(self):
        raw = self._zip([("使用说明.md", b"1"), ("extra.txt", b"2")])
        with self.assertRaises(ValueError):
            core.extract_zip_bytes(raw, self.tmp.name,
                                   allowed_names=("使用说明.md",))
        self.assertFalse(os.path.isfile(os.path.join(self.tmp.name, "使用说明.md")))

    def test_whitelist_accepts_single_listed_file(self):
        raw = self._zip([("使用说明.md", b"1")])
        count = core.extract_zip_bytes(raw, self.tmp.name,
                                       allowed_names=("使用说明.md",))
        self.assertEqual(count, 1)

    def test_empty_zip(self):
        raw = self._zip([])
        self.assertEqual(core.extract_zip_bytes(raw, self.tmp.name), 0)


class HealthCheckTest(unittest.TestCase):
    """health_check 在空白目录/搭好骨架后的结果。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _mk(self, rel, data=b"x"):
        """在游戏根下创建文件(自动建父目录)。"""
        path = os.path.join(self.game, *rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def _item(self, items, name):
        """按名取检查项。"""
        return next(item for item in items if item.name == name)

    def test_empty_dir_fails_core_items(self):
        items = core.health_check(self.game)
        for name in ("exe", "winhttp.dll", "BepInEx", "plugin",
                     "stories.json", "previews", "cfg", "cache", "version"):
            self.assertFalse(self._item(items, name).ok, name)

    def test_stub_dir_passes_local_items(self):
        self._mk((core.EXE_NAME,), b"exe")
        self._mk(("winhttp.dll",), b"dll")
        self._mk(("BepInEx", "core", "BepInEx.Core.dll"), b"core")
        self._mk(("BepInEx", "plugins", "StoryViewer", "StoryViewer.dll"), b"plugin")
        self._mk(("BepInEx", "plugins", "StoryViewer", "stories.json"),
                 json.dumps({"stories": [{"k": "mas_x"}] * core.STORIES_MIN_COUNT}).encode())
        self._mk(("BepInEx", "plugins", "StoryViewer", "previews", "a.png"))
        self._mk(("BepInEx", "plugins", "StoryViewer", "offline_version.json"),
                 b'{"version":"20260925"}')
        self._mk(("ドットアビスX_Data", "Caches", "bundleA", "hash", "__data"))
        core.repair_config(self.game)
        items = core.health_check(self.game)
        for name in ("exe", "winhttp.dll", "BepInEx", "plugin", "stories.json",
                     "previews", "cfg", "zone", "port", "version"):
            self.assertTrue(self._item(items, name).ok, name)

    def test_cache_below_threshold_fails(self):
        self._mk(("ドットアビスX_Data", "Caches", "bundleA", "hash", "__data"))
        items = core.health_check(self.game)
        self.assertFalse(self._item(items, "cache").ok)

    def test_stories_too_few_fails(self):
        self._mk(("BepInEx", "plugins", "StoryViewer", "stories.json"),
                 json.dumps({"stories": [{"k": "mas_x"}]}).encode())
        items = core.health_check(self.game)
        self.assertFalse(self._item(items, "stories.json").ok)

    def test_stories_broken_json_fails(self):
        self._mk(("BepInEx", "plugins", "StoryViewer", "stories.json"), b"{oops")
        items = core.health_check(self.game)
        item = self._item(items, "stories.json")
        self.assertFalse(item.ok)
        self.assertIn("无法解析", item.detail)

    def test_zone_identifier_flagged(self):
        self._mk((core.EXE_NAME,), b"exe")
        self._mk((core.EXE_NAME + ":Zone.Identifier",), b"[ZoneTransfer]")
        items = core.health_check(self.game)
        self.assertFalse(self._item(items, "zone").ok)

    def test_zone_identifier_stat_false_positive_is_ignored(self):
        """不可读取的伪 ADS 路径不应被当成真实 Zone.Identifier。"""
        self._mk((core.EXE_NAME,), b"exe")
        exe = os.path.join(self.game, core.EXE_NAME)
        real_isfile = os.path.isfile

        def false_positive(path):
            """模拟 Windows 对不可读取 ADS 路径的属性误报。"""
            if path == exe + core._ZONE_STREAM:
                return True
            return real_isfile(path)

        with mock.patch.object(core.os.path, "isfile", side_effect=false_positive):
            item = core._zone_check([exe])
        self.assertTrue(item.ok)


class IndexProbeTest(unittest.TestCase):
    """index_probe:前缀统计、封面计数、端口可绑定。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _mk(self, rel, data=b"x"):
        path = os.path.join(self.game, *rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def test_empty_dir_reports_failures(self):
        items = core.index_probe(self.game)
        by_name = {item.name: item for item in items}
        self.assertFalse(by_name["cfg"].ok)
        self.assertFalse(by_name["stories.json"].ok)

    def test_stub_dir_reports_prefix_breakdown(self):
        entries = ([{"k": "mas_a"}] * 2 + [{"k": "men_b"}] * 1
                   + [{"k": "hmn_c"}] * 1 + [{"k": "hmr_d"}] * 1
                   + [{"k": "evs_e"}] * 1 + [{"key": "unknown"}] * 1)
        padding = [{"k": "zzz_pad"}] * (core.STORIES_MIN_COUNT - len(entries))
        payload = json.dumps({"series": [], "stories": entries + padding}).encode()
        self._mk(("BepInEx", "plugins", "StoryViewer", "stories.json"), payload)
        self._mk(("BepInEx", "plugins", "StoryViewer", "previews", "a.png"))
        core.repair_config(self.game)
        items = core.index_probe(self.game)
        by_name = {item.name: item for item in items}
        self.assertTrue(by_name["cfg"].ok)
        self.assertTrue(by_name["stories.json"].ok)
        self.assertIn("mas 2", by_name["stories.json"].detail)
        self.assertIn("其它 94", by_name["stories.json"].detail)
        self.assertTrue(by_name["previews"].ok)


class MiscTest(unittest.TestCase):
    """cache_entry_count / read_github_repo / file_md5。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_cache_entry_count_empty(self):
        self.assertEqual(core.cache_entry_count(self.tmp.name), 0)

    def test_cache_entry_count_counts_top_level(self):
        for name in ("a", "b", "c"):
            os.makedirs(os.path.join(core.cache_dir(self.tmp.name), name))
        with open(os.path.join(core.cache_dir(self.tmp.name), "__info"), "wb") as handle:
            handle.write(b"unity metadata")
        self.assertEqual(core.cache_entry_count(self.tmp.name), 3)

    def test_read_github_repo_missing(self):
        self.assertEqual(core.read_github_repo(self.tmp.name), "")

    def test_read_github_repo_ok(self):
        with open(core.launcher_json_path(self.tmp.name), "w", encoding="utf-8") as handle:
            json.dump({"github_repo": " user/repo "}, handle)
        self.assertEqual(core.read_github_repo(self.tmp.name), "user/repo")

    def test_read_github_repo_broken(self):
        with open(core.launcher_json_path(self.tmp.name), "w", encoding="utf-8") as handle:
            handle.write("{oops")
        self.assertEqual(core.read_github_repo(self.tmp.name), "")

    def test_file_md5(self):
        path = os.path.join(self.tmp.name, "x.bin")
        with open(path, "wb") as handle:
            handle.write(b"abc")
        self.assertEqual(core.file_md5(path), _md5(b"abc"))

    def test_plugin_file_version_missing(self):
        self.assertEqual(core.plugin_file_version(self.tmp.name), "")

    def test_plugin_dll_path_shape(self):
        path = core.plugin_dll_path(self.tmp.name)
        self.assertTrue(path.endswith(os.path.join("StoryViewer", "StoryViewer.dll")))


class IdentityTest(unittest.TestCase):
    """离线身份:app.info 读取/打补丁、Unity 路径清洗、LocalLow 推导。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name
        self.base = os.path.join(self.tmp.name, "LocalLowBase")
        self._old_env = os.environ.get(core.LOCAL_LOW_ENV)
        os.environ[core.LOCAL_LOW_ENV] = self.base

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop(core.LOCAL_LOW_ENV, None)
        else:
            os.environ[core.LOCAL_LOW_ENV] = self._old_env
        self.tmp.cleanup()

    def _write_app_info(self, text):
        """写 app.info(可传 str 或 bytes,以保留换行样式)。"""
        path = core.app_info_path(self.game)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(data)

    def test_read_identity_missing(self):
        self.assertEqual(core.read_identity(self.game), ("", ""))

    def test_read_identity_single_line(self):
        self._write_app_info("EXNOA LLC.\n")
        self.assertEqual(core.read_identity(self.game), ("", ""))

    def test_read_identity_normal(self):
        self._write_app_info("EXNOA LLC.\nドットアビスX")
        self.assertEqual(core.read_identity(self.game), ("EXNOA LLC.", "ドットアビスX"))

    def test_ensure_identity_patches_product_and_backs_up(self):
        self._write_app_info("EXNOA LLC.\nドットアビスX")
        message = core.ensure_offline_identity(self.game)
        self.assertIn("_offline", message)
        self.assertEqual(core.read_identity(self.game), ("EXNOA LLC.", "ドットアビスX_offline"))
        with open(core.app_info_path(self.game), "rb") as handle:
            self.assertFalse(handle.read().endswith(b"\n"))  # 无尾换行样式保留
        self.assertTrue(os.path.isfile(core.app_info_path(self.game) + ".bak_original"))

    def test_ensure_identity_preserves_trailing_newline(self):
        self._write_app_info("EXNOA LLC.\nドットアビスX\n")
        core.ensure_offline_identity(self.game)
        with open(core.app_info_path(self.game), "rb") as handle:
            self.assertTrue(handle.read().endswith(b"\n"))

    def test_ensure_identity_idempotent(self):
        self._write_app_info("EXNOA LLC.\nドットアビスX_offline")
        message = core.ensure_offline_identity(self.game)
        self.assertIn("已就绪", message)
        self.assertFalse(os.path.isfile(core.app_info_path(self.game) + ".bak_original"))

    def test_ensure_identity_missing_file(self):
        self.assertIn("缺失", core.ensure_offline_identity(self.game))

    def test_sanitize_trailing_dot(self):
        self.assertEqual(core._sanitize_path_part("EXNOA LLC."), "EXNOA LLC_")

    def test_sanitize_invalid_chars(self):
        self.assertEqual(core._sanitize_path_part('a<b>c:d"e/f\\g|h?i*j'), "a_b_c_d_e_f_g_h_i_j")

    def test_sanitize_plain_name_unchanged(self):
        self.assertEqual(core._sanitize_path_part("ドットアビスX"), "ドットアビスX")

    def test_local_low_dir_uses_env_override_and_offline_product(self):
        self._write_app_info("EXNOA LLC.\nドットアビスX_offline")
        expected = os.path.join(self.base, "EXNOA LLC_", "ドットアビスX_offline")
        self.assertEqual(core.local_low_dir(self.game), expected)
        self.assertEqual(core.local_low_catalog_dir(self.game),
                         os.path.join(expected, "com.unity.addressables"))

    def test_local_low_catalog_dirs_prefers_offline_then_original(self):
        self._write_app_info("EXNOA LLC.\nドットアビスX_offline")
        self.assertEqual(core.local_low_catalog_dirs(self.game), [
            os.path.join(self.base, "EXNOA LLC_", "ドットアビスX_offline", "com.unity.addressables"),
            os.path.join(self.base, "EXNOA LLC_", "ドットアビスX", "com.unity.addressables"),
        ])

    def test_local_low_dir_empty_without_app_info(self):
        self.assertEqual(core.local_low_dir(self.game), "")
        self.assertEqual(core.local_low_catalog_dirs(self.game), [])


def _zip_bytes(entries) -> bytes:
    """把 ``[(name, bytes)]`` 打成内存 zip(测试用)。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


class CatalogSeedTest(unittest.TestCase):
    """catalog 种子:选取、写包、播种 LocalLow(幂等/哈希校验/失败保护)。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name
        self.base = os.path.join(self.tmp.name, "LocalLowBase")
        self._old_env = os.environ.get(core.LOCAL_LOW_ENV)
        os.environ[core.LOCAL_LOW_ENV] = self.base
        self._write("EXNOA LLC.\nドットアビスX_offline", core.app_info_path(self.game))

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop(core.LOCAL_LOW_ENV, None)
        else:
            os.environ[core.LOCAL_LOW_ENV] = self._old_env
        self.tmp.cleanup()

    def _write(self, data, path):
        """写文件(自动建父目录)。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data if isinstance(data, bytes) else data.encode("utf-8"))

    def _seed(self, data=b"BIN", hash_text="hash-abc",
              bin_name=core.CATALOG_BIN_NAME, hash_name=core.CATALOG_HASH_NAME):
        """写包内 catalog 种子。"""
        self._write(data, os.path.join(core.catalog_seed_dir(self.game), bin_name))
        if hash_name:
            self._write(hash_text, os.path.join(core.catalog_seed_dir(self.game), hash_name))

    def test_newest_catalog_pair_picks_latest_mtime(self):
        directory = os.path.join(self.tmp.name, "cats")
        os.makedirs(directory, exist_ok=True)
        older = os.path.join(directory, "111.bin")
        newer = os.path.join(directory, "222.bin")
        for path, when in ((older, 1000), (newer, 2000)):
            with open(path, "wb") as handle:
                handle.write(b"x")
            with open(path + ".hash", "w", encoding="utf-8") as handle:
                handle.write("h")
            os.utime(path, (when, when))
        self.assertEqual(core.newest_catalog_pair(directory), (newer, newer + ".hash"))

    def test_newest_catalog_pair_empty_and_missing(self):
        self.assertEqual(core.newest_catalog_pair(""), ("", ""))
        self.assertEqual(core.newest_catalog_pair(os.path.join(self.tmp.name, "none")), ("", ""))

    def test_hash_naming_variant_without_bin_suffix(self):
        directory = os.path.join(self.tmp.name, "cats2")
        os.makedirs(directory, exist_ok=True)
        binary = os.path.join(directory, "999.bin")
        with open(binary, "wb") as handle:
            handle.write(b"x")
        with open(os.path.join(directory, "999.hash"), "w", encoding="utf-8") as handle:
            handle.write("h")
        self.assertEqual(core.newest_catalog_pair(directory)[1],
                         os.path.join(directory, "999.hash"))

    def test_write_catalog_seed_requires_hash(self):
        source = os.path.join(self.tmp.name, "src.bin")
        self._write(b"BIN", source)
        with self.assertRaises(ValueError):
            core.write_catalog_seed(self.game, source, "")

    def test_write_catalog_seed_missing_source(self):
        with self.assertRaises(ValueError):
            core.write_catalog_seed(self.game, os.path.join(self.tmp.name, "no.bin"), "")

    def test_write_catalog_seed_fixed_names_and_hash_md5(self):
        source_bin = os.path.join(self.tmp.name, "src.bin")
        source_hash = os.path.join(self.tmp.name, "src.hash")
        self._write(b"NEW-BIN", source_bin)
        self._write("cafe1234", source_hash)
        message = core.write_catalog_seed(self.game, source_bin, source_hash)
        self.assertIn("catalog 种子", message)
        self.assertEqual(core.catalog_seed_hash(self.game), "cafe1234")
        self.assertEqual(core.seed_catalog_pair(self.game)[0],
                         os.path.join(core.catalog_seed_dir(self.game), core.CATALOG_BIN_NAME))

    def test_seed_catalog_hash_empty_without_seed(self):
        self.assertEqual(core.catalog_seed_hash(self.game), "")

    def test_seed_to_local_low_copies_and_is_idempotent(self):
        self._seed()
        first = core.seed_catalog_to_local_low(self.game)
        self.assertIn("已播种", first[0])
        target = core.local_low_catalog_dir(self.game)
        self.assertTrue(os.path.isfile(os.path.join(target, core.CATALOG_BIN_NAME)))
        self.assertTrue(os.path.isfile(os.path.join(target, core.CATALOG_HASH_NAME)))
        second = core.seed_catalog_to_local_low(self.game)
        self.assertIn("已就绪", second[0])

    def test_seed_reinstalls_when_hash_differs(self):
        self._seed(hash_text="new-hash")
        target = core.local_low_catalog_dir(self.game)
        self._write(b"OLD-BIN", os.path.join(target, core.CATALOG_BIN_NAME))
        self._write("old-hash", os.path.join(target, core.CATALOG_HASH_NAME))
        lines = core.seed_catalog_to_local_low(self.game)
        self.assertIn("已播种", lines[0])
        with open(os.path.join(target, core.CATALOG_BIN_NAME), "rb") as handle:
            self.assertEqual(handle.read(), b"BIN")

    def test_seed_missing_seed_message(self):
        lines = core.seed_catalog_to_local_low(self.game)
        self.assertIn("缺 catalog 种子", lines[0])

    def test_seed_without_app_info_message(self):
        broken = os.path.join(self.tmp.name, "no_identity")
        seed_dir = core.catalog_seed_dir(broken)
        self._write(b"BIN", os.path.join(seed_dir, core.CATALOG_BIN_NAME))
        self._write("h", os.path.join(seed_dir, core.CATALOG_HASH_NAME))
        lines = core.seed_catalog_to_local_low(broken)
        self.assertIn("无法确定存档目录", lines[0])

    def test_source_pair_prefers_offline_then_original(self):
        offline_dir = core.local_low_catalog_dir(self.game)
        original_dir = core.local_low_catalog_dirs(self.game)[1]
        self._write(b"OFFLINE", os.path.join(offline_dir, "1.bin"))
        self._write("h1", os.path.join(offline_dir, "1.bin.hash"))
        self._write(b"ORIGINAL", os.path.join(original_dir, "2.bin"))
        self._write("h2", os.path.join(original_dir, "2.bin.hash"))
        self.assertEqual(core.source_catalog_pair(self.game)[0],
                         os.path.join(offline_dir, "1.bin"))

    def test_install_catalog_from_bytes_replaces_with_backup(self):
        self._seed(hash_text="old-hash")
        message = core.install_catalog_from_bytes(self.game, b"FRESH", b"new-hash", "t1")
        self.assertIn("catalog", message)
        self.assertEqual(core.catalog_seed_hash(self.game), "new-hash")
        bin_path = os.path.join(core.catalog_seed_dir(self.game), core.CATALOG_BIN_NAME)
        with open(bin_path, "rb") as handle:
            self.assertEqual(handle.read(), b"FRESH")
        self.assertTrue(os.path.isfile(bin_path + ".bak_t1"))

    def test_seed_local_low_extras_copies_missing_only(self):
        target = core.local_low_dir(self.game)
        seed_dir = core.local_low_seed_dir(self.game)
        self._write(b"RUNTIME-CFG", os.path.join(seed_dir, "AbsfRuntimeConfig.dat"))
        self._write(b"EXTRA", os.path.join(seed_dir, "SomeOther.dat"))
        self._write(b"MASTER-DATA", os.path.join(seed_dir, "DownloadCache", "master.dat"))
        lines = core.seed_local_low_extras(self.game)
        self.assertEqual(len(lines), 3)
        with open(os.path.join(target, "AbsfRuntimeConfig.dat"), "rb") as handle:
            self.assertEqual(handle.read(), b"RUNTIME-CFG")
        with open(os.path.join(target, "DownloadCache", "master.dat"), "rb") as handle:
            self.assertEqual(handle.read(), b"MASTER-DATA")
        # 玩家已有文件绝不被覆盖
        self._write(b"PLAYER-OWN", os.path.join(target, "AbsfRuntimeConfig.dat"))
        self.assertEqual(core.seed_local_low_extras(self.game), [])
        with open(os.path.join(target, "AbsfRuntimeConfig.dat"), "rb") as handle:
            self.assertEqual(handle.read(), b"PLAYER-OWN")

    def test_seed_master_data_replaces_old_cache_but_preserves_other_files(self):
        """主数据缓存允许替换旧/残缺版本,其它 LocalLow 文件仍只补缺失。"""
        target = core.local_low_dir(self.game)
        seed_dir = core.local_low_seed_dir(self.game)
        self._write(b"MASTER-NEW", os.path.join(seed_dir, "DownloadCache", "master.dat"))
        self._write(b"MASTER-OLD", os.path.join(target, "DownloadCache", "master.dat"))
        self._write(b"CACHE-PLAYER-NEW", os.path.join(seed_dir, "DownloadCache", "player.save"))
        self._write(b"CACHE-PLAYER-OLD", os.path.join(target, "DownloadCache", "player.save"))
        self._write(b"PLAYER-OLD", os.path.join(target, "player.save"))
        self._write(b"PLAYER-NEW", os.path.join(seed_dir, "player.save"))

        lines = core.seed_local_low_extras(self.game)

        self.assertIn("主数据", " ".join(lines))
        with open(os.path.join(target, "DownloadCache", "master.dat"), "rb") as handle:
            self.assertEqual(handle.read(), b"MASTER-NEW")
        with open(os.path.join(target, "DownloadCache", "player.save"), "rb") as handle:
            self.assertEqual(handle.read(), b"CACHE-PLAYER-OLD")
        with open(os.path.join(target, "player.save"), "rb") as handle:
            self.assertEqual(handle.read(), b"PLAYER-OLD")

    def test_seed_local_low_extras_without_seed_dir_is_noop(self):
        self.assertEqual(core.seed_local_low_extras(self.game), [])

    def test_seed_local_low_extras_without_identity_message(self):
        broken = os.path.join(self.tmp.name, "no_id2")
        self._write(b"x", os.path.join(core.local_low_seed_dir(broken), "AbsfRuntimeConfig.dat"))
        lines = core.seed_local_low_extras(broken)
        self.assertIn("无法确定存档目录", lines[0])


class DeltaInstallTest(unittest.TestCase):
    """差量清单:路径校验、todo 计算、zip 成员安装(先验后写)。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel, data=b"x"):
        """在游戏根写文件(rel 用 / 分隔)。"""
        path = os.path.join(self.game, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_rel_path_safe_ok(self):
        expected = os.path.join(self.game, "ドットアビスX_Data", "Managed", "A.dll")
        self.assertEqual(core.rel_path_safe(self.game, "ドットアビスX_Data/Managed/A.dll"), expected)

    def test_rel_path_safe_normalizes_backslashes_and_dots(self):
        expected = os.path.join(self.game, "a", "b")
        self.assertEqual(core.rel_path_safe(self.game, "a\\./b"), expected)

    def test_rel_path_safe_rejects_bad_input(self):
        for rel in ("", "..", "../x", "a/../b", "/abs/x", "C:/x", "a//../b"):
            self.assertIsNone(core.rel_path_safe(self.game, rel), rel)

    def test_client_body_allowed_ok_paths(self):
        for rel in ("ドットアビスX.exe", "ドットアビスX_Data/Managed/Assembly-CSharp.dll",
                    "UnityPlayer.dll", "dotnet/System.dll"):
            self.assertTrue(core.client_body_rel_allowed(rel), rel)

    def test_client_body_allowed_blocked_paths(self):
        for rel in ("BepInEx/plugins/StoryViewer/StoryViewer.dll",
                    "ドットアビスX_Data/Caches/b/h/__data",
                    "app.info", "ドットアビスX_Data/app.info",
                    core.LAUNCHER_EXE_NAME, core.LAUNCHER_JSON_NAME, core.VERSION_NAME,
                    "使用说明.md", "check_health.bat", "BepInEx/LogOutput.log",
                    "BepInEx/plugins/StoryViewer/shots/a.png", "x.pdb"):
            self.assertFalse(core.client_body_rel_allowed(rel), rel)

    def test_caches_allowed_matrix(self):
        self.assertTrue(core.caches_rel_allowed(
            "ドットアビスX_Data/Caches/abc/0123456789abcdef0123456789abcdef/__data"))
        self.assertTrue(core.caches_rel_allowed(
            "ドットアビスX_Data/Caches/abc/0123456789abcdef0123456789abcdef/__info"))
        for rel in ("ドットアビスX_Data/Caches/abc/0123456789abcdef0123456789abcdef/__lock",
                    "ドットアビスX_Data/Caches/abc/__data",
                    "ドットアビスX_Data/Caches/abc/h/sub/__data",
                    "ドットアビスX_Data/Managed/A.dll", "Caches/a/b/__data"):
            self.assertFalse(core.caches_rel_allowed(rel), rel)

    def test_client_body_todo_missing_and_changed(self):
        self._write("ドットアビスX_Data/Managed/A.dll", b"old")
        self._write("ドットアビスX_Data/Managed/B.dll", b"same")
        files = {
            "ドットアビスX_Data/Managed/A.dll": _md5(b"new"),
            "ドットアビスX_Data/Managed/B.dll": _md5(b"same"),
            "ドットアビスX_Data/Managed/C.dll": _md5(b"new-file"),
        }
        self.assertEqual(core.client_body_todo(self.game, files), [
            "ドットアビスX_Data/Managed/A.dll", "ドットアビスX_Data/Managed/C.dll"])

    def test_client_body_todo_empty_and_empty_manifest(self):
        self.assertEqual(core.client_body_todo(self.game, {}), [])
        self.assertEqual(core.client_body_todo(self.game, None), [])

    def test_client_body_todo_rejects_disallowed(self):
        with self.assertRaises(ValueError):
            core.client_body_todo(self.game, {"BepInEx/plugins/x.dll": _md5(b"x")})
        with self.assertRaises(ValueError):
            core.client_body_todo(self.game, {"../evil.dll": _md5(b"x")})

    def test_caches_todo_missing_and_bad_shape(self):
        rel = "ドットアビスX_Data/Caches/b/abc/__data"
        self.assertEqual(core.caches_added_todo(self.game, {rel: _md5(b"x")}), [rel])
        self._write(rel, b"x")
        self.assertEqual(core.caches_added_todo(self.game, {rel: _md5(b"x")}), [])
        with self.assertRaises(ValueError):
            core.caches_added_todo(self.game, {"ドットアビスX_Data/evil.txt": _md5(b"x")})

    def test_install_zip_members_installs_and_returns_logs(self):
        rel = "ドットアビスX_Data/Managed/A.dll"
        data = _zip_bytes([(rel, b"new-bytes")])
        zip_path = os.path.join(self.tmp.name, "u.zip")
        with open(zip_path, "wb") as handle:
            handle.write(data)
        logs = core.install_zip_members(zip_path, self.game, {rel: _md5(b"new-bytes")}, "t")
        self.assertEqual(len(logs), 1)
        with open(os.path.join(self.game, *rel.split("/")), "rb") as handle:
            self.assertEqual(handle.read(), b"new-bytes")

    def test_install_zip_members_empty_mapping(self):
        zip_path = os.path.join(self.tmp.name, "empty.zip")
        with open(zip_path, "wb") as handle:
            handle.write(_zip_bytes([("a", b"x")]))
        self.assertEqual(core.install_zip_members(zip_path, self.game, {}, "t"), [])

    def test_install_zip_members_missing_member(self):
        zip_path = os.path.join(self.tmp.name, "u2.zip")
        with open(zip_path, "wb") as handle:
            handle.write(_zip_bytes([("other.dll", b"x")]))
        with self.assertRaises(ValueError):
            core.install_zip_members(zip_path, self.game,
                                     {"ドットアビスX_Data/Managed/A.dll": _md5(b"x")}, "t")

    def test_install_zip_members_md5_mismatch_writes_nothing(self):
        rel = "ドットアビスX_Data/Managed/A.dll"
        zip_path = os.path.join(self.tmp.name, "u3.zip")
        with open(zip_path, "wb") as handle:
            handle.write(_zip_bytes([(rel, b"actual")]))
        with self.assertRaises(ValueError):
            core.install_zip_members(zip_path, self.game, {rel: _md5(b"expected")}, "t")
        self.assertFalse(os.path.isfile(os.path.join(self.game, *rel.split("/"))))

    def test_install_zip_members_rejects_disallowed_and_traversal(self):
        zip_path = os.path.join(self.tmp.name, "u4.zip")
        with open(zip_path, "wb") as handle:
            handle.write(_zip_bytes([("../evil.dll", b"x")]))
        with self.assertRaises(ValueError):
            core.install_zip_members(zip_path, self.game, {"../evil.dll": _md5(b"x")}, "t")
        with self.assertRaises(ValueError):
            core.install_zip_members(
                zip_path, self.game, {"../evil.dll": _md5(b"x")}, "t",
                checker=core.client_body_rel_allowed)

    def test_install_zip_members_checker_blocks_client_body_paths(self):
        rel = "BepInEx/plugins/StoryViewer/StoryViewer.dll"
        zip_path = os.path.join(self.tmp.name, "u5.zip")
        with open(zip_path, "wb") as handle:
            handle.write(_zip_bytes([(rel, b"x")]))
        with self.assertRaises(ValueError):
            core.install_zip_members(zip_path, self.game, {rel: _md5(b"x")}, "t",
                                     checker=core.client_body_rel_allowed)


class BaselineTest(unittest.TestCase):
    """baseline_mismatch:两端缺失/相等/不等。"""

    def test_both_empty_is_false(self):
        self.assertFalse(core.baseline_mismatch({}, {}))
        self.assertFalse(core.baseline_mismatch(None, None))

    def test_one_missing_is_true(self):
        self.assertTrue(core.baseline_mismatch({"baseline": "20260924"}, {}))
        self.assertTrue(core.baseline_mismatch({}, {"baseline": "20260924"}))

    def test_equal_is_false_different_is_true(self):
        self.assertFalse(core.baseline_mismatch({"baseline": "20260924"}, {"baseline": "20260924"}))
        self.assertTrue(core.baseline_mismatch({"baseline": "20260924"}, {"baseline": "20261001"}))

    def test_none_values_treated_as_empty(self):
        self.assertFalse(core.baseline_mismatch({"baseline": None}, {"baseline": ""}))


class HealthIdentityCatalogTest(unittest.TestCase):
    """health_check 的离线身份与 catalog 种子检查项。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel, data=b"x"):
        """写文件(自动建父目录)。"""
        path = os.path.join(self.game, *rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def _write_abs(self, path, data=b"x"):
        """按绝对路径写文件(自动建父目录)。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def _item(self, items, name):
        """按名取检查项。"""
        return next(item for item in items if item.name == name)

    def test_missing_identity_and_seed_fail(self):
        items = core.health_check(self.game)
        self.assertFalse(self._item(items, "identity").ok)
        self.assertFalse(self._item(items, "catalog").ok)

    def test_patched_identity_and_seed_pass(self):
        self._write((core.DATA_DIR_NAME, core.APP_INFO_NAME),
                    "EXNOA LLC.\nドットアビスX_offline".encode("utf-8"))
        seed = core.catalog_seed_dir(self.game)
        self._write_abs(os.path.join(seed, core.CATALOG_BIN_NAME), b"BIN")
        self._write_abs(os.path.join(seed, core.CATALOG_HASH_NAME), b"hash-xyz")
        items = core.health_check(self.game)
        self.assertTrue(self._item(items, "identity").ok)
        self.assertTrue(self._item(items, "catalog").ok)

    def test_unpatched_identity_detail_mentions_repair(self):
        self._write((core.DATA_DIR_NAME, core.APP_INFO_NAME),
                    "EXNOA LLC.\nドットアビスX".encode("utf-8"))
        item = self._item(core.health_check(self.game), "identity")
        self.assertFalse(item.ok)
        self.assertIn("修复", item.detail)


class CollectDiagnosticsTest(unittest.TestCase):
    """collect_diagnostics / upload_diagnostics:打包关键文件、命中统计、上传未配则跳过。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = self.tmp.name
        bex = os.path.join(self.game, "BepInEx")
        cfg_dir = os.path.join(bex, "config")
        plugin = os.path.join(bex, "plugins", "StoryViewer")
        data = os.path.join(self.game, core.DATA_DIR_NAME)
        for d in (bex, cfg_dir, plugin, data):
            os.makedirs(d)
        with open(os.path.join(bex, "LogOutput.log"), "w", encoding="utf-8") as handle:
            handle.write("[资源自举] 完成:内容 catalog 已注册\n")
        with open(os.path.join(bex, "ErrorLog.log"), "w", encoding="utf-8") as handle:
            handle.write("\n")
        with open(os.path.join(bex, "offline-api.log"), "w", encoding="utf-8") as handle:
            handle.write("GET ... 本地缓存 bundle(累计命中 36 / 缺失 0)\n")
        with open(os.path.join(cfg_dir, "dotabyss.storyviewer.cfg"), "w", encoding="utf-8") as handle:
            handle.write("[Offline]\nOfflineAuth = true\nOfflineApi = true\n"
                         "RedirectAssetServer = true\nServeCachedBundles = true\n"
                         "SkipRequestEncryption = true\nForceDmmSdkSuccess = true\n"
                         "CaptureForward = false\nDiagAssets = false\n")
        with open(os.path.join(plugin, core.VERSION_NAME), "w", encoding="utf-8") as handle:
            json.dump({"version": "20261003", "baseline": "20260924",
                       "channel": "baseline", "plugin_version": "0.7.19"}, handle)
        with open(os.path.join(plugin, "StoryViewer.dll"), "wb") as handle:
            handle.write(b"MZfake")
        with open(os.path.join(data, core.APP_INFO_NAME), "w", encoding="utf-8") as handle:
            handle.write("EXNOA LLC.\nドットアビスX_offline\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_collect_zips_key_files_and_summary(self):
        with mock.patch.object(core, "game_running", lambda: False), \
             mock.patch.object(core, "plugin_file_version", lambda gd: "0.7.19"):
            zip_path, lines = core.collect_diagnostics(
                self.game, dest_dir=os.path.join(self.game, "out"))
        self.assertTrue(os.path.isfile(zip_path))
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
        for want in ("diag/diag_summary.txt", "diag/logs/LogOutput.log",
                     "diag/logs/offline-api.log", "diag/config/dotabyss.storyviewer.cfg",
                     "diag/offline_version.json"):
            self.assertIn(want, names)
        text = "\n".join(lines)
        self.assertIn("累计命中 36", text)
        self.assertIn("0.7.19", text)
        self.assertIn("baseline=20260924", text)

    def test_upload_skipped_without_target(self):
        os.environ.pop(core.DIAG_UPLOAD_URL_ENV, None)
        status, _detail = core.upload_diagnostics(self.game, "x.zip", url="", token="")
        self.assertEqual(status, "skipped")

    def test_upload_ok_with_mocked_urlopen(self):
        zip_path = os.path.join(self.game, "d.zip")
        with open(zip_path, "wb") as handle:
            handle.write(b"PKfake")
        fake_resp = mock.MagicMock()
        fake_resp.status = 200
        fake_resp.__enter__.return_value = fake_resp
        with mock.patch("urllib.request.urlopen", return_value=fake_resp) as urlopen:
            status, _detail = core.upload_diagnostics(
                self.game, zip_path, url="http://up", token="t")
        self.assertEqual(status, "ok")
        self.assertTrue(urlopen.called)


if __name__ == "__main__":
    unittest.main(verbosity=2)
