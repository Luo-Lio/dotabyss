#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成剧情预览图(背景 + 立绘 + 标题),输出到插件预览目录。

数据源
------
- ``tools/client-mod/StoryViewer/stories.json``  插件列表里的全部剧情(权威列表,1229 条)
- ``output/stories/<key>.js``                    剧情脚本,取首个背景与首个立绘
- ``output/bg/<id>.png``                         背景(方图,中心裁剪)
- ``output/charastand/<art>.png``                立绘(透明通道)

输出
----
``<client>/BepInEx/plugins/StoryViewer/previews/<key>.jpg``(480x270, JPEG q=82)。
插件按 ``<key>.jpg`` 直接查找,无需索引文件。

用法
----
    python -X utf8 tools/make-previews.py                 # 增量生成(跳过已存在)
    python -X utf8 tools/make-previews.py --force         # 全部重生成
    python -X utf8 tools/make-previews.py --only hmr_10020100011 --show   # 单条调试
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 路径与常量

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # 项目根 E:\agent\dmm\dotabyss
OUTPUT = os.path.join(ROOT, "output")
STORIES_JSON = os.path.join(HERE, "client-mod", "StoryViewer", "stories.json")
PREVIEW_DIR = os.path.join(ROOT, "client", "BepInEx", "plugins", "StoryViewer", "previews")

W, H = 480, 270                # 输出尺寸
BG_CACHE_SIZE = (960, 540)     # 背景预缩放尺寸(全图共用,先把大图缩一次再逐条裁剪)
CHARA_CACHE_H = 540            # 立绘预缩放高度
CROP_BIAS_Y = 0.42             # 方图裁 16:9 时的纵向重心(0=顶部,1=底部)
CHARA_SCALE = 0.94             # 立绘高度占画布比例
CHARA_RIGHT_MARGIN = 6         # 立绘右对齐边距
JPEG_QUALITY = 82

# 字体:统一用微软雅黑(系列标签是简体中文,日文字体会缺字;雅黑同时覆盖假名与常用汉字)
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
FONT_FALLBACK = r"C:\Windows\Fonts\msyh.ttc"

# 系列配色(按系列短名;未知系列用中性色)
SERIES_COLOR = {
    "main": (58, 124, 165),
    "home": (122, 94, 168),
    "chara": (192, 106, 46),
    "tavern": (168, 62, 82),
    "side": (78, 140, 106),
}
SERIES_COLOR_FALLBACK = (90, 104, 122)
R18_COLOR = (122, 34, 51)

TEXT_MAIN = (232, 238, 245)
TEXT_SUB = (196, 208, 220)
SHADOW = (4, 6, 9, 210)


# ---------------------------------------------------------------- 数据读取

def load_stories() -> dict:
    """读取插件剧情索引(series + stories),返回原 dict。"""
    with io.open(STORIES_JSON, encoding="utf-8") as fh:
        return json.load(fh)


_decoder = json.JSONDecoder()


def load_scenario(key: str) -> dict | None:
    """解析 output/stories/<key>.js,返回剧情 JSON;失败返回 None。

    文件形如 ``window.STORY=window.STORY||{};window.STORY["key"]={...};``,
    用 raw_decode 从最后一处 ``={`` 之后解析,可容忍前后缀。
    """
    path = os.path.join(OUTPUT, "stories", f"{key}.js")
    if not os.path.exists(path):
        return None
    try:
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
        i = text.rindex("={")
        obj, _ = _decoder.raw_decode(text, i + 1)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def first_asset(scenario: dict, mark: str, index: int) -> str | None:
    """取 ev 里第一条 ``[mark, ...]`` 指令的第 index 个参数(如 b/背景、+/立绘)。"""
    for ev in scenario.get("ev") or []:
        if isinstance(ev, list) and ev and ev[0] == mark and len(ev) > index:
            val = ev[index]
            if isinstance(val, str) and val:
                return val
    return None


