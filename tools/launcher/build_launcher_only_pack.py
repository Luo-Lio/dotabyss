#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「只更启动器 + 插件锁 0.7.19」的最小增量发布目录。

区别于 build_github_pack.py(全量重打 dll/stories/previews/catalog/master_data/client_body),
本脚本只产出启动器与指定插件 dll,version.json 也只声明 plugin_md5 + launcher_md5——
更新客户端逐字段夹住「缺附件/缺字段即跳过」(见 dotabyss_launcher._do_update),所以:
  · 已在 0.7.19 的玩家:dll md5 命中 → 跳过 dll 步,只换启动器;
  · 误取过 0.7.20 的玩家:dll md5 不符 → 回退到 0.7.19。
带 --expect-plugin-md5 硬校验,杜绝把 0.7.20 打进发布。

产物 dist/release_<版本>/:version.json、StoryViewer.dll、DotabyssOfflineLauncher.exe、
release.json(离线演练用的 GitHub API 返回体,真实上传时忽略)。
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dotabyss_offline_core as core  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
DIST = os.path.join(REPO, "dist")


def main() -> int:
    ap = argparse.ArgumentParser(description="只更启动器 + 锁插件版本的最小发布")
    ap.add_argument("--version", default="20261005", help="新版本号(勿复用已撤回的 20261004)")
    ap.add_argument("--plugin-dll",
                    default=os.path.join(DIST, "release_20261003", "StoryViewer.dll"),
                    help="要随发的插件 dll(默认取 1003 里的 0.7.19)")
    ap.add_argument("--launcher",
                    default=os.path.join(REPO, "client", core.LAUNCHER_EXE_NAME),
                    help="新冻结的启动器 exe")
    ap.add_argument("--baseline", default="20260924", help="基线(与在线 Release 保持一致,勿改)")
    ap.add_argument("--channel", default="baseline")
    ap.add_argument("--plugin-version", default="0.7.19")
    ap.add_argument("--expect-plugin-md5", default="6d4e963c85ece074bdf9865076de7315",
                    help="期望插件 md5(0.7.19);不匹配即中止,防误打 0.7.20")
    ap.add_argument("--repo", default="Luo-Lio/dotabyss", help="仅用于演练 release.json")
    ap.add_argument("--notes", default="更新启动器(新增日志回传取证);插件保持 0.7.19。")
    args = ap.parse_args()

    for path, label in ((args.plugin_dll, "插件 dll"), (args.launcher, "启动器 exe")):
        if not os.path.isfile(path):
            print("[ABORT] 缺 %s:%s" % (label, path))
            return 1

    pm5 = core.file_md5(args.plugin_dll)
    if args.expect_plugin_md5 and pm5.lower() != args.expect_plugin_md5.lower():
        print("[ABORT] 插件 md5=%s 非预期 0.7.19(%s)——拒绝发布(可能是 0.7.20)"
              % (pm5, args.expect_plugin_md5))
        return 1
    lm5 = core.file_md5(args.launcher)

    out = os.path.join(DIST, "release_%s" % args.version)
    os.makedirs(out, exist_ok=True)
    shutil.copyfile(args.plugin_dll, os.path.join(out, "StoryViewer.dll"))
    shutil.copyfile(args.launcher, os.path.join(out, core.LAUNCHER_EXE_NAME))

    version = {
        "version": args.version,
        "baseline": args.baseline,
        "channel": args.channel,
        "notes": args.notes,
        "plugin_version": args.plugin_version,
        "plugin_md5": pm5,
        "launcher_md5": lm5,
    }
    with open(os.path.join(out, "version.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(version, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    base = "https://github.com/%s/releases/download/%s" % (args.repo, args.version)
    release = {"tag_name": args.version, "assets": [
        {"name": "version.json", "browser_download_url": base + "/version.json"},
        {"name": "StoryViewer.dll", "browser_download_url": base + "/StoryViewer.dll"},
        {"name": core.LAUNCHER_EXE_NAME, "browser_download_url": base + "/" + core.LAUNCHER_EXE_NAME},
    ]}
    with open(os.path.join(out, "release.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(release, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print("[gen] %s" % out)
    print("  version=%s baseline=%s 插件=%s(md5=%s) 启动器 md5=%s"
          % (args.version, args.baseline, args.plugin_version, pm5, lm5))
    print("  附件:version.json / StoryViewer.dll / %s / release.json(仅演练)"
          % core.LAUNCHER_EXE_NAME)
    print("\n[真实上传] gh release create %s --title \"离线包 %s\" --notes \"%s\" "
          "dist\\release_%s\\version.json dist\\release_%s\\StoryViewer.dll "
          "dist\\release_%s\\%s" % (args.version, args.version, args.notes,
                                     args.version, args.version, args.version, core.LAUNCHER_EXE_NAME))
    print("(注意:别把 release.json 传上去——那是演练用的假 API 返回。)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
