# -*- coding: utf-8 -*-
"""从本地 bundle 缓存导出各类 CG。

各类资源的形态与处理方式(均为实测):
- 立绘 ``charastand``:UI 预制体,由 Body 整身图 + FaceContent 下的表情叠加图组成,
  按 :mod:`tools.uilayout` 解出的布局合成整图,同时把各表情单独导出。
- cut-in / 背景 ``cutin``/``bg``:单张 Texture2D 即整图。
- 剧情缩略图 ``story``、图标 ``icon``:Sprite(可能来自共享图集,按 Sprite 裁剪区域导出)。

本模块只做「一个 bundle → 若干 PNG + 元数据」,不做扫描与分类。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import UnityPy
from PIL import Image

from .catalog import BundleRecord
from .uilayout import RectTransform, RectTransformTree

# 立绘预制体里的关键节点名(实测)
BODY_NODE = "Body"
FACE_ROOT_NODE = "FaceContent"
# 像素剧情(dot novel)角色预制体:根节点名 = 该前缀 + 角色 id,表情挂在 Face 下(实测)
DOT_BODY_PREFIX = "DotNovelCharaIcon"
DOT_FACE_ROOT_NODE = "Face"

_SUFFIX_RE = re.compile(r"_[0-9a-f]{32}\.bundle$")


@dataclass
class ExportResult:
    """单个 bundle 的导出结果。"""

    ok: bool
    files: list[str] = field(default_factory=list)
    """相对输出目录的文件路径。"""
    meta: dict = field(default_factory=dict)
    """附加元数据(尺寸、图层等)。"""
    error: str = ""


def asset_stem(record: BundleRecord) -> str:
    """取 bundle 内资产的文件名主干(不含扩展名与 md5 后缀)。"""
    path = _SUFFIX_RE.sub("", record.asset_hint)
    return Path(path).stem


def asset_rel_path(record: BundleRecord) -> str:
    """取资产相对主干的相对路径(去掉组前缀与扩展名)。

    组前缀在 catalog 里用连字符(``general-icon-ability``),在资产路径里用下划线,
    去掉后可得到资产自身的名字,例如 ``m_ability_attack_01``、``charaicon100101000m``。

    Args:
        record: bundle 记录。

    Returns:
        str: 相对资产名。
    """
    path = _SUFFIX_RE.sub("", record.asset_hint)
    group_path = record.group.replace("-", "_")
    # 资产路径里的组前缀保留了连字符(如 r18-only_icon_story_s),比较前统一成下划线
    normalized = path.replace("-", "_")
    if group_path and normalized.startswith(group_path + "_"):
        path = normalized[len(group_path) + 1:]
    return Path(path).stem


# 各类别资源 id 在相对资产名里的提取正则(实测:立绘/cut-in 名里带 9 位数字 + 大小写后缀)
ID_RE = {
    "charastand": re.compile(r"charastand([0-9]+[a-z]?)", re.IGNORECASE),
    "dotchara": re.compile(r"dotnovelcharaicon([0-9]+[a-z]?)", re.IGNORECASE),
    "emo": re.compile(r"sdemo_([a-z0-9_]+)$", re.IGNORECASE),
    "cutin": re.compile(r"(?:cutin)?([0-9]{6,}[a-z]?)(?:_cutin)?$", re.IGNORECASE),
}


def id_for(record: BundleRecord, kind: str) -> str:
    """按类别取资源的对外 id(用作文件名与 manifest 主键)。

    Args:
        record: bundle 记录。
        kind: 类别名。

    Returns:
        str: 立绘/cut-in 归一化为 ``100101000G`` 形式;其余用相对资产名。
    """
    rel = asset_rel_path(record)
    regex = ID_RE.get(kind)
    if regex is None:
        return rel
    m = regex.search(rel)
    if not m:
        return rel
    raw = m.group(1)
    # 角色类 id 的字母后缀统一成大写(100101000g → 100101000G);符号名按原样小写
    if kind in ("charastand", "dotchara", "cutin") and len(raw) >= 2 and raw[-1].isalpha():
        return raw[:-1] + raw[-1].upper()
    return raw


class _UiBundle:
    """一个 bundle 的 UI 视图:游戏对象名、Image 组件与 RectTransform 层级。"""

    def __init__(self, bundle_path: Path) -> None:
        """解析 bundle。

        Args:
            bundle_path: ``__data`` 文件路径。
        """
        self.env = UnityPy.load(str(bundle_path))
        self.objects = list(self.env.objects)
        self.go_name: dict[int, str] = {}
        self.go_active: dict[int, bool] = {}
        self.sprite_objects: dict[int, object] = {}
        self.rt_nodes: dict[int, RectTransform] = {}
        # (go 名, 是否激活, sprite path_id, rt path_id)
        self.images: list[tuple[str, bool, int, int]] = []
        self._parse()

    def _parse(self) -> None:
        """遍历对象,收集 GameObject / Sprite / RectTransform / Image 组件。"""
        rt_by_go: dict[int, int] = {}
        for obj in self.objects:
            t = obj.type.name
            if t == "GameObject":
                d = obj.read()
                self.go_name[obj.path_id] = d.m_Name
                self.go_active[obj.path_id] = bool(d.m_IsActive)
            elif t == "Sprite":
                self.sprite_objects[obj.path_id] = obj
            elif t == "RectTransform":
                tt = obj.read_typetree()
                f = tt.get("m_Father") or {}
                node = RectTransform(
                    path_id=obj.path_id,
                    game_object=tt["m_GameObject"]["m_PathID"],
                    father=f.get("m_PathID"),
                    anchored=(tt["m_AnchoredPosition"]["x"], tt["m_AnchoredPosition"]["y"]),
                    size_delta=(tt["m_SizeDelta"]["x"], tt["m_SizeDelta"]["y"]),
                    pivot=(tt["m_Pivot"]["x"], tt["m_Pivot"]["y"]),
                    scale=(tt["m_LocalScale"]["x"], tt["m_LocalScale"]["y"]),
                    anchor_min=(tt["m_AnchorMin"]["x"], tt["m_AnchorMin"]["y"]),
                    anchor_max=(tt["m_AnchorMax"]["x"], tt["m_AnchorMax"]["y"]),
                )
                self.rt_nodes[obj.path_id] = node
                rt_by_go[node.game_object] = obj.path_id
        for obj in self.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                tt = obj.read_typetree()
            except Exception:  # noqa: BLE001 - 非 UI 组件读不出类型树,跳过
                continue
            if not {"m_Sprite", "m_GameObject"} <= set(tt):
                continue
            sprite = tt["m_Sprite"]["m_PathID"]
            if not sprite:
                continue
            go_id = tt["m_GameObject"]["m_PathID"]
            rt_id = rt_by_go.get(go_id)
            if rt_id is None:
                continue
            self.images.append((self.go_name.get(go_id, ""), self.go_active.get(go_id, False), sprite, rt_id))

    def sprite_image(self, sprite_path_id: int, untrim: bool = False) -> Image.Image:
        """读出 Sprite 的位图(按 Sprite 矩形裁剪,已处理图集)。

        Args:
            sprite_path_id: Sprite 的 path_id。
            untrim: 是否把图集紧致打包裁掉的透明边补回(还原成 ``m_Rect`` 设计尺寸)。
                立绘表情层这类要按预制体坐标叠加的图必须为 True,否则裁剪过的图
                会被拉伸到设计框上,导致五官错位。

        Returns:
            PIL 图像(已处理图集裁剪)。
        """
        obj = self.sprite_objects[sprite_path_id]
        img = obj.read().image.convert("RGBA")
        if not untrim:
            return img
        return untrim_image(img, obj)

    def sprite_px(self, sprite_path_id: int) -> tuple[int, int]:
        """读出 Sprite 的像素尺寸。"""
        d = self.sprite_objects[sprite_path_id].read()
        return int(d.m_Rect.width), int(d.m_Rect.height)

    def rt_of_go(self, name: str) -> int | None:
        """按游戏对象名找 RectTransform。"""
        for pid, node in self.rt_nodes.items():
            if self.go_name.get(node.game_object) == name:
                return pid
        return None


def untrim_image(img: Image.Image, sprite_obj) -> Image.Image:
    """把被图集紧致打包裁掉的透明边补回,还原成 ``m_Rect`` 的设计尺寸。

    Unity 图集打包会裁掉 sprite 四周的全透明像素,UnityPy 读出的 ``image``
    因此比 ``m_Rect`` 小;``m_RD.textureRectOffset`` 记录了裁剪边距(y 轴向上)。
    叠加类图层(立绘表情)必须先还原到设计尺寸再缩放,否则内容会被拉伸错位。

    Args:
        img: UnityPy 读出的裁剪后位图。
        sprite_obj: UnityPy 的 Sprite 对象(用于读类型树)。

    Returns:
        还原到 ``m_Rect`` 尺寸的位图;尺寸或偏移不自洽时原样返回。
    """
    tt = sprite_obj.read_typetree()
    rect = tt.get("m_Rect") or {}
    w = int(round(rect.get("width", img.width)))
    h = int(round(rect.get("height", img.height)))
    if (w, h) == img.size:
        return img
    off = (tt.get("m_RD") or {}).get("textureRectOffset") or {}
    x = int(round(off.get("x", 0.0)))
    # textureRectOffset 的 y 轴向上,换算成位图坐标(原点在左上)
    y = h - int(round(off.get("y", 0.0))) - img.height
    if x < 0 or y < 0 or x + img.width > w or y + img.height > h:
        return img  # 偏移超出设计框,数据不自洽时不猜
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.alpha_composite(img, (x, y))
    return canvas


def export_charastand(bundle_path: Path, out_dir: Path, art_id: str, record: BundleRecord,
                      *, body_node: str = BODY_NODE, face_root_node: str = FACE_ROOT_NODE,
                      body_prefix: str = "", kind: str = "charastand") -> ExportResult:
    """导出立绘/像素剧情角色:合成整图 + 各表情单独导出。

    立绘(``charastand``)与像素剧情角色(``dotchara``,DotNovelCharaIcon)预制体
    结构一致,只有节点名与图集大小不同,因此共用本函数。

    Args:
        bundle_path: bundle 的 ``__data`` 路径。
        out_dir: 输出根目录。
        art_id: 角色 id(如 ``100101000G``),用作文件名。
        record: catalog 记录(用于元数据)。
        body_node: 整身图所在节点名(精确匹配)。
        face_root_node: 表情层的父节点名。
        body_prefix: 整身图节点名的前缀(精确名不存在时按前缀取,用于 dotchara)。
        kind: 输出类别目录名(``charastand``/``dotchara``)。

    Returns:
        ExportResult: 文件清单与元数据(尺寸、表情列表、激活表情)。
    """
    ui = _UiBundle(bundle_path)
    tree = RectTransformTree(ui.rt_nodes)

    body = next((x for x in ui.images if x[0] == body_node), None)
    if body is None and body_prefix:
        # dotchara 的整身节点名带角色 id(如 DotNovelCharaIcon101801000G),按前缀取
        body = next((x for x in ui.images if x[0].startswith(body_prefix)), None)
    if body is None:
        return ExportResult(ok=False, error="预制体中找不到 Body 图层")
    _name, _active, body_sprite, body_rt = body
    body_img = ui.sprite_image(body_sprite, untrim=True)
    body_px = ui.sprite_px(body_sprite)
    body_center, body_size = tree.drawn_rect(body_rt)
    root_per_px = body_size[0] / body_px[0]  # 立绘像素 → 根单位

    face_root_rt = ui.rt_of_go(face_root_node)
    # 表情层是 FaceContent 的后代(直接子节点是各表情,Closed 之类挂在表情之下)
    faces = [x for x in ui.images if face_root_rt is not None and tree.is_descendant(x[3], face_root_rt)]

    canvas = Image.new("RGBA", body_img.size, (0, 0, 0, 0))
    canvas.alpha_composite(body_img, (0, 0))

    face_dir = out_dir / kind / "faces" / art_id
    face_meta: dict[str, dict] = {}
    active_face = ""
    for name, active, sprite, rt_id in faces:
        center, size = tree.drawn_rect(rt_id)
        face_img = ui.sprite_image(sprite, untrim=True)
        # 换算到立绘像素坐标:位置取中心差,尺寸按根单位比例折算
        dx = (center[0] - body_center[0]) / root_per_px
        dy = (center[1] - body_center[1]) / root_per_px
        w = max(1, round(size[0] / root_per_px))
        h = max(1, round(size[1] / root_per_px))
        resized = face_img.resize((w, h), Image.LANCZOS)
        face_dir.mkdir(parents=True, exist_ok=True)
        face_path = face_dir / f"{name}.png"
        resized.save(face_path)
        # Unity 的 Y 轴向上,位图 Y 轴向下
        cx = body_px[0] / 2 + dx
        cy = body_px[1] / 2 - dy
        pos = (round(cx - w / 2), round(cy - h / 2))
        face_meta[name] = {
            "file": str(face_path.relative_to(out_dir)).replace("\\", "/"),
            "pos": [pos[0], pos[1]],
            "size": [w, h],
        }
        if active:
            active_face = name
            canvas.alpha_composite(resized, pos)

    main_dir = out_dir / kind
    main_dir.mkdir(parents=True, exist_ok=True)
    main_path = main_dir / f"{art_id}.png"
    canvas.save(main_path)

    return ExportResult(
        ok=True,
        files=[str(main_path.relative_to(out_dir)).replace("\\", "/"), *[f["file"] for f in face_meta.values()]],
        meta={
            "kind": kind,
            "art_id": art_id,
            "group": record.group,
            "size": list(body_px),
            "active_face": active_face,
            "faces": face_meta,
            "bundle": record.name,
            "cdn": record.cdn,
        },
    )


def export_emo(bundle_path: Path, out_dir: Path, name: str, record: BundleRecord) -> ExportResult:
    """导出情绪符号(sdemo):取图标 Sprite 存成 ``emo/<名字>.png``。

    预制体里是一组 SpriteRenderer(图标 + 气泡底),图标是漫画式符号
    (``SdEmoIcon_Anger`` 等,多为 64×64);离线播放只取图标本身,气泡由播放器用 CSS 画。

    Args:
        bundle_path: bundle 的 ``__data`` 路径。
        out_dir: 输出根目录。
        name: 符号名(如 ``anger``,与脚本里的 ``Anger`` 小写对应)。
        record: catalog 记录。

    Returns:
        ExportResult: 文件清单与元数据。
    """
    env = UnityPy.load(str(bundle_path))
    best: tuple[tuple[int, int], object, str] | None = None
    for obj in env.objects:
        if obj.type.name != "Sprite":
            continue
        d = obj.read()
        # 优先名为 SdEmoIcon* 的图标,其次取面积最大的一张(排除 128×136 的气泡底)
        score = (1 if str(d.m_Name).startswith("SdEmoIcon") else 0, int(d.m_Rect.width) * int(d.m_Rect.height))
        if d.m_Name.startswith("SdEmoBallon"):
            continue
        if best is None or score > best[0]:
            best = (score, obj, d.m_Name)
    if best is None:
        return ExportResult(ok=False, error="bundle 里没有图标 Sprite")

    image = best[1].read().image.convert("RGBA")
    dst_dir = out_dir / "emo"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{name}.png"
    image.save(dst)
    return ExportResult(
        ok=True,
        files=[str(dst.relative_to(out_dir)).replace("\\", "/")],
        meta={
            "kind": "emo",
            "art_id": name,
            "group": record.group,
            "size": list(image.size),
            "source_object": str(best[2]),
            "bundle": record.name,
            "cdn": record.cdn,
        },
    )


def export_simple(bundle_path: Path, out_dir: Path, kind: str, stem: str, record: BundleRecord) -> ExportResult:
    """导出单图类资源(cut-in / 背景 / 剧情缩略图 / 图标)。

    选取规则:优先与资产主干同名的 Sprite,其次同名的 Texture2D,最后退化为唯一 Sprite。

    Args:
        bundle_path: bundle 的 ``__data`` 路径。
        out_dir: 输出根目录。
        kind: 类别目录名(``cutin``/``bg``/``story``/``icon``)。
        stem: 资产主干名,用作文件名与同名匹配。
        record: catalog 记录。

    Returns:
        ExportResult: 文件清单与元数据。
    """
    env = UnityPy.load(str(bundle_path))
    textures: dict[str, object] = {}
    sprites: dict[str, tuple[object, tuple[int, int]]] = {}
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            d = obj.read()
            textures.setdefault(d.m_Name, obj)
        elif obj.type.name == "Sprite":
            d = obj.read()
            sprites.setdefault(d.m_Name, (obj, (int(d.m_Rect.width), int(d.m_Rect.height))))

    wanted = stem.lower()
    image: Image.Image | None = None
    name = stem
    if wanted in {k.lower() for k in sprites}:
        key = next(k for k in sprites if k.lower() == wanted)
        image = sprites[key][0].read().image.convert("RGBA")
        name = key
    elif len(sprites) == 1:
        key = next(iter(sprites))
        image = sprites[key][0].read().image.convert("RGBA")
        name = key
    elif wanted in {k.lower() for k in textures}:
        name = next(k for k in textures if k.lower() == wanted)
        image = textures[name].read().image.convert("RGBA")
    elif len(textures) == 1:
        name = next(iter(textures))
        image = textures[name].read().image.convert("RGBA")
    if image is None:
        return ExportResult(ok=False, error=f"没找到可用图像(纹理 {len(textures)} / 精灵 {len(sprites)})")

    dst_dir = out_dir / kind
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{stem}.png"
    image.save(dst)
    return ExportResult(
        ok=True,
        files=[str(dst.relative_to(out_dir)).replace("\\", "/")],
        meta={
            "kind": kind,
            "art_id": stem,
            "group": record.group,
            "size": list(image.size),
            "source_object": name,
            "bundle": record.name,
            "cdn": record.cdn,
        },
    )