def pick_bg(scenario: dict) -> str | None:
    """优先取首个 'b' 指令;退回 bgs 清单第一条。"""
    return first_asset(scenario, "b", 1) or next(
        (x for x in (scenario.get("bgs") or []) if isinstance(x, str) and x), None
    )


def pick_chara(scenario: dict) -> str | None:
    """优先取首个 '+' 立绘指令;退回 arts 清单第一条。"""
    return first_asset(scenario, "+", 2) or next(
        (x for x in (scenario.get("arts") or []) if isinstance(x, str) and x), None
    )


# ---------------------------------------------------------------- 图像合成

def load_chara_index() -> dict[str, str]:
    """扫描 charastand 目录,建立「art_id → 文件名」索引。

    文件名形如 ``100201000G.png``(G=通常/X=表情差分等),同一 art_id 可能有多份;
    优先 G 版本,其次字母序最靠前者。
    """
    index: dict[str, str] = {}
    root = os.path.join(OUTPUT, "charastand")
    if not os.path.isdir(root):
        return index
    for name in os.listdir(root):
        if not name.lower().endswith(".png"):
            continue
        stem = name[:-4]
        art_id = "".join(ch for ch in stem if ch.isdigit())
        if not art_id:
            continue
        prev = index.get(art_id)
        if prev is None or (stem.endswith("G") and not prev[:-4].endswith("G")):
            index[art_id] = name
    return index


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """加载字体;失败时退到微软雅黑,再失败用 Pillow 内置位图字体。"""
    for p in (path, FONT_FALLBACK):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def cover_crop(img: Image.Image, size: tuple[int, int], bias_y: float) -> Image.Image:
    """等比缩放并裁剪到目标尺寸(cover),bias_y 控制纵向裁剪重心。"""
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    nw, nh = max(tw, int(img.width * scale + 0.5)), max(th, int(img.height * scale + 0.5))
    resized = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = int((nh - th) * max(0.0, min(1.0, bias_y)))
    return resized.crop((left, top, left + tw, top + th))


class AssetCache:
    """背景/立绘的预缩放缓存:同一素材在全量生成中只解码一次。"""

    def __init__(self) -> None:
        self._bgs: dict[str, Image.Image] = {}
        self._charas: dict[str, Image.Image] = {}
        self._missing: set[str] = set()
        self._chara_index = load_chara_index()

    def bg(self, bg_id: str | None) -> Image.Image | None:
        """取预缩放后的背景(960x540);缺失返回 None。"""
        if not bg_id or bg_id in self._missing:
            return None
        if bg_id not in self._bgs:
            path = os.path.join(OUTPUT, "bg", f"{bg_id}.png")
            if not os.path.exists(path):
                self._missing.add(bg_id)
                return None
            with Image.open(path) as raw:
                self._bgs[bg_id] = cover_crop(raw.convert("RGB"), BG_CACHE_SIZE, CROP_BIAS_Y)
        return self._bgs[bg_id]

    def chara(self, art_id: str | None) -> Image.Image | None:
        """取预缩放后的立绘(RGBA,高 540);缺失返回 None。"""
        if not art_id or art_id in self._missing:
            return None
        if art_id not in self._charas:
            name = self._chara_index.get(art_id)
            path = os.path.join(OUTPUT, "charastand", name) if name else ""
            if not path or not os.path.exists(path):
                self._missing.add(art_id)
                return None
            with Image.open(path) as raw:
                img = raw.convert("RGBA")
                h = CHARA_CACHE_H
                w = max(1, int(img.width * h / img.height + 0.5))
                self._charas[art_id] = img.resize((w, h), Image.LANCZOS)
        return self._charas[art_id]


