#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ドットアビスX 离线启动器:首次本地修复、手动自检/修复/更新,再拉起游戏。

结构对标 TSKX 离线版(tools/tskx_launcher.py):直连失败自动回退系统代理、
后台线程 + 队列刷日志、启动器自替换(``.new`` + cmd)、``--smoke`` 冒烟。
更新通道:客户端本体(client_body.zip)、bundle 素材增量(caches_update.zip)、主数据缓存(master_data.zip)、
catalog 种子、剧情索引/封面、插件 DLL、玩家文档、启动器本体;基线不一致时
拒绝增量更新并要求重装完整包。自测口:``--release-dir``(目录当 HTTP)、
``--auto-update``(跑一次更新并落盘结果)。
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dotabyss_offline_core as c  # noqa: E402

# 配色取自游戏内 StoryViewer 面板(ViewerBehaviour.cs 的 Col* 常量),
# 保持启动器与该游戏原生 UI 同风格。
C_BG = "#141110"          # ColWindow
C_PANEL = "#1B1815"       # ColBand
C_LOG_BG = "#100E0C"      # ColPreviewBg
C_FG = "#ECE4D9"          # ColCream
C_DIM = "#9B9184"         # ColMuted
C_FAINT = "#6F665B"       # ColFaint
C_LINE = "#262220"        # ColLine
C_START = "#D99A4E"       # ColAmber
C_START_HOVER = "#F0C987"  # ColAmberLight
C_START_FG = "#231A0E"    # ColInk
C_BTN = "#211E1B"         # ColCard
C_BTN_HOVER = "#3A332C"   # ColCardHover
C_OK = "#F0C987"          # 亮琥珀=成功
C_WARN = "#D99A4E"        # 琥珀=警告
C_ERR = "#E06A4A"         # R18 红提亮=错误
FONT = ("Microsoft YaHei UI", 10)
FONT_TITLE = ("Microsoft YaHei UI", 15, "bold")
FONT_START = ("Microsoft YaHei UI", 14, "bold")
FONT_LOG = ("Consolas", 9)
GITHUB_UA = "dotabyss-offline-launcher"
ICO_NAME = "dotabyss_launcher.ico"


def resolve_icon_path(frozen, meipass, script_dir, exe_dir=None):
    """返回第一份存在的启动器 ico 路径。

    参数:frozen 是否冻包;meipass 为 PyInstaller 解包目录;script_dir 为 py 所在目录;
        exe_dir 为冻包 exe 目录。返回:路径字符串,都不存在则为 None。
    """
    names = []
    if frozen and meipass:
        names.append(os.path.join(meipass, ICO_NAME))
    names.append(os.path.join(script_dir, ICO_NAME))
    if exe_dir:
        names.append(os.path.join(exe_dir, ICO_NAME))
    for path in names:
        if path and os.path.isfile(path):
            return path
    return None


def resolve_game_dir():
    """解析游戏根目录(含主程序与 BepInEx 的目录)。

    冻包时:exe 所在目录及其上级;开发时额外回退到 ``<仓库>/client``
    (tools/launcher 的上上级)。
    返回:候选里第一个像游戏根的路径;都不像时返回 exe/脚本所在目录。
    """
    if getattr(sys, "frozen", False):
        here = os.path.dirname(os.path.abspath(sys.executable))
        candidates = [here, os.path.dirname(here)]
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            here,
            os.path.dirname(here),
            os.path.join(os.path.dirname(os.path.dirname(here)), "client"),
        ]
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, c.EXE_NAME)) or os.path.isdir(
                os.path.join(cand, "BepInEx")):
            return cand
    return here


# 直连失败时回退系统代理的提示回调(App 注入 self._emit,模块级供 HTTP 辅助函数使用)
_http_note = None


def set_http_note(fn):
    """登记 HTTP 回退提示回调;None 表示静默。"""
    global _http_note
    _http_note = fn


def _proxy_map():
    """读取系统代理(环境变量优先,注册表兜底),返回 ``{'http': url, 'https': url}`` 子集。

    只认 http/https(urllib 不支持 socks);某个 scheme 环境变量没有时用注册表值。
    """
    env = urllib.request.getproxies_environment()
    registry = urllib.request.getproxies_registry()
    proxies = {}
    for scheme in ("https", "http"):
        value = env.get(scheme) or registry.get(scheme)
        if value:
            proxies[scheme] = value
    return proxies


def _note(text, tag="warn"):
    """投递一条回退提示(无回调时静默,回调异常不影响下载)。"""
    if _http_note:
        try:
            _http_note(text, tag)
        except Exception:
            pass


def _http_request(opener, url, timeout):
    """用指定 opener 打开 URL(统一 UA),返回响应对象。"""
    request = urllib.request.Request(url, headers={"User-Agent": GITHUB_UA})
    return opener.open(request, timeout=timeout)


def _direct_opener():
    """直连 opener:显式禁用系统代理。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _proxy_opener(proxies):
    """系统代理 opener。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))


def _stream_to_file(response, dest, chunk):
    """把响应流式写入文件,返回写入字节数;失败时抛出。"""
    total = 0
    with response, open(dest, "wb") as out:
        while True:
            block = response.read(chunk)
            if not block:
                break
            out.write(block)
            total += len(block)
    return total


def _http_get(url, timeout=60):
    """GET 并返回响应体:先直连,失败自动回退系统代理。

    说明:有系统代理时直连用 20 秒短超时(socket 超时按每次读写计,慢速下载不受影响);
    服务器有响应(HTTPError,如 404)不触发回退;无系统代理时行为与旧版一致。
    """
    proxies = _proxy_map()
    direct_timeout = min(timeout, 20) if proxies else timeout
    try:
        with _http_request(_direct_opener(), url, direct_timeout) as response:
            return response.read()
    except urllib.error.HTTPError:
        raise
    except Exception as exc:
        if not proxies:
            raise
        _note("直连失败(%s),改用系统代理重试…" % exc)
        with _http_request(_proxy_opener(proxies), url, timeout) as response:
            return response.read()


