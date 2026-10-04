#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端自测:收集诊断包 -> 上传到一次性本地 http 收件端 -> 校验收到且字节一致。

纯本地(127.0.0.1 临时端口),用完即关,不留外部依赖、不硬编码任何生产端点。
仅用于验证 collect_diagnostics + upload_diagnostics 这条链路本身是通的。
"""
import os
import sys
import threading
import tempfile
import http.server

HERE = os.path.dirname(os.path.abspath(__file__))          # tests/
LAUNCHER = os.path.dirname(HERE)                            # tools/launcher(core 在此)
ROOT = os.path.dirname(os.path.dirname(LAUNCHER))           # 仓库根
sys.path.insert(0, LAUNCHER)
import dotabyss_offline_core as c  # noqa: E402

RECEIVED = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        RECEIVED["name"] = self.path
        RECEIVED["auth"] = self.headers.get("Authorization", "")
        RECEIVED["bytes"] = body
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_a):  # 静音
        pass


def main():
    game_dir = os.path.join(ROOT, "client")
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    url = "http://127.0.0.1:%d/diag" % port
    os.environ[c.DIAG_UPLOAD_URL_ENV] = url
    os.environ[c.DIAG_UPLOAD_TOKEN_ENV] = "selftest-token"
    try:
        zip_path, lines = c.collect_diagnostics(game_dir)
        print("本地诊断包:", zip_path, "大小:", os.path.getsize(zip_path))
        status, detail = c.upload_diagnostics(game_dir, zip_path)
        print("上传状态:", status, "|", detail)
        assert status == "ok", "上传未成功"
        assert RECEIVED.get("bytes"), "收件端没拿到 body"
        with open(zip_path, "rb") as f:
            local = f.read()
        assert local in RECEIVED["bytes"], "收到的 multipart body 里不含完整 zip 字节"
        print("收到路径:", RECEIVED["name"], "| Authorization:", RECEIVED["auth"])
        print("zip 完整送达校验: 通过 (zip %d bytes / body %d bytes)"
              % (len(local), len(RECEIVED["bytes"])))
        # 确认摘要里有崩溃签名段
        sig_idx = [i for i, l in enumerate(lines) if "崩溃签名抽取" in l]
        print("diag_summary 含崩溃签名段:", bool(sig_idx))
        if sig_idx:
            for l in lines[sig_idx[0]:sig_idx[0] + 6]:
                print("   ", l[:120])
        print("\n端到端自测:全部通过")
    finally:
        srv.shutdown()
        os.environ.pop(c.DIAG_UPLOAD_URL_ENV, None)
        os.environ.pop(c.DIAG_UPLOAD_TOKEN_ENV, None)


if __name__ == "__main__":
    main()