def gradient_bg(series_key: str) -> Image.Image:
    """无背景素材时的兜底:系列色调的纵向渐变 + 点阵纹理(呼应游戏的「dot」母题)。"""
    base = SERIES_COLOR.get(series_key, SERIES_COLOR_FALLBACK)
    top = tuple(int(c * 0.42) for c in base)
    bottom = (10, 13, 18)
    col = Image.new("RGB", (1, H))
    for y in range(H):
        t = (y / (H - 1)) ** 0.9
        col.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    canvas = col.resize((W, H), Image.BILINEAR)
    draw = ImageDraw.Draw(canvas, "RGBA")
    for gy in range(8, H, 16):
        for gx in range(8, W, 16):
            draw.rectangle((gx, gy, gx + 1, gy + 1), fill=(255, 255, 255, 10))
    return canvas


def draw_bottom_fade(canvas: Image.Image) -> None:
    """底部渐隐(保证标题可读),顶部少量压暗(保证标签可读)。"""
    fade_h = int(H * 0.52)
    fade = Image.new("L", (1, fade_h))
    for y in range(fade_h):
        fade.putpixel((0, y), int(205 * (y / max(1, fade_h - 1)) ** 1.35))
    fade = fade.resize((W, fade_h), Image.BILINEAR)
    canvas.paste(Image.new("RGB", (W, fade_h), (5, 8, 12)), (0, H - fade_h), fade)

    top = Image.new("L", (W, 44))
    for y in range(44):
        top.paste(int(120 * (1 - y / 43) ** 1.5), (0, y, W, y + 1))
    canvas.paste(Image.new("RGB", (W, 44), (4, 6, 9)), (0, 0), top)


def draw_pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
              font: ImageFont.FreeTypeFont, bg: tuple[int, int, int]) -> tuple[int, int, int, int]:
    """画一个圆角标签(系列/R18),返回其包围盒。"""
    x, y = xy
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    pad_x, pad_y = 7, 3
    box = (x, y, x + (r - l) + pad_x * 2, y + (b - t) + pad_y * 2)
    draw.rounded_rectangle(box, radius=4, fill=bg)
    draw.text((x + pad_x - l, y + pad_y - t), text, font=font, fill=(255, 255, 255))
    return box


def wrap_title(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
               max_w: int, max_lines: int = 2) -> list[str]:
    """按像素宽度折行(日语无空格,逐字符累加);超出部分用省略号。"""
    if not text:
        return []
    lines: list[str] = []
    cur = ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
            continue
        lines.append(cur)
        cur = ch
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
        cur = ""
    if cur:  # 还有放不下的内容 → 末行省略号
        last = lines[-1] if lines else ""
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        if lines:
            lines[-1] = last + "…"
    return lines[:max_lines]


def compose(story: dict, scenario: dict | None, cache: AssetCache,
            series_label: str, fonts: dict) -> Image.Image:
    """合成单条预览图。"""
    canvas = Image.new("RGB", (W, H), (12, 16, 22))
    series_key = story.get("s") or ""
    bg_id = pick_bg(scenario) if scenario else None
    bg = cache.bg(bg_id)
    if bg is not None:
        canvas.paste(bg.resize((W, H), Image.LANCZOS), (0, 0))
    else:
        canvas.paste(gradient_bg(series_key), (0, 0))

    chara = cache.chara(pick_chara(scenario) if scenario else None)
    if chara is not None:
        target_h = max(1, int(H * CHARA_SCALE))
        target_w = max(1, int(chara.width * target_h / chara.height))
        max_w = int(W * 0.62)  # 立绘过宽(多人/横幅构图)时改为按宽度约束
        if target_w > max_w:
            target_w, target_h = max_w, max(1, int(chara.height * max_w / chara.width))
        sprite = chara.resize((target_w, target_h), Image.LANCZOS)
        canvas.paste(sprite, (W - target_w - CHARA_RIGHT_MARGIN, H - target_h), sprite)

    draw_bottom_fade(canvas)
    draw = ImageDraw.Draw(canvas)

    # 左上系列标签 / 右上 R18 标签(系列为空时不画,避免出现空胶囊)
    key = story.get("k") or ""
    tag = (series_label or series_key or "").strip()
    if tag:
        draw_pill(draw, (10, 9), tag, fonts["tag"],
                  SERIES_COLOR.get(series_key, SERIES_COLOR_FALLBACK))
    if story.get("r18"):
        draw_pill(draw, (W - 10 - 62, 9), "R18", fonts["tag"], R18_COLOR)

    # 左下标题 + 角色名 + key(中文优先;标题已回退为 key 时不重复显示)
    title = (story.get("tz") or story.get("t") or "").strip() or key
    lines = wrap_title(draw, title, fonts["title"], W - 24)
    chara_name = (story.get("cz") or story.get("c") or "").strip()
    meta = "  /  ".join(p for p in (chara_name, "" if title == key else key) if p)

    meta_h = fonts["meta"].size + 6 if meta else 0
    y = H - 14 - meta_h - len(lines) * (fonts["title"].size + 4)
    for line in lines:
        draw.text((12, y), line, font=fonts["title"], fill=TEXT_MAIN,
                  stroke_width=2, stroke_fill=SHADOW)
        y += fonts["title"].size + 4
    if meta:
        draw.text((12, H - 12 - fonts["meta"].size), meta, font=fonts["meta"],
                  fill=TEXT_SUB, stroke_width=2, stroke_fill=SHADOW)
    return canvas