def _http_download(url, dest, timeout=600, chunk=1 << 20):
    """流式下载到文件:先直连,失败自动回退系统代理,返回写入字节数。

    回退时以 ``wb`` 重新打开目标文件(截断重写),不会残留半截文件。
    """
    proxies = _proxy_map()
    direct_timeout = min(timeout, 20) if proxies else timeout
    try:
        response = _http_request(_direct_opener(), url, direct_timeout)
        return _stream_to_file(response, dest, chunk)
    except urllib.error.HTTPError:
        raise
    except Exception as exc:
        if not proxies:
            raise
        _note("直连失败(%s),改用系统代理重试…" % exc)
        response = _http_request(_proxy_opener(proxies), url, timeout)
        return _stream_to_file(response, dest, chunk)


def make_dir_fetchers(release_dir):
    """自测用:把 HTTP 取数映射到本地发布目录,返回 ``(get, download)`` 两个函数。

    ``api.github.com/...`` 映射到 ``release.json``,其余 URL 取末段文件名;
    目标文件不存在时抛 ``HTTPError(404)``,与真实网络行为一致。
    """
    def _resolve(url):
        name = url.rsplit("/", 1)[-1].split("?")[0] or "release.json"
        if "api.github.com" in url:
            name = "release.json"
        return os.path.join(release_dir, name)

    def get(url, timeout=60):  # noqa: ARG001 - 接口兼容
        path = _resolve(url)
        if not os.path.isfile(path):
            raise urllib.error.HTTPError(url, 404, "release dir missing", None, None)
        with open(path, "rb") as handle:
            return handle.read()

    def download(url, dest, timeout=600, chunk=1 << 20):  # noqa: ARG001 - 接口兼容
        path = _resolve(url)
        if not os.path.isfile(path):
            raise urllib.error.HTTPError(url, 404, "release dir missing", None, None)
        shutil.copy2(path, dest)
        return os.path.getsize(dest)

    return get, download


def _has_preview_files(directory):
    """判断封面目录是否至少有一个文件,用于兼容旧版本元数据缺失。"""
    if not os.path.isdir(directory):
        return False
    try:
        return any(os.path.isfile(os.path.join(directory, name))
                   for name in os.listdir(directory))
    except OSError:
        return False


def _has_player_docs(game_dir):
    """判断玩家文档白名单是否完整,用于兼容旧版本元数据缺失。"""
    return all(os.path.isfile(os.path.join(game_dir, name)) for name in c.PLAYER_DOC_NAMES)


_DETACHED = 0x00000008
_NEW_GROUP = 0x00000200


def _spawn_launcher_replace(game_dir):
    """分离启动 cmd:等本进程退出后 move exe 并拉起新启动器。

    说明:用 ``shell=True`` 把脚本整串交给 cmd;argv 列表形式会被 list2cmdline
    转义引号导致脚本静默失败(实测,见 core.build_launcher_replace_cmd 注释)。
    """
    script = c.build_launcher_replace_cmd(game_dir)
    subprocess.Popen(
        script,
        shell=True,
        cwd=game_dir,
        close_fds=True,
        creationflags=_DETACHED | _NEW_GROUP,
    )


def _tk_button(parent, text, command, bg, hover, fg=C_FG, font=FONT, padx=18, pady=8):
    """创建可改底色的 tk.Button,并绑 hover;禁用态不响应变色。"""
    btn = tk.Button(
        parent, text=text, command=command, bg=bg, fg=fg, font=font,
        activebackground=hover, activeforeground=fg, bd=0, relief="flat",
        padx=padx, pady=pady, cursor="hand2",
        disabledforeground=C_FAINT,
    )

    def _enter(_event, target=btn, color=hover):
        if str(target["state"]) == "disabled":
            return
        target.configure(bg=color)

    def _leave(_event, target=btn, color=bg):
        if str(target["state"]) == "disabled":
            return
        target.configure(bg=color)

    btn.bind("<Enter>", _enter)
    btn.bind("<Leave>", _leave)
    return btn


def _plugin_version_hint(game_dir):
    """读取插件 DLL 的版本号,读不到再退回配置头注释(旧值)。

    说明:配置头注释是 BepInEx 建文件时写下的旧值(升级插件不会刷新),
    所以优先读 DLL 本体的版本信息;都读不到返回空串。
    """
    value = c.plugin_file_version(game_dir)
    if value:
        return value
    path = c.config_path(game_dir)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(2000)
    except OSError:
        return ""
    marker = "created by plugin "
    index = head.find(marker)
    if index < 0:
        return ""
    line = head[index + len(marker):].splitlines()[0] if head[index + len(marker):] else ""
    parts = line.rsplit(" v", 1)
    return parts[1].strip() if len(parts) == 2 else ""


_PLUGIN_VERSION_DISPLAY_LIMIT = 24


def short_plugin_version(text):
    """把插件版本规范化为适合顶栏显示的短文本。

    参数:text 为完整插件版本,可包含 ``+`` 后的源代码修订号。
    返回:去掉 source revision、且不超过 24 个字符的显示版本;空输入返回空串。
    """
    if text is None:
        return ""
    value = str(text).split("+", 1)[0]
    if len(value) > _PLUGIN_VERSION_DISPLAY_LIMIT:
        return value[:_PLUGIN_VERSION_DISPLAY_LIMIT - 1] + "…"
    return value


