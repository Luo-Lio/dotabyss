# -*- coding: utf-8 -*-
"""把游戏原版的 R18 剧情封面铺进插件预览目录。

背景:游戏的 R18 剧情在 catalog 里有专门的封面资产 ``story_s_<storyId>``
(已由 tools/export.py 导出到 ``output/story/``),而插件预览目录原先只有
按剧情 key 从其它途径生成的图。这里把原版封面按插件需要的命名铺进去。

映射规则(已全量校验:catalog 的 203 张封面 ↔ 列表 609 条 R18 条目,一一对应):
    条目 key(如 ``hmr_10010100011``)去掉末位分段号 → 封面 ``story_s_hmr_1001010001``
    同一故事的前/中/后篇共用一张封面。

输出:<client>/BepInEx/plugins/StoryViewer/previews/<key>.jpg(JPEG 质量 90,覆盖旧图)。
用法:python tools/client-mod/gen_covers.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))  # tools/client-mod -> 项目根
COVERS = os.path.join(PROJECT_ROOT, "output", "story")
STORIES = os.path.join(PROJECT_ROOT, "client", "BepInEx", "plugins", "StoryViewer", "stories.json")
PREVIEWS = os.path.join(PROJECT_ROOT, "client", "BepInEx", "plugins", "StoryViewer", "previews")
QUALITY = 90


def main() -> None:
    """读 stories.json 里的 R18 条目,按映射把原版封面写成 <key>.jpg。"""
    stories = json.loads(Path(STORIES).read_text(encoding="utf-8"))["stories"]
    r18 = [s for s in stories if s.get("r18")]

    os.makedirs(PREVIEWS, exist_ok=True)
    ok = skipped = failed = 0
    for entry in r18:
        key = entry["k"]
        cover = os.path.join(COVERS, f"story_s_{key[:-1]}.png")
        if not os.path.isfile(cover):
            skipped += 1
            continue
        out = os.path.join(PREVIEWS, f"{key}.jpg")
        try:
            with Image.open(cover) as img:
                # 封面为不透明彩图,统一转 RGB 再存 JPEG(带 alpha 时先合成到黑底)。
                if img.mode != "RGB":
                    img = img.convert("RGBA")
                    bg = Image.new("RGB", img.size, (0, 0, 0))
                    bg.paste(img, mask=img.split()[3])
                    img = bg
                img.save(out, "JPEG", quality=QUALITY)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - 单张失败不影响整体,打印后继续
            failed += 1
            print(f"失败: {key} <- {cover}: {exc}")

    total_mb = sum(os.path.getsize(os.path.join(PREVIEWS, f)) for f in os.listdir(PREVIEWS)) / 1024 / 1024
    print(f"写出 {ok} 张封面(跳过 {skipped} 张缺源、失败 {failed} 张);"
          f"预览目录现有 {len(os.listdir(PREVIEWS))} 个文件 / {total_mb:.1f} MB")


if __name__ == "__main__":
    main()
