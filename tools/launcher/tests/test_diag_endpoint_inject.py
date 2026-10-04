#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试:build_full_pack 是否把诊断回传端点以「编码隐身字段」注入 launcher.json。

用假的 URL/令牌(不含真实机密),验证:
  1) 设了 DOTABYSS_DIAG_UPLOAD_URL 时,生成的 launcher.json 含 diag_endpoint;
  2) diag_endpoint 能解码回原 url/token;
  3) 明文 url/token 不出现在 launcher.json 文本里(隐身);
  4) 原有 github_repo 字段保留;
  5) 未设 env 时不写 diag_endpoint(向后兼容)。
独立可跑:python tests/test_diag_endpoint_inject.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.dirname(HERE)
sys.path.insert(0, LAUNCHER)

import dotabyss_offline_core as core  # noqa: E402
import build_full_pack as bfp  # noqa: E402

FAKE_URL = "http://example.invalid:65001/ingest/deadbeef"
FAKE_TOKEN = "DUMMYTOKEN-not-a-secret"


def _seed_out_dir():
    out = tempfile.mkdtemp()
    for p in (core.plugin_dll_path(out), core.stories_path(out), core.launcher_path(out)):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(b"x")
    return out


def _read_launcher(out):
    with open(core.launcher_json_path(out), "r", encoding="utf-8") as fh:
        return fh.read()


def test_inject_encoded_endpoint():
    os.environ["DOTABYSS_DIAG_UPLOAD_URL"] = FAKE_URL
    os.environ["DOTABYSS_DIAG_UPLOAD_TOKEN"] = FAKE_TOKEN
    try:
        out = _seed_out_dir()
        bfp.write_version_and_repo(out, "TESTVER", "user/repo", out, "", "baseline")
        raw = _read_launcher(out)
        data = json.loads(raw)
        assert "diag_endpoint" in data, "缺 diag_endpoint"
        assert data.get("github_repo") == "user/repo", "github_repo 丢失"
        url, token = core._diag_decode_endpoint(data["diag_endpoint"])
        assert url == FAKE_URL and token == FAKE_TOKEN, "解码值不符"
        assert "example.invalid" not in raw and "65001" not in raw and FAKE_TOKEN not in raw, "明文泄漏"
    finally:
        os.environ.pop("DOTABYSS_DIAG_UPLOAD_URL", None)
        os.environ.pop("DOTABYSS_DIAG_UPLOAD_TOKEN", None)


def test_no_endpoint_when_env_absent():
    os.environ.pop("DOTABYSS_DIAG_UPLOAD_URL", None)
    os.environ.pop("DOTABYSS_DIAG_UPLOAD_TOKEN", None)
    out = _seed_out_dir()
    bfp.write_version_and_repo(out, "TESTVER", "user/repo", out, "", "baseline")
    data = json.loads(_read_launcher(out))
    assert "diag_endpoint" not in data, "无 env 却写了 diag_endpoint"


def test_roundtrip_encode_decode():
    enc = core._diag_encode_endpoint(FAKE_URL, FAKE_TOKEN)
    assert core._diag_decode_endpoint(enc) == (FAKE_URL, FAKE_TOKEN)
    assert core._diag_decode_endpoint("") == ("", "")
    assert core._diag_decode_endpoint("!!!not-base64!!!") == ("", "")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("全部通过")
