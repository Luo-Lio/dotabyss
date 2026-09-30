# -*- coding: utf-8 -*-
"""校验产物一致性:manifest 与 (catalog + 缓存) 的预期集合是否吻合,文件是否齐全。

用法:
    python -m tools.verify
退出码 0 表示一致,1 表示存在缺失/多余/文件丢失。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .catalog import parse_catalog, pick_latest_catalog
from .export import classify, scan_cache
from .extract import id_for
from .paths import discover

# 游戏边玩边下载时,bundle 会在「导出扫描之后、verify 之前」落盘;
# 缓存目录 mtime 落在导出窗口内(manifest 写入时间往前 30 分钟)的一律视为滞后而非缺陷。
LAG_WINDOW_SECONDS = 1800


def main() -> int:
    """入口。

    Returns:
        int: 0 一致;1 不一致。
    """
    p = discover()
    manifest_path = p.out_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"[错误] 找不到 {manifest_path},请先运行 python -m tools.export")
        return 1
    records = parse_catalog(pick_latest_catalog(p.catalog_dir))
    hits, stats = scan_cache(p.cache_dir, {r.cdn: r for r in records})

    expected: dict[str, str] = {}
    hit_by_key: dict[str, str] = {}
    for record, _data in hits:
        kind = classify(record)
        if kind:
            key = f"{kind}:{id_for(record, kind)}"
            expected[key] = record.name
            hit_by_key[key] = record.cdn

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    have = {f"{it['kind']}:{it['art_id']}": it for it in manifest["items"]}
    # 引用型 bundle(图像在别的 bundle 里)本就无产物,不算缺失
    referenced = {f"{r['kind']}:{r['art_id']}" for r in manifest.get("references", [])}
    missing = sorted(k for k in expected if k not in have and k not in referenced)
    extra = sorted(k for k in have if k not in expected)
    # 游戏边玩边下载时,导出后才落盘的 bundle 会表现为「应导未导」;按缓存目录 mtime 区分滞后与真缺失
    manifest_mtime = manifest_path.stat().st_mtime
    lag, real_missing = [], []
    for key in missing:
        cdn = hit_by_key.get(key, "")
        cdn_dir = p.cache_dir / cdn if cdn else None
        if cdn_dir is not None and cdn_dir.is_dir() and cdn_dir.stat().st_mtime >= manifest_mtime - LAG_WINDOW_SECONDS:
            lag.append(key)
        else:
            real_missing.append(key)

    listed: set[str] = set()
    file_missing: list[str] = []
    for item in manifest["items"]:
        files = list(item.get("files") or [])
        files += [f["file"] for f in (item.get("faces") or {}).values()]
        for rel in files:
            listed.add(rel)
            if not (p.out_dir / rel).is_file():
                file_missing.append(rel)
    # 动态素材(Live2D/Spine)与剧情封面的产物同样纳入校验
    for section in ("live2d", "spine"):
        for entry in (manifest.get("dynamic") or {}).get(section, []):
            for rel in entry.get("files", []):
                listed.add(rel)
                if not (p.out_dir / rel).is_file():
                    file_missing.append(rel)
    for entry in (manifest.get("stories") or {}).get("entries", []):
        rel = entry.get("thumb_file")
        if rel:
            listed.add(rel)
            if not (p.out_dir / rel).is_file():
                file_missing.append(rel)
    # 剧情脚本(output/stories/*.js):每条 playback 数据都必须在盘上
    script_missing: list[str] = []
    for key, entry in (manifest.get("scripts") or {}).items():
        rel = entry.get("file") or f"stories/{key}.js"
        listed.add(rel)
        if not (p.out_dir / rel).is_file():
            script_missing.append(rel)
        if not entry.get("beats"):
            script_missing.append(f"{rel}（0 段文本,疑似解析空）")
    on_disk = {str(x.relative_to(p.out_dir)).replace("\\", "/") for x in p.out_dir.rglob("*.png")}
    orphan = sorted(on_disk - listed)
    scripts_on_disk = {str(x.relative_to(p.out_dir)).replace("\\", "/") for x in (p.out_dir / "stories").glob("*.js")}
    script_orphan = sorted(scripts_on_disk - listed)

    print(f"缓存:目录 {stats['cache_dirs']},命中 {stats['hit']},md5 不符 {stats['md5_mismatch']}")
    print(f"清单:{len(have)} 项;预期:{len(expected)} 项")
    print(f"缺失(应导未导):{len(real_missing)}" + (f" {real_missing[:5]}" if real_missing else ""))
    if lag:
        print(f"滞后(导出后缓存新增,重跑 export 即可收敛):{len(lag)}" + (f" {lag[:5]}" if lag else ""))
    print(f"多余(当前扫描不再产出):{len(extra)}" + (f" {extra[:5]}" if extra else ""))
    print(f"清单引用的文件缺失:{len(file_missing)}" + (f" {file_missing[:5]}" if file_missing else ""))
    print(f"磁盘孤儿 PNG:{len(orphan)}" + (f" {orphan[:5]}" if orphan else ""))
    scripts = manifest.get("scripts") or {}
    print(f"剧情脚本:{len(scripts)} 条,文件缺失/空 {len(script_missing)}"
          + (f" {script_missing[:3]}" if script_missing else ""))
    print(f"磁盘孤儿脚本:{len(script_orphan)}" + (f" {script_orphan[:3]}" if script_orphan else ""))
    print(f"失败记录:{len(manifest.get('failures', []))},引用型:{len(manifest.get('references', []))}")
    ok = not (real_missing or extra or file_missing or orphan or script_missing
              or script_orphan or manifest.get("failures"))
    print("结论:" + ("一致 ✓" if ok else "不一致 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
