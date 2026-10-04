#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立诊断打包器(纯 Python,不碰游戏运行时)。

用途:当你手上只有一堆**原始日志**(玩家发来的 ``LogOutput.log``、``offline-api.log``
等,或从别处拷贝的),用它能直接生成一个自包含的回传 zip,并可选上传到已配置的
接收端(Cloudflare Worker / 任何 multipart 端点),契约与启动器
``dotabyss_offline_core.upload_diagnostics`` 完全一致。

超大日志同样保留**开头 + 结尾**(复用 core 的 ``_cap_bytes_head_tail``),并把已知
崩溃签名关键字抽进摘要(复用 core 的 ``DIAG_SIGNATURE_PATTERNS``),确保开机段黑屏
证据不被截断。

示例:
    python build_log_diag_zip.py D:\\player\\LogOutput.log D:\\player\\offline-api.log
    python build_log_diag_zip.py LogOutput.log --out out\\ --upload --game-dir ..\\..\\client
"""
import os
import sys
import time
import zipfile
import platform
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))            # tools/launcher
sys.path.insert(0, HERE)
import dotabyss_offline_core as c  # noqa: E402


def _signature_lines(path: str) -> list:
    """从单个日志文件抽取已知崩溃签名行(有界扫描,复用 core 模式表)。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            raw = handle.read(min(size, c.DIAG_SIGNATURE_SCAN_BYTES))
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    out, seen = [], set()
    for line in text.splitlines():
        low = line.lower()
        if any(pat.lower() in low for pat in c.DIAG_SIGNATURE_PATTERNS):
            s = line.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s[:300])
            if len(out) >= 120:
                break
    return out


def build(log_paths, out_dir=None, title="ドットアビスX 日志回传包"):
    """把若干日志打成 zip,返回 ``(zip 路径, 摘要行列表)``。"""
    out_dir = out_dir or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    zip_path = os.path.join(out_dir, "dotabyss-logdiag-%s.zip" % stamp)

    lines = ["=== %s ===" % title,
             "生成时间:%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
             "系统:%s %s / Python %s" % (platform.system(), platform.release(),
                                        platform.python_version()),
             "收录日志:"]
    for p in log_paths:
        try:
            lines.append("  - %s (%d 字节)" % (os.path.basename(p), os.path.getsize(p)))
        except OSError:
            lines.append("  - %s (读不到)" % os.path.basename(p))

    # 汇总各日志的崩溃签名,放摘要里一眼可见。
    all_sig = []
    for p in log_paths:
        for s in _signature_lines(p):
            if s not in all_sig:
                all_sig.append(s)
    lines.append("")
    lines.append("--- 崩溃签名抽取(关键字命中,跨全部日志去重) ---")
    if all_sig:
        lines.extend(all_sig)
    else:
        lines.append("(未匹配到已知崩溃签名关键字)")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("diag/diag_summary.txt", ("\n".join(lines) + "\n").encode("utf-8"))
        for p in log_paths:
            if os.path.isfile(p):
                zf.writestr("diag/logs/" + os.path.basename(p),
                            c._cap_bytes_head_tail(p))
    return zip_path, lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="把原始日志打成回传 zip(可选上传)。")
    ap.add_argument("logs", nargs="+", help="一个或多个日志文件路径")
    ap.add_argument("--out", default=None, help="输出目录(默认当前目录)")
    ap.add_argument("--upload", action="store_true", help="打包后尝试上传到已配置端点")
    ap.add_argument("--game-dir", default="", help="用于读取 launcher.json 上传配置的游戏根(可空)")
    args = ap.parse_args(argv)

    missing = [p for p in args.logs if not os.path.isfile(p)]
    if missing:
        for m in missing:
            print("找不到日志文件:%s" % m, file=sys.stderr)
        return 2

    zip_path, lines = build(args.logs, out_dir=args.out)
    print("已生成诊断包:%s (%d 字节)" % (zip_path, os.path.getsize(zip_path)))
    print("摘要预览(前 12 行):")
    for line in lines[:12]:
        print("  " + line)

    if args.upload:
        status, detail = c.upload_diagnostics(args.game_dir, zip_path)
        print("上传%s:%s" % ({"ok": "成功", "skipped": "跳过",
                             "error": "失败"}.get(status, status), detail))
        return 0 if status == "ok" else (0 if status == "skipped" else 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
