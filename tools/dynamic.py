# -*- coding: utf-8 -*-
"""动态素材导出:Live2D 模型/动作 与 Spine 骨骼动画。

实测形态(均为 bundel 内对象结构):

**Live2D —— 剧情立绘演出**,按剧情一话一个模型实例::

    mainchara_<剧情key>_l2d_<模型id>_l2d_<模型id>.asset          → MonoBehaviour._bytes = 标准 moc3 模型字节
    mainchara_<剧情key>_l2d_<模型id>_l2d_<模型id>.prefab         → 预制体(纹理 Texture2D 在此 bundle 内)
    mainchara_<剧情key>_l2d_<模型id>_animations_<动作>.fade.asset → 演出动作(ParameterIds + AnimationCurve 关键帧)
    mainchara_<剧情key>_l2d_<模型id>_addanimations_<动作>.fade.asset → 追加动作(眨眼/口型/表情)

动作数据实测字段:``ParameterIds[]`` 与 ``ParameterCurves[]``(每参数一条 Unity AnimationCurve),
可无损转成 Cubism 标准 ``motion3.json``(线性段)。导出后配官方 Cubism 运行时即可离线播放。

**Spine —— 剧情 Boss 演出**,三件套可完整还原::

    spine/boss/<boss>/spinesd.skel        → TextAsset,二进制骨架(实测版本 4.1.23)
    spine/boss/<boss>/spinesd.atlas.txt   → TextAsset,图集描述(文本)
    spine/boss/<boss>/spinesd_atlas.asset → Texture2D,皮肤图集

导出统一成「一个模型一个目录 + 标准格式文件」,便于后续用官方运行时离线播放。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import UnityPy

from .catalog import BundleRecord

# Live2D:mainchara_<剧情key>_l2d_<模型id>_
L2D_RE = re.compile(r"mainchara_([a-z0-9_]+?)_l2d_(\d+)_", re.IGNORECASE)
L2D_MOTION_RE = re.compile(r"_l2d_\d+_(?P<group>add)?animations_(?P<name>.+?)\.fade\.asset$", re.IGNORECASE)
# Spine:spine_boss_<bossid>_
SPINE_RE = re.compile(r"spine_boss_([a-z0-9]+)_", re.IGNORECASE)

MOC3_MAGIC = b"MOC3"

# catalog 的 asset_hint 末尾带 「_<md5>.bundle」,比较后缀前必须先剥掉
_BUNDLE_SUFFIX_RE = re.compile(r"_[0-9a-f]{32}\.bundle$", re.IGNORECASE)


def clean_hint(record: BundleRecord) -> str:
    """取资产名主干(小写、去掉 md5 后缀),用于后缀判断。

    Args:
        record: catalog 记录。

    Returns:
        str: 例如 ``r18-only_novel_mainchara_hmr_10010100012_l2d_10010100012_l2d_10010100012.asset``。
    """
    return _BUNDLE_SUFFIX_RE.sub("", record.asset_hint).lower()


def _write_if_needed(path: Path, payload: bytes, force: bool) -> bool:
    """写文件(已存在且非 force 时跳过),返回是否真的写入。"""
    if path.is_file() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return True


def _animation_curve_points(curve: dict) -> list[float]:
    """把 Unity AnimationCurve 转成 Cubism 线性段序列 [t0,v0,t1,v1,...]。

    关键帧的 inSlope/outSlope 不参与转换:统一按线性插值生成,
    播放观感与游戏内 Bezier 略有差异(数据本身不丢,曲线可在 JSON 里回读)。

    Args:
        curve: typetree 里的 m_Curve 字段(含 m_Curve 关键帧数组)。

    Returns:
        list[float]: 交替的 时间/数值 序列;关键帧不足 2 个时返回空表。
    """
    keys = curve.get("m_Curve") or []
    if len(keys) < 2:
        return []
    out: list[float] = []
    for kf in keys:
        out.append(round(float(kf.get("time", 0.0)), 6))
        out.append(round(float(kf.get("value", 0.0)), 6))
    return out


def fade_to_motion3(typetree: dict, loop: bool) -> dict:
    """把 ``.fade.asset`` 的类型树转成 Cubism ``motion3.json`` 结构。

    Args:
        typetree: fade 资产的类型树(ParameterIds / ParameterCurves / MotionLength ...)。
        loop: 是否循环动作(文件名以 ``_loop`` 结尾)。

    Returns:
        dict: motion3.json 结构;无有效曲线时 Curves 为空表。
    """
    ids = typetree.get("ParameterIds") or []
    curves = typetree.get("ParameterCurves") or []
    out_curves: list[dict] = []
    total_point = total_segment = 0
    for i, pid in enumerate(ids):
        if i >= len(curves) or not isinstance(curves[i], dict):
            continue
        points = _animation_curve_points(curves[i])
        if len(points) < 4:
            continue
        curve = {"Target": "Parameter", "Id": str(pid), "Segments": points}
        fade_in = float(typetree.get("FadeInTime", -1.0))
        fade_out = float(typetree.get("FadeOutTime", -1.0))
        if fade_in >= 0:
            curve["FadeInTime"] = fade_in
        if fade_out >= 0:
            curve["FadeOutTime"] = fade_out
        out_curves.append(curve)
        n = len(points) // 2
        total_point += n
        total_segment += max(0, n - 1)
    duration = float(typetree.get("MotionLength", 0.0)) or (
        max((c["Segments"][-2] for c in out_curves), default=0.0))
    return {
        "Version": 3,
        "Meta": {
            "Duration": round(duration, 6),
            "Fps": 30.0,
            "Loop": bool(loop),
            "AreBeziersRestricted": False,
            "CurveCount": len(out_curves),
            "TotalSegmentCount": total_segment,
            "TotalPointCount": total_point,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": out_curves,
        "UserData": [],
    }


def _read_objects(data: Path) -> list:
    """打开 bundle 并返回对象列表。"""
    return list(UnityPy.load(str(data)).objects)


class DynamicExporter:
    """把已缓存 bundle 里的动态素材导出为通用格式,并维护 manifest 条目。"""

    def __init__(self, out_dir: Path, force: bool = False, limit: int = 0) -> None:
        """初始化。

        Args:
            out_dir: 输出根目录。
            force: 覆盖已存在的产物。
            limit: 每个类别最多导出多少个模型(0 = 不限,调试用)。
        """
        self.out_dir = out_dir
        self.force = force
        self.limit = limit
        self.live2d: dict[str, dict] = {}
        self.spine: dict[str, dict] = {}
        self.counters: dict[str, int] = {"live2d_files": 0, "spine_files": 0, "skipped": 0}
        self.failures: list[dict] = []

    # ── Live2D ────────────────────────────────────────────────────────────
    def feed_live2d(self, record: BundleRecord, data: Path) -> None:
        """处理一个 Live2D 相关 bundle(moc3 / 动作 / 纹理)。"""
        hint = clean_hint(record)
        m = L2D_RE.search(hint)
        if not m:
            return
        story_key, model_id = m.group(1).lower(), m.group(2)
        if model_id not in self.live2d:
            if self.limit and len(self.live2d) >= self.limit:
                return
            self.live2d[model_id] = {
                "kind": "live2d", "model_id": model_id, "story_key": story_key,
                "files": [], "moc3_bytes": 0, "motions": [], "textures": 0,
                "bundle": record.name,
            }
        entry = self.live2d[model_id]
        model_dir = self.out_dir / "live2d" / model_id
        try:
            if hint.endswith(f"_l2d_{model_id}.asset"):
                self._live2d_model(data, entry, model_dir)
            elif hint.endswith(".fade.asset"):
                self._live2d_motion(data, entry, model_dir, hint)
            elif hint.endswith(f"_l2d_{model_id}.prefab"):
                self._live2d_textures(data, entry, model_dir)
        except Exception as exc:  # noqa: BLE001 - 单个资产失败不影响整批
            self.failures.append({"bundle": record.name, "error": repr(exc)})

    def _live2d_model(self, data: Path, entry: dict, model_dir: Path) -> None:
        """导出 moc3 模型字节。"""
        for obj in _read_objects(data):
            if obj.type.name != "MonoBehaviour":
                continue
            tt = obj.read_typetree()
            raw = tt.get("_bytes")
            if not raw:
                continue
            blob = bytes(raw) if isinstance(raw, (bytes, bytearray)) else bytes(bytearray(raw))
            if blob[:4] != MOC3_MAGIC:
                entry.setdefault("warnings", []).append("moc3 魔数不符,已跳过")
                return
            path = model_dir / f"{entry['model_id']}.moc3"
            _write_if_needed(path, blob, self.force)
            entry["moc3_bytes"] = len(blob)
            rel = str(path.relative_to(self.out_dir)).replace("\\", "/")
            if rel not in entry["files"]:
                entry["files"].append(rel)
            entry["name"] = tt.get("m_Name", "")
            return

    def _live2d_motion(self, data: Path, entry: dict, model_dir: Path, hint: str) -> None:
        """把一条 fade 动作转成 motion3.json。"""
        m = L2D_MOTION_RE.search(hint)
        if not m:
            return
        name = f"{'add' if m.group('group') else ''}{m.group('name')}".replace("_loop", "_loop")
        for obj in _read_objects(data):
            if obj.type.name != "MonoBehaviour":
                continue
            tt = obj.read_typetree()
            payload = fade_to_motion3(tt, loop=hint.endswith("_loop.fade.asset"))
            if not payload["Curves"]:
                continue
            path = model_dir / "motions" / f"{name}.motion3.json"
            _write_if_needed(path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), self.force)
            rel = str(path.relative_to(self.out_dir)).replace("\\", "/")
            if rel not in entry["files"]:
                entry["files"].append(rel)
            entry["motions"].append({
                "name": name,
                "file": rel,
                "duration": payload["Meta"]["Duration"],
                "curves": payload["Meta"]["CurveCount"],
                "loop": payload["Meta"]["Loop"],
                "source": str(tt.get("MotionName", ""))[:160],
            })
            return

    def _live2d_textures(self, data: Path, entry: dict, model_dir: Path) -> None:
        """导出预制体内的纹理(编号即 Cubism 绘制序,不可重排;另记录最大一张作封面)。"""
        textures = []
        for obj in _read_objects(data):
            if obj.type.name != "Texture2D":
                continue
            d = obj.read()
            textures.append((d.m_Name, d.image.convert("RGBA")))
        textures.sort(key=lambda x: x[0])
        poster: tuple[str, int] = ("", 0)
        for i, (_name, image) in enumerate(textures):
            path = model_dir / f"texture_{i:02d}.png"
            if path.is_file() and not self.force:
                pass
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                image.save(path)
            rel = str(path.relative_to(self.out_dir)).replace("\\", "/")
            if rel not in entry["files"]:
                entry["files"].append(rel)
            area = image.size[0] * image.size[1]
            if area > poster[1]:
                poster = (rel, area)
        if textures:
            entry["textures"] = len(textures)
            entry["poster"] = poster[0]
        self._write_model3(entry, model_dir)

    def _write_model3(self, entry: dict, model_dir: Path) -> None:
        """生成最小 model3.json(纹理与动作引用),供 Cubism 运行时加载。"""
        textures = [f"texture_{i:02d}.png" for i in range(entry.get("textures", 0))]
        motions = [{"File": f"motions/{m['name']}.motion3.json", "FadeInTime": -1.0, "FadeOutTime": -1.0}
                   for m in entry["motions"]]
        if not textures and not motions:
            return
        payload = {
            "Version": 3,
            "FileReferences": {
                "Moc": f"{entry['model_id']}.moc3",
                "Textures": textures,
                "Motions": {"": motions},
            },
        }
        path = model_dir / "model3.json"
        _write_if_needed(path, json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"), self.force)
        rel = str(path.relative_to(self.out_dir)).replace("\\", "/")
        if rel not in entry["files"]:
            entry["files"].append(rel)

    # ── Spine ─────────────────────────────────────────────────────────────
    def feed_spine(self, record: BundleRecord, data: Path) -> None:
        """处理一个 Spine 相关 bundle(骨架 / 图集描述 / 纹理)。"""
        hint = clean_hint(record)
        m = SPINE_RE.search(hint)
        if not m:
            return
        boss_id = m.group(1).lower()
        if boss_id not in self.spine:
            if self.limit and len(self.spine) >= self.limit:
                return
            self.spine[boss_id] = {
                "kind": "spine", "boss_id": boss_id,
                "files": [], "skel_bytes": 0, "atlas_bytes": 0, "textures": 0,
                "bundle": record.name,
            }
        entry = self.spine[boss_id]
        boss_dir = self.out_dir / "spine" / boss_id
        try:
            if hint.endswith("_skeletondata.asset"):
                # 骨架是 bundle 内的 TextAsset(SpineSD.skel,二进制)
                self._spine_text(data, entry, boss_dir, f"{boss_id}.skel", "skel_bytes")
            elif hint.endswith(".atlas.txt"):
                self._spine_atlas(data, entry, boss_dir, boss_id)
            elif hint.endswith("_atlas.asset"):
                self._spine_textures(data, entry, boss_dir, boss_id)
        except Exception as exc:  # noqa: BLE001
            self.failures.append({"bundle": record.name, "error": repr(exc)})

    def _spine_text(self, data: Path, entry: dict, boss_dir: Path, filename: str, size_key: str) -> None:
        """导出 Spine 的 TextAsset(骨架二进制 / 图集文本)。"""
        for obj in _read_objects(data):
            if obj.type.name != "TextAsset":
                continue
            d = obj.read()
            raw = d.m_Script
            blob = bytes(raw) if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8", "surrogateescape")
            path = boss_dir / filename
            _write_if_needed(path, blob, self.force)
            entry[size_key] = len(blob)
            rel = str(path.relative_to(self.out_dir)).replace("\\", "/")
            if rel not in entry["files"]:
                entry["files"].append(rel)
            return

    def _spine_atlas(self, data: Path, entry: dict, boss_dir: Path, boss_id: str) -> None:
        """导出图集文本,并把首页的图像文件名改写成导出的 PNG 名。"""
        for obj in _read_objects(data):
            if obj.type.name != "TextAsset":
                continue
            d = obj.read()
            raw = d.m_Script
            text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            lines = text.splitlines()
            if lines:
                lines[0] = f"{boss_id}.png"
            blob = ("\n".join(lines) + "\n").encode("utf-8")
            path = boss_dir / f"{boss_id}.atlas"
            _write_if_needed(path, blob, self.force)
            entry["atlas_bytes"] = len(blob)
            rel = str(path.relative_to(self.out_dir)).replace("\\", "/")
            if rel not in entry["files"]:
                entry["files"].append(rel)
            return

    def _spine_textures(self, data: Path, entry: dict, boss_dir: Path, boss_id: str) -> None:
        """导出皮肤图集纹理(命名为 <boss>.png,与改写后的 atlas 对应)。"""
        images = []
        for obj in _read_objects(data):
            if obj.type.name != "Texture2D":
                continue
            d = obj.read()
            images.append((d.m_Name, d.image.convert("RGBA")))
        images.sort(key=lambda x: x[0])
        for i, (name, image) in enumerate(images):
            fname = f"{boss_id}.png" if i == 0 else f"{boss_id}_{i}.png"
            path = boss_dir / fname
            if not path.is_file() or self.force:
                path.parent.mkdir(parents=True, exist_ok=True)
                image.save(path)
            rel = str(path.relative_to(self.out_dir)).replace("\\", "/")
            if rel not in entry["files"]:
                entry["files"].append(rel)
            entry.setdefault("texture_names", []).append(name)
        entry["textures"] = len(images)

    # ── 汇总 ──────────────────────────────────────────────────────────────
    def result(self) -> dict:
        """导出汇总(按模型 id 排序,便于 diff 与展示)。"""
        live2d = sorted(self.live2d.values(), key=lambda e: e["model_id"])
        spine = sorted(self.spine.values(), key=lambda e: e["boss_id"])
        for e in live2d:
            e["motions"].sort(key=lambda m: m["name"])
            e["files"].sort()
        for e in spine:
            e["files"].sort()
        return {
            "live2d": live2d,
            "spine": spine,
            "counts": {
                "live2d_models": len(live2d),
                "live2d_motions": sum(len(e["motions"]) for e in live2d),
                "live2d_with_textures": sum(1 for e in live2d if e.get("textures")),
                "spine_models": len(spine),
                "spine_with_textures": sum(1 for e in spine if e.get("textures")),
            },
        }
