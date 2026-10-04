#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从构建环境变量生成 dotabyss_diag_default.py(内建默认端点,base64 编码)。

由 freeze_launcher.ps1 在冻结前调用:把 DOTABYSS_DIAG_UPLOAD_URL/TOKEN 编码写进
一个 gitignore 的模块,随 PyInstaller 烘进启动器 exe,使老玩家仅更新启动器也能回传。
未设 URL 则写入空串(不内建任何端点)。真实 IP/令牌不进 Git。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dotabyss_offline_core as core  # noqa: E402


def main() -> int:
    url = os.environ.get(core.DIAG_UPLOAD_URL_ENV, "").strip()
    token = os.environ.get(core.DIAG_UPLOAD_TOKEN_ENV, "").strip()
    b64 = core._diag_encode_endpoint(url, token) if url else ""
    out = os.path.join(HERE, "dotabyss_diag_default.py")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# 生成文件:勿手改、勿提交(已 gitignore)。由 make_diag_default.py 从构建 env 写入,\n")
        fh.write("# 随 freeze 烘进启动器 exe 作内建默认端点(base64,明文不进 Git)。删除=回到仅 env/launcher.json 决定。\n")
        fh.write("ENDPOINT_B64 = %r\n" % b64)
    print("已生成 %s(内建端点:%s)" % (out, "有" if b64 else "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
