#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动器布局回归自测:默认尺寸与高级区均保持可见且可量测。

运行:``D:\\Python\\python.exe test_launcher_layout.py``(需要图形环境,不依赖 pytest)。
"""

import json
import os
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dotabyss_launcher as launcher  # noqa: E402


ADVANCED_NAMES = (
    "btn_check", "btn_probe", "btn_repair", "btn_logs", "btn_diag", "btn_offline",
)


def _make_game_dir(parent, notice):
    """创建带离线版本元数据的最小游戏目录,返回目录路径。"""
    game_dir = os.path.join(parent, "game")
    plugin_dir = os.path.join(game_dir, "BepInEx", "plugins", "StoryViewer")
    os.makedirs(plugin_dir, exist_ok=True)
    with open(os.path.join(plugin_dir, "offline_version.json"), "w", encoding="utf-8") as handle:
        json.dump({"version": "20261006", "plugin_version": "0.7.0",
                   "first_ready": True, "notice": notice}, handle)
    return game_dir


def _box(root, widget):
    """返回控件相对根窗口客户区的映射与几何量。"""
    return {
        "mapped": bool(widget.winfo_ismapped()),
        "x": widget.winfo_rootx() - root.winfo_rootx(),
        "y": widget.winfo_rooty() - root.winfo_rooty(),
        "width": widget.winfo_width(),
        "height": widget.winfo_height(),
    }


def _inside(root, box):
    """判断控件是否映射且完整落在根窗口客户区内。"""
    return (box["mapped"] and box["x"] >= 0 and box["y"] >= 0
            and box["x"] + box["width"] <= root.winfo_width()
            and box["y"] + box["height"] <= root.winfo_height())


def _format_box(box):
    """把控件测量值格式化为稳定的诊断文本。"""
    return ("mapped=%s x=%d y=%d width=%d height=%d"
            % (box["mapped"], box["x"], box["y"], box["width"], box["height"]))


def _run_case(notice):
    """运行一个公告/无公告布局场景并返回测量结果。"""
    temp = tempfile.TemporaryDirectory(prefix="dotabyss_layout_")
    root = None
    try:
        game_dir = _make_game_dir(temp.name, notice)
        root = tk.Tk()
        app = launcher.App(root, game_dir=game_dir)
        root.update_idletasks()

        # 读取 App 根据请求高度算出的默认值,再显式设置一次并刷新窗口。
        geometry = root.geometry().split("+", 1)[0]
        _default_width, default_height = (int(value) for value in geometry.split("x"))
        root.geometry("520x%d" % default_height)
        root.update()

        collapsed = {
            "btn_adv": _box(root, app.btn_adv),
            "log_frame": _box(root, app.log_frame),
            "notice_frame": _box(root, app._notice_frame),
        }

        app._toggle_advanced()
        root.update_idletasks()
        root.update()
        expanded = {
            "adv_frame": _box(root, app.adv_frame),
            "log_frame": _box(root, app.log_frame),
            "notice_frame": _box(root, app._notice_frame),
        }
        expanded.update({name: _box(root, getattr(app, name)) for name in ADVANCED_NAMES})

        print("场景:%s 默认几何=%dx%d 根窗口=%dx%d"
              % ("有公告" if notice else "无公告", _default_width, default_height,
                 root.winfo_width(), root.winfo_height()))
        for name, box in collapsed.items():
            print("  收起 %s: %s" % (name, _format_box(box)))
        for name, box in expanded.items():
            print("  展开 %s: %s" % (name, _format_box(box)))

        failures = []

        def check(label, condition, actual):
            """记录单条断言,失败时保留实际测量值。"""
            if condition:
                print("  PASS %s" % label)
            else:
                failures.append("%s;实际:%s" % (label, actual))
                print("  FAIL %s;实际:%s" % (label, actual))

        btn_adv = collapsed["btn_adv"]
        check("高级按钮默认可见且在窗口内", _inside(root, btn_adv), _format_box(btn_adv))

        expanded_names = ("adv_frame",) + ADVANCED_NAMES
        expanded_actual = "; ".join(
            "%s=(%s)" % (name, _format_box(expanded[name])) for name in expanded_names)
        check("高级区及六个高级按钮展开后全部可见且在窗口内",
              all(_inside(root, expanded[name]) for name in expanded_names), expanded_actual)

        log_box = expanded["log_frame"]
        check("展开后日志区可视高度大于 0", log_box["height"] > 0, _format_box(log_box))

        notice_box = collapsed["notice_frame"]
        if notice:
            reasonable = 0 < notice_box["height"] < root.winfo_height() / 2
            check("公告区高度合理且未吞掉全部空间", reasonable, _format_box(notice_box))
            # 展开高级区必须由日志区让出空间,不能把公告压扁(否则公告只剩半行)。
            expanded_notice = expanded["notice_frame"]
            check("展开高级区后公告高度不被压缩",
                  expanded_notice["height"] == notice_box["height"],
                  "%s vs 收起时 %s" % (_format_box(expanded_notice),
                                     _format_box(notice_box)))
        else:
            check("无公告时公告区不占空间", not notice_box["mapped"], _format_box(notice_box))
            check("无公告时展开高级区公告区仍不占空间",
                  not expanded["notice_frame"]["mapped"],
                  _format_box(expanded["notice_frame"]))

        if failures:
            raise AssertionError("布局场景失败:\n" + "\n".join(failures))
        return collapsed, expanded
    finally:
        if root is not None:
            root.destroy()
        temp.cleanup()


def main():
    """依次验证有公告与无公告场景,通过时返回 0。"""
    _run_case("维护完成,离线包已就绪。")
    _run_case("")
    print("PASS launcher layout")
    return 0


if __name__ == "__main__":
    sys.exit(main())