class App:
    """离线启动器主窗口。"""

    def __init__(self, root, smoke_out=None, game_dir=None, auto_out=None):
        """构建窗口并按需启动首次修复。

        参数:root 为 Tk 根;smoke_out 为冒烟结果路径;game_dir 覆盖游戏根;
            auto_out 为自测结果路径(非空时不弹窗、自动跑一次更新后落盘)。
        """
        self.root = root
        self.smoke_out = smoke_out
        self.game_dir = game_dir or resolve_game_dir()
        version = c.load_version(self.game_dir)
        self._plugin_version_full = (str(version.get("plugin_version") or "")
                                     or _plugin_version_hint(self.game_dir))
        self.q = queue.Queue()
        set_http_note(self._emit)
        self.busy = False
        self._btns = []
        self._auto_out = auto_out
        self._auto_done = False
        self._auto_logs = []
        self._quiet_tried = False
        self._closing = False
        root.title("ドットアビスX 离线启动器")
        root.geometry("520x420")
        root.minsize(480, 360)
        root.configure(bg=C_BG)
        ico = resolve_icon_path(
            getattr(sys, "frozen", False),
            getattr(sys, "_MEIPASS", None),
            os.path.dirname(os.path.abspath(__file__)),
            os.path.dirname(os.path.abspath(sys.executable))
            if getattr(sys, "frozen", False) else None,
        )
        if ico:
            try:
                root.iconbitmap(ico)
            except tk.TclError:
                pass
        self._style()
        self._build()
        self._poll_queue()
        if smoke_out:
            root.after(3000, lambda: self._smoke_done(smoke_out))
        elif auto_out:
            pass  # 自测:由 main() 调度 _auto_update(内部会先做安全修复)
        else:
            if not version.get("first_ready"):
                self._run_bg(self._first_ready, keep_enabled=False)
            root.after(1200, self._start_quiet_check)

    def _style(self):
        """配置滚动条等 ttk 控件配色。"""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=C_BG, foreground=C_FG, font=FONT)
        style.configure("TFrame", background=C_BG)
        style.configure("Vertical.TScrollbar", background=C_BTN, troughcolor=C_PANEL,
                        arrowcolor=C_DIM, bordercolor=C_BG)

    def _version_text(self):
        """右侧版本标签文案:离线包日期与插件版本。"""
        data = c.load_version(self.game_dir)
        pack_ver = str(data.get("version") or "")
        plugin_ver = short_plugin_version(self._plugin_version_full)
        if pack_ver and plugin_ver:
            return "离线包 %s\n插件 v%s" % (pack_ver, plugin_ver)
        if pack_ver:
            return "离线包 %s" % pack_ver
        if plugin_ver:
            return "插件 v%s" % plugin_ver
        return "—"

    def _build(self):
        """构建顶栏、主按钮、日志、可折叠高级区。"""
        header = tk.Frame(self.root, bg=C_BG)
        header.pack(fill="x", padx=16, pady=(14, 8))
        titles = tk.Frame(header, bg=C_BG)
        titles.pack(side="left")
        tk.Label(titles, text="ドットアビスX 离线启动器", font=FONT_TITLE,
                 bg=C_BG, fg=C_FG).pack(anchor="w")
        tk.Label(titles, text="Dot Abyss X · Offline", font=FONT,
                 bg=C_BG, fg=C_DIM).pack(anchor="w")
        tk.Label(header, text=self._version_text(), font=FONT, bg=C_BG, fg=C_DIM,
                 justify="right").pack(side="right", anchor="n")

        cta = tk.Frame(self.root, bg=C_BG)
        cta.pack(fill="x", padx=16, pady=(4, 10))
        self.btn_start = _tk_button(
            cta, "开始游戏", self.start_game, C_START, C_START_HOVER,
            fg=C_START_FG, font=FONT_START, padx=28, pady=12)
        self.btn_start.pack(side="left")
        self.btn_update = _tk_button(
            cta, "更新", self.run_update, C_BTN, C_BTN_HOVER, padx=18, pady=12)
        self.btn_update.pack(side="left", padx=(10, 0))

        log_frame = tk.Frame(self.root, bg=C_PANEL)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.txt = tk.Text(
            log_frame, bg=C_LOG_BG, fg=C_FG, font=FONT_LOG, bd=0, relief="flat",
            wrap="word", state="disabled", height=10, insertbackground=C_FG,
            highlightthickness=0)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True, padx=8, pady=8)
        self.txt.tag_configure("ok", foreground=C_OK)
        self.txt.tag_configure("warn", foreground=C_WARN)
        self.txt.tag_configure("err", foreground=C_ERR)
        self.txt.tag_configure("dim", foreground=C_FG)

        self.btn_adv = _tk_button(
            self.root, "高级 ▾", self._toggle_advanced, C_BTN, C_BTN_HOVER,
            padx=12, pady=4)
        self.btn_adv.pack(anchor="w", padx=16, pady=(0, 4))
        self.adv_frame = tk.Frame(self.root, bg=C_BG)
        self.btn_check = _tk_button(
            self.adv_frame, "自检", self.run_check, C_BTN, C_BTN_HOVER)
        self.btn_probe = _tk_button(
            self.adv_frame, "索引探针", self.run_index_probe, C_BTN, C_BTN_HOVER)
        self.btn_repair = _tk_button(
            self.adv_frame, "修复", self.run_repair, C_BTN, C_BTN_HOVER)
        self.btn_logs = _tk_button(
            self.adv_frame, "打开日志", self.open_logs, C_BTN, C_BTN_HOVER)
        self.btn_check.pack(side="left")
        self.btn_probe.pack(side="left", padx=8)
        self.btn_repair.pack(side="left")
        self.btn_logs.pack(side="left", padx=8)
        self._advanced_open = False
        self._btns = [
            self.btn_start, self.btn_update, self.btn_check, self.btn_probe,
            self.btn_repair, self.btn_logs, self.btn_adv,
        ]
        self.log("游戏目录:%s" % self.game_dir, "dim")
        if self._plugin_version_full:
            self.log("插件完整版本: %s" % self._plugin_version_full, "dim")

    def _toggle_advanced(self):
        """展开或收起自检/探针/修复/打开日志。"""
        if self._advanced_open:
            self.adv_frame.pack_forget()
            self.btn_adv.configure(text="高级 ▾")
            self._advanced_open = False
        else:
            self.adv_frame.pack(fill="x", padx=16, pady=(0, 10))
            self.btn_adv.configure(text="高级 ▴")
            self._advanced_open = True

    def log(self, text, tag=None):
        """向日志框追加一行(仅主线程)。"""
        self.txt.configure(state="normal")
        self.txt.insert("end", text + "\n", tag or ())
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _poll_queue(self):
        """把后台日志与控件指令刷到界面(仅主线程)。"""
        count = 0
        while count < 200:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                break
            if item == "__DONE__":
                self._set_busy(False)
                count += 1
                continue
            if isinstance(item, tuple) and len(item) == 2 and item[0] == "__QUIT__":
                self._closing = True
                self.root.destroy()
                return
            if isinstance(item, tuple) and len(item) == 2 and item[0] == "__BTN__":
                self.btn_update.configure(text=item[1])
                count += 1
                continue
            if isinstance(item, tuple) and len(item) == 2:
                text, tag = item
            else:
                text, tag = str(item), None
            self.log(text, tag)
            count += 1
        self.root.after(100, self._poll_queue)

    def _emit(self, text, tag=None):
        """后台线程投递日志(自测模式同时留一份文本用于落盘)。"""
        if self._auto_out:
            self._auto_logs.append(str(text))
        self.q.put((text, tag))

    def _set_button_text(self, text):
        """请求修改更新按钮文案(经队列回主线程,后台线程可安全调用)。"""
        self.q.put(("__BTN__", text))

    def _set_busy(self, busy):
        """禁用或恢复全部动作按钮。"""
        self.busy = busy
        state = "disabled" if busy else "normal"
        for btn in self._btns:
            btn.configure(state=state)

    def _run_bg(self, fn, keep_enabled=False):
        """在后台线程执行 fn;busy 时拒绝重入。"""
        if self.busy:
            return
        if not keep_enabled:
            self._set_busy(True)

        def worker():
            try:
                fn()
            except Exception as exc:
                self._emit("失败:%s" % exc, "err")
            finally:
                if not keep_enabled:
                    self.q.put("__DONE__")

        threading.Thread(target=worker, daemon=True).start()

    def _log_checks(self, items):
        """输出 health_check 结果。"""
        for item in items:
            tag = "ok" if item.ok else "err"
            mark = "通过" if item.ok else "失败"
            self._emit("%s:%s — %s" % (item.name, mark, item.detail), tag)

    def _log_probes(self, items):
        """输出 index_probe 结果。"""
        for item in items:
            tag = "ok" if item.ok else "err"
            mark = "通过" if item.ok else "失败"
            self._emit("%s:%s — %s" % (item.name, mark, item.detail), tag)

    def _first_ready(self):
        """首次启动:本地安全修复(不联网) + 自检。"""
        self._emit("首次准备:正在安全修复(不联网)…", "dim")
        for line in c.safe_repair(self.game_dir):
            self._emit(line, "ok")
        items = c.health_check(self.game_dir)
        self._log_checks(items)
        if all(i.ok or i.name == "port" for i in items):
            self._emit("首次准备完成。", "ok")
        else:
            self._emit("首次准备结束,仍有未通过项,可点「修复」。", "warn")

    def _ensure_local_ready(self):
        """启动游戏前补齐本地条件(幂等、不联网):离线身份 + catalog/附属种子。"""
        identity = c.ensure_offline_identity(self.game_dir)
        if "已就绪" not in identity:
            self.log(identity, "warn")
        for line in c.seed_catalog_to_local_low(self.game_dir):
            if "已就绪" in line:
                continue
            self.log(line, "dim")
        for line in c.seed_local_low_extras(self.game_dir):
            self.log(line, "dim")

    def start_game(self):
        """拉起游戏;已在运行则只提示。"""
        if c.game_running():
            self.log("游戏已在运行", "warn")
            return
        exe = os.path.join(self.game_dir, c.EXE_NAME)
        if not os.path.isfile(exe):
            self.log("找不到 %s" % c.EXE_NAME, "err")
            return
        self._ensure_local_ready()
        cfg_ok, cfg_detail = c.offline_config_status(self.game_dir)
        if not cfg_ok:
            self.log("离线配置不完整(%s),已自动修复。" % cfg_detail, "warn")
            self.log(c.repair_config(self.game_dir), "ok")
        try:
            subprocess.Popen([exe], cwd=self.game_dir)
            self.log("已启动游戏。", "ok")
        except Exception as exc:
            self.log("启动失败:%s" % exc, "err")

    def run_check(self):
        """只读自检。"""
        def work():
            self._emit("开始自检…", "dim")
            self._log_checks(c.health_check(self.game_dir))
            self._emit("自检结束。", "dim")
        self._run_bg(work)

    def run_index_probe(self):
        """手动跑索引探针,不调用 health_check。"""
        def work():
            self._emit("开始索引探针…", "dim")
            items = c.index_probe(self.game_dir)
            self._log_probes(items)
            if items and all(i.ok for i in items):
                self._emit("索引探针通过。", "ok")
            else:
                self._emit("索引探针失败。", "err")
        self._run_bg(work)

    def run_repair(self):
        """手动安全修复。"""
        def work():
            self._emit("开始修复…", "dim")
            for line in c.safe_repair(self.game_dir):
                self._emit(line, "ok")
            self._log_checks(c.health_check(self.game_dir))
            self._emit("修复结束。", "dim")
        self._run_bg(work)

    def open_logs(self):
        """用资源管理器打开日志目录(失败时只提示)。"""
        target = c.logs_dir(self.game_dir)
        if not os.path.isdir(target):
            self.log("日志目录不存在:%s" % target, "err")
            return
        try:
            os.startfile(target)  # noqa: S606 - 固定打开本地目录
            self.log("已打开日志目录。", "dim")
        except OSError as exc:
            self.log("打开失败:%s" % exc, "err")

    def run_update(self):
        """用户点击后才访问 GitHub;失败不挡住开始游戏。"""
        self._run_bg(self._do_update)

    def _fetch_remote(self):
        """取 latest Release 与 version.json;未配置仓库或缺少文件时抛异常。"""
        repo = c.read_github_repo(self.game_dir)
        if not repo:
            raise RuntimeError("未配置仓库(launcher.json 的 github_repo 为空)")
        payload = json.loads(_http_get(
            "https://api.github.com/repos/%s/releases/latest" % repo))
        parsed = c.parse_latest_release(payload)
        if not parsed.get("version_json_url"):
            raise RuntimeError("Release 没有 version.json")
        remote = json.loads(_http_get(parsed["version_json_url"]))
        return parsed, remote

    def _start_quiet_check(self):
        """启动后静默查一次更新(只改按钮文案,失败不打扰玩家)。"""
        if self.smoke_out or self._auto_out or self._quiet_tried:
            return
        self._quiet_tried = True
        threading.Thread(target=self._check_update_quiet, daemon=True).start()

    def _check_update_quiet(self):
        """静默检查版本与轻量产物状态:有待修复项 → 按钮「有更新」。"""
        try:
            _parsed, remote = self._fetch_remote()
        except Exception:
            return
        local = c.load_version(self.game_dir)
        if c.baseline_mismatch(local, remote):
            self._emit("远端基线与本机不一致:需重新下载完整包。", "warn")
            self._set_button_text("需重装")
            return
        if str(remote.get("version") or "") != str(local.get("version") or ""):
            self._emit("发现新版本 %s(本机 %s),可点「更新」。"
                       % (remote.get("version") or "?", local.get("version") or "?"), "warn")
            self._set_button_text("有更新")
            return
        if not self._quiet_outputs_current(remote, local):
            self._emit("本地产物未完全就绪,点「更新」补齐。", "warn")
            self._set_button_text("有更新")

    def _temp_zip(self, name):
        """更新下载的临时 zip 路径(插件目录下,失败时可留档排查)。"""
        return os.path.join(c.plugin_dir(self.game_dir),
                            "update_%s_%s.zip" % (name, time.strftime("%Y%m%d_%H%M%S")))

    def _apply_catalog(self, release, remote):
        """更新 catalog 种子并播种到 LocalLow;哈希一致时跳过。返回说明或空串。"""
        remote_hash = str(remote.get("catalog_hash") or "")
        if not remote_hash:
            return ""
        if c.catalog_seed_hash(self.game_dir) == remote_hash:
            return ""
        bin_url = release.get("catalog_bin_url")
        hash_url = release.get("catalog_hash_url")
        if not (bin_url and hash_url):
            raise RuntimeError("Release 缺少 catalog 附件(catalog_1.bin / .hash)")
        raw_bin = _http_get(bin_url, timeout=600)
        raw_hash = _http_get(hash_url, timeout=60)
        expected_bin = str(remote.get("catalog_bin_md5") or "")
        if expected_bin and hashlib.md5(raw_bin).hexdigest() != expected_bin.lower():
            raise RuntimeError("catalog bin 摘要不符")
        expected_hash = str(remote.get("catalog_hash_md5") or "")
        if expected_hash and hashlib.md5(raw_hash).hexdigest() != expected_hash.lower():
            raise RuntimeError("catalog 哈希文件摘要不符")
        got_hash = raw_hash.decode("utf-8", "replace").strip()
        if got_hash != remote_hash:
            raise RuntimeError("catalog 哈希内容不符(%s ≠ %s)" % (got_hash, remote_hash))
        stamp = time.strftime("%Y%m%d_%H%M%S")
        message = c.install_catalog_from_bytes(self.game_dir, raw_bin, raw_hash, stamp)
        lines = c.seed_catalog_to_local_low(self.game_dir)
        return message + ";" + "、".join(lines)

    def _apply_client_body(self, release, remote, stamp):
        """按清单更新客户端本体(插件/缓存/身份/启动器除外)。返回说明或空串。"""
        body = remote.get("client_body") or {}
        files = body.get("files") or {}
        if not files:
            return ""
        todo = c.client_body_todo(self.game_dir, files)
        if not todo:
            return ""
        url = release.get("client_body_zip_url")
        if not url:
            raise RuntimeError("Release 缺少 client_body.zip")
        self._emit("客户端本体需更新 %d/%d 个文件,开始下载…" % (len(todo), len(files)), "dim")
        zip_path = self._temp_zip("client_body")
        try:
            got = _http_download(url, zip_path, timeout=3600)
            expected = str(body.get("zip_md5") or "")
            if expected and c.file_md5(zip_path) != expected.lower():
                raise RuntimeError("client_body.zip 摘要不符(下载 %d 字节)" % got)
            mapping = {rel: files[rel] for rel in todo}
            logs = c.install_zip_members(zip_path, self.game_dir, mapping, stamp,
                                         checker=c.client_body_rel_allowed, backup=False)
        finally:
            try:
                os.remove(zip_path)
            except OSError:
                pass
        return "已更新客户端本体 %d 个文件" % len(logs)

    def _apply_caches_added(self, release, remote, stamp):
        """按清单补充 bundle 缓存(新角色/新剧情素材)。返回说明或空串。"""
        data = remote.get("caches_added") or {}
        files = data.get("files") or {}
        if not files:
            return ""
        todo = c.caches_added_todo(self.game_dir, files)
        if not todo:
            return ""
        url = release.get("caches_zip_url")
        if not url:
            raise RuntimeError("Release 缺少 caches_update.zip")
        self._emit("素材缓存需补充 %d/%d 个 bundle,开始下载…" % (len(todo), len(files)), "dim")
        zip_path = self._temp_zip("caches")
        try:
            got = _http_download(url, zip_path, timeout=3600)
            expected = str(data.get("zip_md5") or "")
            if expected and c.file_md5(zip_path) != expected.lower():
                raise RuntimeError("caches_update.zip 摘要不符(下载 %d 字节)" % got)
            mapping = {rel: files[rel] for rel in todo}
            logs = c.install_zip_members(zip_path, self.game_dir, mapping, stamp,
                                         checker=c.caches_rel_allowed, backup=False)
        finally:
            try:
                os.remove(zip_path)
            except OSError:
                pass
        return "已补充 %d 个 bundle 素材" % len(logs)

    def _apply_master_data(self, release, remote, stamp):
        """下载主数据附件、写入包内种子并播种 LocalLow。

        新版 Release 声明主数据清单时附件是强制项;旧 Release 没有该字段则兼容跳过。
        主数据允许替换同路径旧缓存,其它 LocalLow 文件仍只补缺失。
        """
        files = remote.get("master_data_files") or {}
        declared = bool(files or remote.get("master_data_md5") or remote.get("master_data_url"))
        if not declared:
            return ""
        url = release.get("master_data_url")
        if not url:
            raise RuntimeError("Release 缺少主数据附件 master_data.zip")
        if not isinstance(files, dict) or not files:
            raise RuntimeError("version.json 缺少主数据文件清单")
        if any(not c.master_data_rel_allowed(rel) for rel in files):
            raise RuntimeError("主数据文件清单含非法路径")
        if not remote.get("master_data_md5"):
            raise RuntimeError("version.json 缺少 master_data.zip 摘要")
        if any(not isinstance(digest, str) or len(digest) != 32
               or any(ch not in "0123456789abcdefABCDEF" for ch in digest)
               for digest in files.values()):
            raise RuntimeError("主数据文件清单含非法 MD5")

        seed_root = c.local_low_seed_dir(self.game_dir)
        stored_zip_md5 = str(c.load_version(self.game_dir).get("master_data_md5") or "")
        seed_ready = all(
            os.path.isfile(os.path.join(seed_root, *rel.replace("\\", "/").split("/")))
            and not c.file_needs_update(
                os.path.join(seed_root, *rel.replace("\\", "/").split("/")), expected)
            for rel, expected in files.items()) and stored_zip_md5 == str(
                remote.get("master_data_md5") or "").lower()
        if not seed_ready:
            self._emit("主数据缓存需更新 %d 个文件,开始下载…" % len(files), "dim")
            zip_path = self._temp_zip("master_data")
            try:
                got = _http_download(url, zip_path, timeout=600)
                expected_zip = str(remote.get("master_data_md5") or "")
                if expected_zip and c.file_md5(zip_path) != expected_zip.lower():
                    raise RuntimeError("master_data.zip 摘要不符(下载 %d 字节)" % got)
                c.install_zip_members(zip_path, seed_root, files, stamp,
                                      checker=c.master_data_rel_allowed, backup=False)
            finally:
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
        lines = c.seed_local_low_extras(self.game_dir)
        if any("失败" in line for line in lines):
            raise RuntimeError("主数据播种失败:" + "、".join(lines))
        return "已更新并播种主数据缓存(%d 个文件)" % len(files)

    def _write_auto_result(self, status):
        """自测模式:把状态与最近日志写到 --auto-update 指定文件。"""
        if not self._auto_out:
            return
        self._auto_done = True
        try:
            with open(self._auto_out, "w", encoding="utf-8") as handle:
                handle.write("%s\n" % status)
                handle.write("\n".join(self._auto_logs[-80:]))
        except OSError:
            pass

    def _close_window(self):
        """请求关闭主窗口(经队列回主线程,后台线程可安全调用)。"""
        if self._closing:
            return
        self._closing = True
        self.q.put(("__QUIT__", None))

    def _auto_update(self):
        """自测:跑一次更新并落盘结果(OK / OK-UPTODATE / BLOCKED-BASELINE / FAIL)。"""
        before = str(c.load_version(self.game_dir).get("version") or "")
        self._do_update()
        if not self._auto_done:
            after = str(c.load_version(self.game_dir).get("version") or "")
            text = "\n".join(self._auto_logs)
            if after and after != before:
                self._write_auto_result("OK version=%s" % after)
            elif "已是最新" in text:
                self._write_auto_result("OK-UPTODATE")
            elif "基线" in text and "不一致" in text:
                self._write_auto_result("BLOCKED-BASELINE")
            else:
                self._write_auto_result("FAIL")
        self._close_window()

    def _apply_docs(self, release, remote, stamp, local=None, same_version=False):
        """从 Release 更新玩家文档包(白名单落地到游戏根)。

        参数:release 为 parse_latest_release 产物;remote 为 version.json;
            stamp 为备份后缀。返回:中文说明或空串。
        """
        url = release.get("player_docs_url")
        expected = str(remote.get("player_docs_zip_md5") or "")
        stored = str((local or {}).get("player_docs_zip_md5") or "")
        if expected and stored.lower() == expected.lower():
            return ""
        if expected and same_version and not stored and _has_player_docs(self.game_dir):
            return ""
        if not url:
            if expected:
                raise RuntimeError("Release 缺少 player_docs.zip")
            return ""
        raw = _http_get(url, timeout=300)
        if expected and hashlib.md5(raw).hexdigest() != expected.lower():
            raise RuntimeError("文档包摘要不符")
        count = c.extract_zip_bytes(raw, self.game_dir, allowed_names=c.PLAYER_DOC_NAMES)
        return "已更新玩家文档(%d 个文件)" % count

    def _apply_previews(self, release, remote, local=None, same_version=False):
        """从 Release 更新封面包(previews.zip 覆盖到预览目录)。"""
        url = release.get("previews_zip_url")
        expected = str(remote.get("previews_zip_md5") or "")
        stored = str((local or {}).get("previews_zip_md5") or "")
        if expected and stored.lower() == expected.lower():
            return ""
        if expected and same_version and not stored and _has_preview_files(c.previews_dir(self.game_dir)):
            return ""
        if not url:
            if expected:
                raise RuntimeError("Release 缺少 previews.zip")
            return ""
        raw = _http_get(url, timeout=300)
        if expected and hashlib.md5(raw).hexdigest() != expected.lower():
            raise RuntimeError("封面包摘要不符")
        count = c.extract_zip_bytes(raw, c.previews_dir(self.game_dir))
        return "已更新 %d 张封面" % count

    def _release_outputs_current(self, remote, local):
        """核对 Release 已声明的本地产物,避免同版本过早返回。

        返回:所有可核对的声明均匹配时为 True;旧 Release 未声明的字段不参与判断。
        主数据同时要求本地版本记录 ZIP 摘要、种子文件存在且逐文件 MD5 一致,
        这样旧启动器刚完成自替换后仍会进入一次修复流程。
        """
        for rel, expected in (
                (("BepInEx", "plugins", "StoryViewer", "StoryViewer.dll"),
                 remote.get("plugin_md5")),
                (("BepInEx", "plugins", "StoryViewer", "stories.json"),
                 remote.get("stories_md5"))):
            if expected and c.file_needs_update(os.path.join(self.game_dir, *rel), expected):
                return False

        previews_md5 = str(remote.get("previews_zip_md5") or "")
        if previews_md5:
            stored_previews = str(local.get("previews_zip_md5") or "")
            if stored_previews:
                if stored_previews.lower() != previews_md5.lower():
                    return False
            elif not _has_preview_files(c.previews_dir(self.game_dir)):
                return False
        docs_md5 = str(remote.get("player_docs_zip_md5") or "")
        if docs_md5:
            stored_docs = str(local.get("player_docs_zip_md5") or "")
            if stored_docs:
                if stored_docs.lower() != docs_md5.lower():
                    return False
            elif not _has_player_docs(self.game_dir):
                return False

        body = remote.get("client_body")
        if body is not None:
            if not isinstance(body, dict):
                return False
            try:
                if c.client_body_todo(self.game_dir, body.get("files") or {}):
                    return False
            except (TypeError, ValueError, OSError):
                return False

        caches = remote.get("caches_added")
        if caches is not None:
            if not isinstance(caches, dict):
                return False
            try:
                if c.caches_added_todo(self.game_dir, caches.get("files") or {}):
                    return False
            except (TypeError, ValueError, OSError):
                return False

        catalog_hash = str(remote.get("catalog_hash") or "")
        if catalog_hash and c.catalog_seed_hash(self.game_dir) != catalog_hash:
            return False
        catalog_bin_md5 = str(remote.get("catalog_bin_md5") or "")
        if catalog_bin_md5:
            catalog_bin = os.path.join(c.catalog_seed_dir(self.game_dir), c.CATALOG_BIN_NAME)
            if c.file_needs_update(catalog_bin, catalog_bin_md5):
                return False

        master_declared = any(key in remote for key in
                              ("master_data_url", "master_data_md5", "master_data_files"))
        if master_declared:
            files = remote.get("master_data_files")
            expected_zip = str(remote.get("master_data_md5") or "")
            if (not isinstance(files, dict) or not files or len(expected_zip) != 32
                    or not all(ch in "0123456789abcdefABCDEF" for ch in expected_zip)):
                return False
            if str(local.get("master_data_md5") or "").lower() != expected_zip.lower():
                return False
            seed_root = c.local_low_seed_dir(self.game_dir)
            for rel, expected in files.items():
                if (not isinstance(expected, str) or len(expected) != 32
                        or any(ch not in "0123456789abcdefABCDEF" for ch in expected)
                        or not c.master_data_rel_allowed(rel)):
                    return False
                seed_file = os.path.join(seed_root, *rel.replace("\\", "/").split("/"))
                if c.file_needs_update(seed_file, expected):
                    return False

        launcher_md5 = str(remote.get("launcher_md5") or "")
        if launcher_md5:
            if getattr(sys, "frozen", False):
                if c.file_needs_update(c.launcher_path(self.game_dir), launcher_md5):
                    return False
            elif str(local.get("launcher_md5") or "").lower() != launcher_md5.lower():
                return False
        return True

    def _quiet_outputs_current(self, remote, local):
        """用轻量规则判断静默检查是否可以保持现状。

        这里不能调用 ``_release_outputs_current``:后者会扫描客户端本体和
        Caches 的全部文件。静默检查只比较 ``offline_version.json`` 已记录的
        产物摘要,并逐个校验主数据种子(通常只有一个约 11 MB 的 ``.dat``)。
        远端未声明的字段按旧 Release 兼容规则跳过。
        返回:所有已声明记录和主数据种子均匹配时为 True。
        """
        record_fields = (
            "plugin_md5", "stories_md5", "previews_zip_md5",
            "player_docs_zip_md5", "catalog_hash", "catalog_bin_md5",
            "launcher_md5",
        )
        for field in record_fields:
            expected = remote.get(field)
            if expected and str(local.get(field) or "").lower() != str(expected).lower():
                return False

        for remote_field, local_fields in (
                ("client_body", ("client_body_zip_md5", "client_body_md5")),
                ("caches_added", ("caches_added_zip_md5", "caches_added_md5"))):
            if remote_field not in remote or remote.get(remote_field) is None:
                continue
            manifest = remote.get(remote_field)
            if not isinstance(manifest, dict):
                return False
            expected = manifest.get("zip_md5")
            if expected:
                stored = next((local.get(field) for field in local_fields
                               if local.get(field)), "")
                if str(stored).lower() != str(expected).lower():
                    return False

        master_declared = any(key in remote for key in
                              ("master_data_url", "master_data_md5", "master_data_files"))
        if not master_declared:
            return True
        files = remote.get("master_data_files")
        expected_zip = str(remote.get("master_data_md5") or "")
        if (not isinstance(files, dict) or not files or len(expected_zip) != 32
                or any(ch not in "0123456789abcdefABCDEF" for ch in expected_zip)
                or str(local.get("master_data_md5") or "").lower() != expected_zip.lower()):
            return False
        seed_root = c.local_low_seed_dir(self.game_dir)
        for rel, expected in files.items():
            if (not isinstance(rel, str) or not isinstance(expected, str)
                    or len(expected) != 32
                    or any(ch not in "0123456789abcdefABCDEF" for ch in expected)
                    or not c.master_data_rel_allowed(rel)):
                return False
            seed_file = os.path.join(seed_root, *rel.replace("\\", "/").split("/"))
            try:
                if c.file_needs_update(seed_file, expected):
                    return False
            except OSError:
                return False
        return True

    def _backfill_remote_records(self, local, remote):
        """在同版本早退前补写远端产物摘要,避免旧元数据反复触发静默提示。

        调用前已经通过 ``_release_outputs_current`` 的实际文件校验,这里只记录
        已确认的摘要,不下载或重新扫描大体积附件。返回是否写入了新记录。
        """
        updated = dict(local)
        for field in (
                "plugin_md5", "stories_md5", "previews_zip_md5",
                "player_docs_zip_md5", "launcher_md5", "catalog_hash",
                "catalog_bin_md5", "master_data_md5"):
            if field in remote:
                updated[field] = remote[field]
        for remote_field, local_field in (
                ("client_body", "client_body_zip_md5"),
                ("caches_added", "caches_added_zip_md5")):
            manifest = remote.get(remote_field)
            if isinstance(manifest, dict) and "zip_md5" in manifest:
                updated[local_field] = manifest["zip_md5"]
        if updated == local:
            return False
        c.save_version(self.game_dir, updated)
        return True

    def _do_update(self):
        """执行一次 latest 累积更新;任一步异常只打红字。

        顺序:修复/身份 → 客户端本体 → bundle 素材 → catalog → 索引 → 封面 →
        插件 DLL → 玩家文档 → 启动器。基线不一致直接拒绝(必须重装完整包)。
        """
        repo = c.read_github_repo(self.game_dir)
        if not repo:
            self._emit("未配置仓库(launcher.json 的 github_repo 为空)", "warn")
            return
        if c.game_running():
            self._emit("游戏运行中,拒绝更新。", "err")
            return
        try:
            parsed, remote = self._fetch_remote()
            local = c.load_version(self.game_dir)
            # 基线优先于版本号裁决:基线不一致 = 必须整包重装,即使版本号恰好相同
            if c.baseline_mismatch(local, remote):
                self._emit("基线不一致(本机 %s → 远端 %s):请重新下载完整包,不能增量更新。"
                           % (local.get("baseline") or "无", remote.get("baseline") or "无"), "err")
                self._set_button_text("需重装")
                return
            same_version = str(remote.get("version") or "") == str(local.get("version") or "")
            if same_version and self._release_outputs_current(remote, local):
                self._backfill_remote_records(local, remote)
                self._emit("已是最新。", "ok")
                return
            if same_version:
                self._emit("版本号相同但本地产物未完全就绪,继续校验修复。", "warn")
            stamp = time.strftime("%Y%m%d_%H%M%S")
            for line in c.safe_repair(self.game_dir):
                self._emit(line, "ok")

            # 本体 → 素材 → 主数据 → catalog → 索引 → 封面 → 插件 DLL → 文档 → 启动器
            # (本体先行:它决定其余文件的格式;先数据后代码,任一失败旧版仍可玩)
            for message in (
                self._apply_client_body(parsed, remote, stamp),
                self._apply_caches_added(parsed, remote, stamp),
                self._apply_master_data(parsed, remote, stamp),
                self._apply_catalog(parsed, remote),
            ):
                if message:
                    self._emit(message, "ok")

            stories_dest = c.stories_path(self.game_dir)
            stories_md5 = remote.get("stories_md5")
            if parsed.get("stories_url") and c.file_needs_update(stories_dest, stories_md5):
                raw = _http_get(parsed["stories_url"], timeout=300)
                self._emit(c.install_bytes(stories_dest, raw, stories_md5, stamp), "ok")

            previews_msg = self._apply_previews(parsed, remote, local, same_version)
            if previews_msg:
                self._emit(previews_msg, "ok")

            dll_dest = os.path.join(c.plugin_dir(self.game_dir), "StoryViewer.dll")
            dll_md5 = remote.get("plugin_md5")
            if parsed.get("plugin_dll_url") and c.file_needs_update(dll_dest, dll_md5):
                raw = _http_get(parsed["plugin_dll_url"], timeout=300)
                self._emit(c.install_bytes(dll_dest, raw, dll_md5, stamp), "ok")

            docs_msg = self._apply_docs(parsed, remote, stamp, local, same_version)
            if docs_msg:
                self._emit(docs_msg, "ok")

            launcher_dest = c.launcher_path(self.game_dir)
            launcher_md5 = remote.get("launcher_md5")
            restart = False
            if (parsed.get("launcher_exe_url")
                    and c.file_needs_update(launcher_dest, launcher_md5)):
                if getattr(sys, "frozen", False):
                    raw = _http_get(parsed["launcher_exe_url"], timeout=300)
                    self._emit(c.install_bytes(launcher_dest, raw, launcher_md5, stamp,
                                               replace=False), "ok")
                    restart = True
                else:
                    self._emit("开发模式跳过启动器替换", "warn")

            new_version = dict(local)
            new_version.update({
                "version": remote.get("version", local.get("version")),
                "baseline": remote.get("baseline", local.get("baseline")),
                "channel": remote.get("channel", local.get("channel")),
                "plugin_version": remote.get("plugin_version", local.get("plugin_version")),
                "plugin_md5": remote.get("plugin_md5", local.get("plugin_md5")),
                "stories_md5": remote.get("stories_md5", local.get("stories_md5")),
                "previews_zip_md5": remote.get("previews_zip_md5", local.get("previews_zip_md5")),
                "player_docs_zip_md5": remote.get("player_docs_zip_md5",
                                                    local.get("player_docs_zip_md5")),
                "launcher_md5": remote.get("launcher_md5", local.get("launcher_md5")),
                "catalog_hash": remote.get("catalog_hash", local.get("catalog_hash")),
                "catalog_bin_md5": remote.get("catalog_bin_md5", local.get("catalog_bin_md5")),
                "master_data_md5": remote.get("master_data_md5", local.get("master_data_md5")),
                "client_body_zip_md5": (
                    (remote.get("client_body") or {}).get("zip_md5", local.get("client_body_zip_md5"))
                    if isinstance(remote.get("client_body"), dict)
                    else local.get("client_body_zip_md5")),
                "caches_added_zip_md5": (
                    (remote.get("caches_added") or {}).get("zip_md5",
                                                            local.get("caches_added_zip_md5"))
                    if isinstance(remote.get("caches_added"), dict)
                    else local.get("caches_added_zip_md5")),
                "first_ready": True,
            })
            c.save_version(self.game_dir, new_version)
            self._emit("更新完成。", "ok")
            if restart:
                self._emit("正在重启启动器…", "ok")
                self._write_auto_result("OK-RESTART")
                _spawn_launcher_replace(self.game_dir)
                self._close_window()
                return
            self._write_auto_result("OK version=%s" % new_version.get("version"))
            self._set_button_text("已是最新")
        except Exception as exc:
            self._emit("更新失败:%s" % exc, "err")
            if self._auto_out:
                self._write_auto_result("FAIL")

    def _smoke_done(self, out_path):
        """冒烟:窗口已起来则写 PASS 并退出,不启动游戏。"""
        try:
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write("PASS game_dir=%s\n" % self.game_dir)
        except Exception as exc:
            try:
                with open(out_path, "w", encoding="utf-8") as handle:
                    handle.write("FAIL %s\n" % exc)
            except Exception:
                pass
        self.root.destroy()


def main(argv=None):
    """入口:``--smoke <out.txt>``、``--game-dir <dir>``、``--release-dir <dir>``、``--auto-update <out.txt>``。

    说明:``--release-dir`` 把网络取数映射到本地发布目录(自测);
    ``--auto-update`` 自动跑一次更新并把结果写文件(自测),常与前者搭配。
    """
    global _http_get, _http_download
    argv = list(sys.argv[1:] if argv is None else argv)

    def _arg(name):
        if name in argv:
            return argv[argv.index(name) + 1]
        return None

    smoke_out = _arg("--smoke")
    game_dir = _arg("--game-dir")
    release_dir = _arg("--release-dir")
    auto_out = _arg("--auto-update")
    if release_dir:
        _http_get, _http_download = make_dir_fetchers(release_dir)
    game_dir = game_dir or resolve_game_dir()
    if (not smoke_out) and getattr(sys, "frozen", False) and c.pending_launcher_swap(game_dir):
        _spawn_launcher_replace(game_dir)
        return 0
    root = tk.Tk()
    app = App(root, smoke_out=smoke_out, game_dir=game_dir, auto_out=auto_out)
    if auto_out:
        root.after(600, lambda: app._run_bg(app._auto_update))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
