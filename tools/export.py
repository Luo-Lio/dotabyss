# -*- coding: utf-8 -*-
"""CLI 入口:扫描本地 bundle 缓存 → 导出 CG/动态素材 + 剧情索引 → 写 manifest.json。

用法:
    python -m tools.export                # 导出全部已缓存资源(已存在的文件跳过)
    python -m tools.export --inventory    # 只统计缓存里各类资源的数量
    python -m tools.export --force        # 覆盖已有产物
    python -m tools.export --only charastand,cutin
    python -m tools.export --dynamic-limit 3   # 只导出 3 个 Live2D/Spine 模型(调试)

除图像外还会:
- 用 master data 建剧情索引(按角色聚合、数量随数据走,不写死);
- 导出动态素材:Live2D(moc3 + motion3.json + 纹理)与 Spine(skel/atlas/png)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from . import dynamic, extract, paths, scenario, story
from .catalog import BundleRecord, parse_catalog, pick_latest_catalog
from .masterdata import MasterData, load_master_data

KINDS = ("charastand", "cutin", "bg", "story", "icon", "emo")
KIND_ORDER = {k: i for i, k in enumerate(KINDS)}


def exists_exact(path: Path) -> bool:
    """大小写敏感的文件存在性判断。

    Windows 文件系统不区分大小写,``Path.is_file()`` 会把 ``emo/angeR.png``
    当成存在的 ``emo/anger.png``;清理陈旧条目时必须按名字精确比较。

    Args:
        path: 待检查的文件路径。

    Returns:
        bool: 同名文件(大小写完全一致)是否存在。
    """
    parent = path.parent
    if not parent.is_dir():
        return False
    try:
        return path.name in {x.name for x in parent.iterdir()}
    except OSError:
        return False


def classify(record: BundleRecord) -> str | None:
    """把一个 bundle 记录分类到 CG 类别;不支持的返回 None。

    Args:
        record: catalog 记录。

    Returns:
        类别名(charastand/cutin/bg/story/icon)或 None。
    """
    hint = record.asset_hint.lower()
    group = record.group.lower()
    # 立绘:必须是 r18-only-charastand 这类真实角色预制体,排除 general-ui 下的表情特效预制体
    if re.search(r"charastand[0-9]+[a-z]?\.prefab", hint) and "charastand" in group:
        return "charastand"
    # 情绪符号(sdemo_anger 这类单图标预制体);排除 prefabs_sdemo_daily 之类的 UI 大杂烩
    if re.search(r"variantsdemotion_sdemo_[a-z0-9_]+\.prefab", hint) and "prefabs_sdemo" not in hint:
        return "emo"
    if "characutin" in hint or "cutin" in hint:
        return "cutin"
    if "bg-novel" in group or "bg-novel" in hint:
        return "bg"
    if "story-s" in group or "story-s" in hint:
        return "story"
    if "icon" in group:
        return "icon"
    return None


def scan_cache(cache_dir: Path, by_cdn: dict[str, BundleRecord]) -> tuple[list[tuple[BundleRecord, Path]], Counter]:
    """扫描缓存目录,返回 (记录, __data 路径) 列表与统计。

    Args:
        cache_dir: ``Caches`` 目录。
        by_cdn: cdn 目录名 → 记录。

    Returns:
        (命中列表, 统计计数):统计含 ``cache_dirs``/``hit``/``miss``/``md5_mismatch``。
    """
    stats: Counter = Counter()
    hits: list[tuple[BundleRecord, Path]] = []
    for entry in sorted(cache_dir.iterdir()):
        if not entry.is_dir() or len(entry.name) != 32:
            continue
        stats["cache_dirs"] += 1
        record = by_cdn.get(entry.name)
        if record is None:
            stats["miss"] += 1
            continue
        data = next((p / "__data" for p in entry.iterdir() if (p / "__data").is_file()), None)
        if data is None:
            stats["empty"] += 1
            continue
        # 内层目录名即内容 md5,应与 catalog 记录一致
        if data.parent.name != record.md5_hex:
            stats["md5_mismatch"] += 1
        stats["hit"] += 1
        hits.append((record, data))
    return hits, stats


def build_inventory(records: list[BundleRecord], hits: list[tuple[BundleRecord, Path]], stats: Counter) -> None:
    """打印缓存清单(各类别已缓存 / 全量)。"""
    total_by_kind: Counter = Counter()
    for r in records:
        k = classify(r)
        if k:
            total_by_kind[k] += 1
    got_by_kind: Counter = Counter()
    got_by_group: dict[str, Counter] = defaultdict(Counter)
    for r, _p in hits:
        k = classify(r)
        if k:
            got_by_kind[k] += 1
            got_by_group[k][r.group] += 1
    print(f"catalog 记录 {len(records)} 条;缓存目录 {stats['cache_dirs']} 个,"
          f"命中 {stats['hit']},未命中 {stats['miss']},空目录 {stats['empty']},md5 不符 {stats['md5_mismatch']}")
    print("\n类别            已缓存 / 全量")
    for k in KINDS:
        print(f"  {k:12s} {got_by_kind.get(k, 0):6d} / {total_by_kind.get(k, 0)}")
    print("\n分组明细:")
    for k in KINDS:
        for g, c in got_by_group.get(k, Counter()).most_common():
            print(f"  [{k:10s}] {c:5d}  {g}")


def apply_names(item: dict, master: MasterData, kind: str) -> None:
    """给导出的条目补角色/皮肤名称。"""
    art_id = item.get("art_id", "")
    info = None
    if kind in ("charastand", "cutin", "icon"):
        info = master.skin_by_art(art_id)
    elif kind == "bg":
        info = master.skin_by_bg(art_id)
    if info:
        title, profile = master.profile(info.character_id)
        item.update(
            character=info.character_name,
            character_id=info.character_id,
            skin=info.skin_name,
            profile_title=title,
            profile=profile,
            bg_id=info.bg_id,
        )


def main(argv: list[str] | None = None) -> int:
    """入口。

    Args:
        argv: 命令行参数(默认取 sys.argv)。

    Returns:
        int: 进程退出码。
    """
    ap = argparse.ArgumentParser(description="ドットアビスX CG 导出")
    ap.add_argument("--game-dir", type=Path, help="游戏安装目录")
    ap.add_argument("--out", type=Path, help="输出目录(默认 <仓库>/output)")
    ap.add_argument("--catalog", type=Path, help="显式指定 catalog .bin")
    ap.add_argument("--inventory", action="store_true", help="只统计,不导出")
    ap.add_argument("--force", action="store_true", help="覆盖已有产物")
    ap.add_argument("--only", default="", help="只导出指定类别,逗号分隔")
    ap.add_argument("--limit", type=int, default=0, help="每类最多导出多少个(调试用)")
    ap.add_argument("--dynamic-limit", type=int, default=0, help="动态素材最多导出多少个模型(调试用,0=不限)")
    ap.add_argument("--skip-dynamic", action="store_true", help="跳过动态素材导出")
    ap.add_argument("--skip-scripts", action="store_true", help="跳过剧情脚本导出")
    args = ap.parse_args(argv)

    try:
        p = paths.discover(args.game_dir, args.out)
    except FileNotFoundError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2

    catalog_path = pick_latest_catalog(p.catalog_dir, args.catalog)
    records = parse_catalog(catalog_path)
    by_cdn = {r.cdn: r for r in records}
    hits, stats = scan_cache(p.cache_dir, by_cdn)
    print(f"catalog: {catalog_path.name}")
    build_inventory(records, hits, stats)
    if args.inventory:
        return 0

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    master = load_master_data(p.download_cache_dir)

    manifest_path = p.out_dir / "manifest.json"
    items: dict[str, dict] = {}
    old_refs: dict[str, dict] = {}
    old_stories: dict = {}
    old_dynamic: dict = {}
    old_scripts: dict = {}
    if manifest_path.is_file():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        items = {f"{it['kind']}:{it['art_id']}": it for it in old.get("items", [])}
        old_refs = {f"{r['kind']}:{r['art_id']}": r for r in old.get("references", [])}
        old_stories = old.get("stories") or {}
        old_dynamic = old.get("dynamic") or {}
        old_scripts = old.get("scripts") or {}

    counters = Counter()
    failures: list[dict] = []
    per_kind_limit: Counter = Counter()
    seen_keys: set[str] = set()
    for record, data in hits:
        kind = classify(record)
        if kind is None or (only and kind not in only):
            continue
        if args.limit and per_kind_limit[kind] >= args.limit:
            continue
        art_id = extract.id_for(record, kind)
        key = f"{kind}:{art_id}"
        seen_keys.add(key)
        old_files = items.get(key, {}).get("files") or []
        if key in items and not args.force and old_files and (p.out_dir / old_files[0]).is_file():
            counters["skipped"] += 1
            continue
        per_kind_limit[kind] += 1
        try:
            if kind == "charastand":
                result = extract.export_charastand(data, p.out_dir, art_id, record)
            elif kind == "emo":
                result = extract.export_emo(data, p.out_dir, art_id, record)
            else:
                result = extract.export_simple(data, p.out_dir, kind, art_id, record)
        except Exception as exc:  # noqa: BLE001 - 单个 bundle 失败不中断整批
            failures.append({"bundle": record.name, "error": repr(exc)})
            counters["failed"] += 1
            continue
        if not result.ok:
            # 引用型 bundle(只存 Addressables 引用,图像在别的 bundle 里)不算失败
            if "没找到可用图像" in result.error:
                old_refs[key] = {"kind": kind, "art_id": art_id, "bundle": record.name, "reason": result.error}
                counters["referenced"] += 1
            else:
                failures.append({"bundle": record.name, "error": result.error})
                counters["failed"] += 1
            continue
        old_refs.pop(key, None)
        item = {"kind": kind, "files": result.files, **result.meta}
        apply_names(item, master, kind)
        items[key] = item
        counters["exported"] += 1
        print(f"[{kind}] {art_id} -> {result.files[0]}")

    p.out_dir.mkdir(parents=True, exist_ok=True)

    # ── 清理已处理类别里的陈旧条目:本次扫描不再产出、且产物文件已不在磁盘上 ──
    # (典型来源:id 规则调整后残留的旧文件条目;文件还在的一律保留,缓存轮换不影响)
    prune_kinds = {k for k in KINDS if not only or k in only}
    for key in list(items):
        it = items[key]
        files = it.get("files") or []
        if it.get("kind") in prune_kinds and key not in seen_keys and files and not exists_exact(p.out_dir / files[0]):
            del items[key]
            counters["pruned"] += 1

    # ── 动态素材:Live2D(moc3 + 动作 + 纹理)与 Spine(skel/atlas/png) ──
    want_dynamic = not args.skip_dynamic and (not only or "dynamic" in only)
    if want_dynamic:
        exporter = dynamic.DynamicExporter(p.out_dir, force=args.force, limit=args.dynamic_limit)
        for record, data in hits:
            if dynamic.L2D_RE.search(record.asset_hint):
                exporter.feed_live2d(record, data)
            elif dynamic.SPINE_RE.search(record.asset_hint):
                exporter.feed_spine(record, data)
        dynamic_result = exporter.result()
        failures.extend(exporter.failures)
        counters["failed"] += len(exporter.failures)
        # 影片走 CRI 流式,本地只有 ~2.5KB 存根;如实统计,供图库提示
        movie_records = [r for r in records if "movie" in r.group.lower()]
        movie_local = sum(1 for r, d in hits if "movie" in r.group.lower() and d.stat().st_size > 100_000)
        dynamic_result["movies"] = {
            "total": len(movie_records),
            "local": movie_local,
            "note": "影片由 CRI 流式播放,本地缓存只有存根;离线观看需另行抓流或录屏",
        }
        counts = dynamic_result["counts"]
        print(f"\n动态素材:Live2D 模型 {counts['live2d_models']} 个(动作 {counts['live2d_motions']} 条,"
              f"带纹理 {counts['live2d_with_textures']}),Spine 模型 {counts['spine_models']} 个"
              f"(带纹理 {counts['spine_with_textures']}),影片本地 {movie_local}/{len(movie_records)}")
    else:
        dynamic_result = old_dynamic

    # ── 剧情索引(按角色聚合,数量随数据,不写死)──
    if not only or "stories" in only:
        story_index = story.build_story_index(master)
        # 已导出的剧情缩略图回填为封面
        char_by_story: dict[str, dict] = {}
        for entry in story_index["entries"]:
            thumb_key = entry.get("thumb") or ""
            item = items.get(f"story:{thumb_key}") if thumb_key else None
            entry["thumb_file"] = item["files"][0] if item else ""
            if entry.get("character"):
                char_by_story[entry["key"]] = entry
                # 剧情 key 末位是「段」(11=第一话前篇,12=后篇),用去掉末位的组键做等价关联
                char_by_story.setdefault(entry["key"][:-1], entry)
                if thumb_key:
                    char_by_story.setdefault(thumb_key.replace("story_s_", ""), entry)
        # 动态素材补上角色名(Live2D 模型按剧情 key 关联,允许前后篇差异)
        for model in dynamic_result.get("live2d", []):
            skey = model.get("story_key", "")
            linked = char_by_story.get(skey) or char_by_story.get(skey[:-1])
            if linked:
                model["character_id"] = linked["character_id"]
                model["character"] = linked["character"]
                model["title"] = linked["title"]
        print(f"剧情索引:{len(story_index['entries'])} 条,覆盖角色 {len(story_index['characters'])} 个,"
              f"动态关联 {sum(1 for m in dynamic_result.get('live2d', []) if m.get('character'))} 个模型")
    else:
        story_index = old_stories

    # ── 剧情脚本:编译成离线播放事件流(output/stories/<key>.js)──
    if not args.skip_scripts:
        metas = {e["key"]: e for e in (story_index or {}).get("entries", [])}
        known_art = {it["art_id"] for it in items.values() if it["kind"] == "charastand"}
        scripts = scenario.export_scripts(records, p.cache_dir, p.out_dir, metas=metas,
                                          known_art=known_art, force=args.force,
                                          old=old_scripts)
        by_series = Counter(v["series"] for v in scripts.values())
        beats = sum(v["beats"] for v in scripts.values())
        print(f"剧情脚本:{len(scripts)} 条(文本 {beats} 段),"
              f"系列 {dict(sorted(by_series.items()))},立绘素材 {len(known_art)} 张")
    else:
        scripts = old_scripts

    ordered = sorted(items.values(), key=lambda it: (KIND_ORDER.get(it["kind"], 9), it["art_id"]))
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "catalog": {"file": catalog_path.name, "records": len(records)},
        "cache_stats": dict(stats),
        "counts": dict(Counter(it["kind"] for it in ordered)),
        "items": ordered,
        "references": sorted(old_refs.values(), key=lambda r: (r["kind"], r["art_id"])),
        "failures": failures,
        "stories": story_index,
        "dynamic": dynamic_result,
        "scripts": scripts,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n导出 {counters['exported']} 个,跳过 {counters['skipped']} 个,"
          f"引用型 {counters['referenced']} 个,失败 {counters['failed']} 个")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