# ---------------------------------------------------------------- 主流程

def main() -> int:
    """命令行入口:批量生成预览图。"""
    ap = argparse.ArgumentParser(description="生成剧情预览图")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的预览图")
    ap.add_argument("--only", help="只生成指定 key(调试用)")
    ap.add_argument("--show", action="store_true", help="打印将使用的素材信息")
    args = ap.parse_args()

    data = load_stories()
    stories = data.get("stories") or []
    labels = {s.get("key"): s.get("label") for s in (data.get("series") or [])}
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    fonts = {
        "tag": load_font(FONT_REG, 12),
        "title": load_font(FONT_BOLD, 19),
        "meta": load_font(FONT_REG, 11),
    }
    cache = AssetCache()

    targets = [s for s in stories if not args.only or s.get("k") == args.only]
    if not targets:
        print(f"没有匹配的剧情: {args.only}")
        return 1

    started = time.time()
    done = skipped = failed = 0
    fallback_bg = fallback_chara = 0
    for idx, story in enumerate(targets, 1):
        key = story.get("k") or ""
        if not key:
            continue
        dst = os.path.join(PREVIEW_DIR, f"{key}.jpg")
        if os.path.exists(dst) and not args.force:
            skipped += 1
            continue
        try:
            scenario = load_scenario(key)
            if scenario is None:
                fallback_bg = fallback_chara = 1  # 无脚本:仅背景兜底
            if args.show:
                print(f"{key}: bg={pick_bg(scenario) if scenario else None} "
                      f"chara={pick_chara(scenario) if scenario else None} "
                      f"title={(story.get('t') or '')[:24]}")
            img = compose(story, scenario, cache, labels.get(story.get("s")), fonts)
            img.save(dst, "JPEG", quality=JPEG_QUALITY, optimize=True)
            done += 1
        except Exception as exc:  # 单条失败不影响整体
            failed += 1
            print(f"  !! {key} 生成失败: {exc}", file=sys.stderr)
        if idx % 100 == 0:
            print(f"  ... {idx}/{len(targets)}(成功 {done} / 跳过 {skipped} / 失败 {failed})")

    total_mb = sum(
        os.path.getsize(os.path.join(PREVIEW_DIR, f))
        for f in os.listdir(PREVIEW_DIR) if f.endswith(".jpg")
    ) / 1024 / 1024
    print(f"完成: 生成 {done} / 跳过 {skipped} / 失败 {failed};"
          f" 目录 {len([f for f in os.listdir(PREVIEW_DIR) if f.endswith('.jpg')])} 张,"
          f" 共 {total_mb:.1f} MB, 用时 {time.time() - started:.1f}s")
    print(f"输出目录: {PREVIEW_DIR}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
