# -*- coding: utf-8 -*-
"""剧情脚本解析:把命令式 ``.txt`` 脚本编译成离线播放用的紧凑事件流。

实测格式(ドットアビスX,纯文本、逗号分隔、逐行一条命令):

对白
    - ``message,<说话人>,<文本>[,<立绘id>,<语音id>,<角色槽>]``
    - ``dotmessage,<说话人>,<文本>,<...>,<对象名>,<位置>,<表情>,<x>,<y>``(像素剧情,13 字段)
    - ``l2dmessage,<...>``(Live2D 剧情,字段不稳定,按「说话人+文本」宽松解析)
旁白
    - ``messageTextCenter,,<文本>,,,on`` / ``messageTextUnder,,<文本>,,,on``
场景
    - ``bg,<背景id>``、``subimage,UI/BG/Novel/<背景id>,...``
角色
    - ``charaload,<槽>,<立绘id>,<名字>``(载入即可见)
    - ``objectload,<对象名>,CHARA,<立绘id>,<显示名>``(载入后默认隐藏,靠 objectshow 显现)
    - ``objectshow/objecthide,<对象名>[,<值>]``、``charashow`` / ``charahide``(含 ``async`` 变体)
    - ``charamove,...,X,<x>,<y>`` / ``dotmove,<名>,<时长>,<x>,<y>,<z>,...``(像素舞台坐标)
    - ``charascale,<槽>,<倍率>`` / ``charaface,<槽>,<FaceXxx>`` / ``cleanall,ALL``
    - ``charaemo,<槽>,<符号>,<CONT|STOP>,<时长>``:漫画式情绪符号(个人剧情里很密)
控制
    - ``:<标签>`` 定义标签、``labeljump,<标签>`` 跳转(解析期直接跳,带步数上限防环)

其余命令(动效/音频/镜头/震屏/模糊/遮罩/时间轴…)一律忽略:离线播放只还原
「背景 + 角色 + 文本」三要素;这些命令不影响这三者的最终状态。

输出格式(每条事件都是紧凑数组,``t`` 为事件类型):

- ``["b", <背景id>]``                            切背景
- ``["+", <槽>, <立绘id>, <名字>, <?mob>, <?隐]]`` 载入角色(``mob=1`` 无立绘;``隐=1`` 初始隐藏)
- ``["sh"|"h", <槽>]``                            显示/隐藏
- ``["x", <槽>, <百分比>]``                       横向位置(已归一到舞台百分比,可为负/超出 100)
- ``["y", <槽>, <数值>]``                         纵向位置(设计稿像素,播放器暂不使用)
- ``["s", <槽>, <倍率>]``                         缩放
- ``["f", <槽>, <FaceXxx>]``                      表情
- ``["e", <槽>, <符号名>, <CONT|STOP>]``           情绪符号(CONT 持续到被替换;``*`` 表示全体清除)
- ``["m", <说话人>, <文本>, <?槽>]``               对白
- ``["n", <文本>, <?center>]``                    旁白
- ``["clr"]``                                     清空全部角色

坐标归一(实测两套坐标系):立绘剧情 ``charamove`` 的 X 是相对中心的像素(设计稿宽
1920),按 ``50 + x/19.2`` 转百分比;像素剧情 ``dotmove`` 的 X 是 0..20 的舞台单位
(10 = 居中,负数为台外),按 ``x*5`` 转百分比。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import UnityPy

from .catalog import BundleRecord

# 脚本 bundle 名形如 ``..._<key>_<key>.txt_<md5>.bundle``
SCRIPT_KEY_RE = re.compile(r"_([a-z]{2,4}_[0-9a-z]+)_\1\.txt_", re.I)
# 立绘 id:6 位以上数字 + 可选字母后缀(如 100101000G);无后缀的是像素单位(Spine)
ART_ID_RE = re.compile(r"^\d{6,}[A-Za-z]?$")
FACE_RE = re.compile(r"^(?:Face|Eye)[A-Za-z0-9]+$")
SLOT_RE = re.compile(r"^chara_\d+$")
BG_PREFIX = "UI/BG/Novel/"

MAX_EVENTS = 20000
MAX_JUMPS = 400

# 脚本 key 前缀 → 剧情索引里的系列名(story.SERIES 的 key)
PREFIX_SERIES = {"mas": "main", "men": "home", "hmn": "chara", "hmr": "tavern", "evs": "side"}


def load_script_text(data: Path) -> str | None:
    """读出脚本 bundle 里的 TextAsset 文本。

    Args:
        data: bundle 的 ``__data`` 路径。

    Returns:
        脚本文本;bundle 里没有 TextAsset 时返回 None。
    """
    env = UnityPy.load(str(data))
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        d = obj.read()
        raw = getattr(d, "m_Script", None)
        if raw is None:
            raw = getattr(d, "script", "")
        return raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
    return None


def scan_scripts(records: list[BundleRecord], cache_dir: Path) -> dict[str, tuple[BundleRecord, Path]]:
    """扫描缓存里的剧情脚本,返回 ``key → (记录, __data 路径)``。

    同一个 key 可能有多份记录(历史版本),优先取已缓存的那份;都缓存时取
    cdn 名较小的一份,保证结果稳定。

    Args:
        records: catalog 记录。
        cache_dir: ``Caches`` 目录。

    Returns:
        dict: 剧情 key → (bundle 记录, ``__data`` 路径)。
    """
    found: dict[str, list[tuple[str, BundleRecord, Path]]] = {}
    for record in records:
        m = SCRIPT_KEY_RE.search(record.asset_hint or "")
        if not m:
            continue
        cdn_dir = cache_dir / record.cdn
        if not cdn_dir.is_dir():
            continue  # 游戏持续下载会轮换缓存目录
        data = next((p / "__data" for p in cdn_dir.iterdir() if (p / "__data").is_file()), None)
        if data is None:
            continue
        found.setdefault(m.group(1), []).append((record.cdn, record, data))
    return {key: (sorted(v)[0][1], sorted(v)[0][2]) for key, v in found.items()}


def _num(text: str) -> float | None:
    """把字符串转成 float,失败返回 None。"""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _pct_of_px(x: float) -> float:
    """立绘剧情 ``charamove`` 的 X(相对中心的像素)转舞台百分比。

    设计稿宽 1920,中心 50%,故 ``50 + x / 19.2``。
    """
    return round(50.0 + x / 19.2, 2)


def _pct_of_dot(x: float) -> float:
    """像素剧情 ``dotmove`` 的 X(0..20 的舞台单位,10 为居中)转舞台百分比。

    实测:11 人并排站位取 5..14.5,敌人候场用 26,-12.5 为左侧台外,故舞台宽 20 单位。
    """
    return round(x * 5.0, 2)


def _face_of(parts: list[str]) -> str:
    """从命令字段里找表情名(FaceXxx / EyeXxx)。"""
    for p in parts:
        if FACE_RE.match(p.strip()):
            return p.strip()
    return ""


def _message_parts(parts: list[str]) -> tuple[str, str, str]:
    """解析 ``message`` 行,返回 (说话人, 文本, 角色槽)。

    字段数实测 3~6(``speaker, text[, art[, voice[, slot]]]``);文本本身
    理论上可能含半角逗号,若字段数异常则按「末尾 3 个是可选字段」兜底。
    """
    speaker = parts[1].strip() if len(parts) > 1 else ""
    slot = parts[-1].strip() if parts and SLOT_RE.match(parts[-1].strip()) else ""
    if len(parts) >= 6 and slot:
        text = ",".join(parts[2:-3])
    elif len(parts) > 2:
        text = parts[2]
    else:
        text = ""
    return speaker, text, slot


def parse_script(text: str, known_art: set[str] | None = None) -> dict[str, Any]:
    """把脚本文本编译成事件流。

    Args:
        text: 脚本文本(``load_script_text`` 的返回值)。
        known_art: 已导出的立绘 id 集合;用于标记没有立绘的像素单位(``mob``)。

    Returns:
        dict: ``{"ev": [...], "cast": {...}, "bgs": [...], "arts": [...], "ignored": {...}}``。
    """
    known = known_art or set()
    lines = text.splitlines()
    labels: dict[str, int] = {}
    for i, raw in enumerate(lines):
        s = raw.strip().lstrip("\ufeff")
        if s.startswith(":") and len(s) > 1:
            labels[s[1:].strip()] = i

    ev: list[list[Any]] = []
    cast: dict[str, str] = {}
    bgs: set[str] = set()
    arts: set[str] = set()
    ignored: dict[str, int] = {}
    dot_stage = False
    i = 0
    jumps = 0
    while i < len(lines) and len(ev) < MAX_EVENTS:
        raw = lines[i].strip().lstrip("\ufeff")
        i += 1
        if not raw or raw.startswith("//") or raw.startswith(":"):
            continue
        parts = raw.split(",")
        cmd = parts[0].strip().lower()

        def arg(idx: int) -> str:
            return parts[idx].strip() if len(parts) > idx else ""

        if cmd == "bg":
            bg = arg(1)
            if bg:
                ev.append(["b", bg])
                bgs.add(bg)
        elif cmd == "subimage":
            path = arg(1)
            if path.startswith(BG_PREFIX):
                bg = path[len(BG_PREFIX):].strip("/")
                if bg:
                    ev.append(["b", bg])
                    bgs.add(bg)
        elif cmd == "dotbgload":
            # 像素剧情的背景:运行时用 3D 舞台(prefab 场景)渲染,与 bg_0/bg_1/bg_2
            # 三层视差合成,离线无法复现——只做标记,供播放器提示
            dot_stage = True
        elif cmd == "charaload":
            slot, art, name = arg(1), arg(2), arg(3)
            if slot:
                # 立绘剧情:载入即可见(无 charashow 也会出现在台上)
                ev.append(["+", slot, art, name, 0 if art in known else 1, 0])
                if art:
                    cast[slot] = f"{art}|{name}"
                    arts.add(art)
        elif cmd == "objectload" and arg(2).upper() == "CHARA":
            slot, art, name = arg(1), arg(3), arg(4)
            if slot:
                # 像素剧情:载入后默认隐藏,由 objectshow/objecthide 控制显隐
                ev.append(["+", slot, art, name, 0 if art in known else 1, 1])
                if art:
                    cast[slot] = f"{art}|{name}"
                    arts.add(art)
        elif cmd in ("charashow", "charashowalpha", "asynccharashow", "asynccharashowalpha",
                     "objectshow", "asyncobjectshow"):
            if arg(1):
                ev.append(["sh", arg(1)])
        elif cmd in ("charahide", "asynccharahide", "objecthide", "asyncobjecthide"):
            if arg(1):
                ev.append(["h", arg(1)])
        elif cmd in ("charamove", "asynccharamove"):
            slot = arg(1)
            axis = next((k for k, p in enumerate(parts) if p.strip().lower() in ("x", "charaheight")), -1)
            if slot and axis >= 0 and len(parts) > axis + 1:
                v = _num(parts[axis + 1])
                if v is not None:
                    if parts[axis].strip().lower() == "x":
                        ev.append(["x", slot, _pct_of_px(v)])
                    else:
                        ev.append(["y", slot, v])
        elif cmd in ("dotmove", "asyncdotmove"):
            # dotmove,<名>,<时长>,<x>,<y>,<z>,...;asyncdotmove 在时长后多一个缓动字段
            slot, v = arg(1), _num(arg(3))
            if slot and v is not None:
                ev.append(["x", slot, _pct_of_dot(v)])
        elif cmd in ("charascale", "asynccharascale"):
            slot, v = arg(1), _num(arg(2))
            if slot and v is not None:
                ev.append(["s", slot, v])
        elif cmd in ("charaface", "asynccharaface"):
            slot, face = arg(1), _face_of(parts[2:])
            if slot and face:
                ev.append(["f", slot, face])
        elif cmd in ("charaemo", "asynccharaemo", "objectemo", "asyncobjectemo"):
            # 情绪符号(漫画式气泡:Anger/Flower/Exclamation…),CONT=持续到被替换,STOP=只演一次
            slot, emo, mode = arg(1), arg(2), arg(3).upper()
            if slot and emo:
                ev.append(["e", slot, emo, "STOP" if mode == "STOP" else "CONT"])
        elif cmd == "emodelete":
            ev.append(["e", arg(1) or "*", "", "CONT"])
        elif cmd == "cleanall":
            ev.append(["clr"])
        elif cmd == "message":
            speaker, body, slot = _message_parts(parts)
            if body or speaker:
                row: list[Any] = ["m", speaker, body]
                if slot:
                    row.append(slot)
                ev.append(row)
        elif cmd == "dotmessage":
            speaker, body = arg(1), arg(2)
            obj = arg(8) if len(parts) > 12 else ""
            emo = arg(10) if len(parts) > 12 else ""
            if obj and emo:
                ev.append(["f", obj, emo])
            row = ["m", speaker, body]
            if obj:
                row.append(obj)
            ev.append(row)
        elif cmd == "l2dmessage":
            speaker, body = arg(1), arg(2)
            if body:
                ev.append(["m", speaker, body])
        elif cmd in ("messagetextcenter", "messagetextunder"):
            body = arg(2)
            if body:
                ev.append(["n", body, "c"] if cmd == "messagetextcenter" else ["n", body])
        elif cmd == "labeljump":
            target = arg(1).strip()
            if target and target in labels and jumps < MAX_JUMPS:
                i = labels[target]
                jumps += 1
        else:
            ignored[cmd] = ignored.get(cmd, 0) + 1

    return {
        "ev": ev,
        "cast": cast,
        "bgs": sorted(bgs),
        "arts": sorted(arts),
        "dot_stage": dot_stage,
        "ignored": dict(sorted(ignored.items(), key=lambda kv: -kv[1])),
    }


def story_js(payload: dict[str, Any]) -> str:
    """把一条剧情编译成可 ``<script src>`` 加载的 JS(避免 file:// 下 fetch 被拦)。

    Args:
        payload: 剧情数据。

    Returns:
        str: JS 源码。
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f'window.STORY=window.STORY||{{}};window.STORY[{json.dumps(payload["key"])}]={body};\n'


def build_story_payload(key: str, text: str, meta: dict[str, Any] | None,
                        known_art: set[str] | None = None) -> dict[str, Any]:
    """组装单条剧情的可播放数据。

    Args:
        key: 剧情 key(如 ``men_10010100001``)。
        text: 脚本文本。
        meta: 剧情索引里的条目(取 title/series/character)。
        known_art: 已导出的立绘 id 集合。

    Returns:
        dict: 含 ``key/series/title/character/ev/cast/bgs/arts`` 的播放数据。
    """
    parsed = parse_script(text, known_art)
    meta = meta or {}
    return {
        "key": key,
        "series": meta.get("series", ""),
        "title": meta.get("title", ""),
        "character": meta.get("character", ""),
        "chapter": meta.get("chapter_name", ""),
        "ev": parsed["ev"],
        "cast": parsed["cast"],
        "bgs": parsed["bgs"],
        "arts": parsed["arts"],
        "dot_stage": parsed["dot_stage"],
    }


def export_scripts(records: list[BundleRecord], cache_dir: Path, out_dir: Path,
                   metas: dict[str, dict] | None = None, known_art: set[str] | None = None,
                   only: set[str] | None = None, force: bool = False,
                   old: dict[str, dict] | None = None) -> dict[str, dict]:
    """把缓存里的剧情脚本导出为 ``stories/<key>.js``,并返回清单。

    Args:
        records: catalog 记录。
        cache_dir: ``Caches`` 目录。
        out_dir: 输出根目录。
        metas: 剧情 key → 索引条目(补标题/系列/角色)。
        known_art: 已导出的立绘 id 集合。
        only: 只导出这些系列前缀(``{"mas", "men"}``);None 表示全部。
        force: 覆盖已存在的脚本文件。
        old: 上次的脚本清单(用于跳过未变化的重写)。

    Returns:
        dict: ``key → {"file": 相对路径, "beats": 事件数, "bytes": 大小, "arts": 立绘数,
        "bgs": 背景数, "series": 系列, "title": 标题, "character": 角色名}``。
    """
    metas = metas or {}
    old = old or {}
    story_dir = out_dir / "stories"
    scripts = scan_scripts(records, cache_dir)
    result: dict[str, dict] = {}
    for key in sorted(scripts):
        prefix = key.split("_")[0]
        if only and prefix not in only:
            continue
        record, data = scripts[key]
        text = None
        try:
            text = load_script_text(data)
        except Exception:  # noqa: BLE001 - 单个脚本读失败不影响整批
            text = None
        if not text:
            continue
        # 索引只收录「前篇」key,后篇(末位 12)沿用去尾位的条目元数据
        meta = metas.get(key) or metas.get(key[:-1]) or {}
        payload = build_story_payload(key, text, meta, known_art)
        if not payload["series"]:
            payload["series"] = PREFIX_SERIES.get(prefix, prefix)
        rel = f"stories/{key}.js"
        path = story_dir / f"{key}.js"
        body = story_js(payload)
        old_entry = old.get(key) or {}
        if force or not path.is_file() or old_entry.get("bytes") != len(body.encode("utf-8")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        result[key] = {
            "file": rel,
            "beats": sum(1 for e in payload["ev"] if e[0] in ("m", "n")),
            "bytes": len(body.encode("utf-8")),
            "arts": len(payload["arts"]),
            "bgs": len(payload["bgs"]),
            "series": payload["series"] or PREFIX_SERIES.get(prefix, prefix),
            "title": payload["title"],
            "character": payload["character"],
        }
    return result
