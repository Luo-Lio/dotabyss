# -*- coding: utf-8 -*-
"""Unity UI 预制体的 RectTransform 布局求解。

立绘预制体是「Canvas 根 → StandZoomPos → Pose → Body → FaceContent → 表情」的 UI 层级,
要把多个 Sprite 合成为一张整图,必须按 Unity 的锚点规则解出每个节点的矩形与缩放:

- 节点矩形尺寸(节点局部单位):``R = 锚点跨度 × 父矩形尺寸 + sizeDelta``
- 点锚点(anchorMin == anchorMax)时 ``R == sizeDelta``(表情层用拉伸锚点,sizeDelta 为 0)
- 节点中心(相对根):``父中心 + (锚点位置 + anchoredPosition + (0.5 - pivot) × R × 自身缩放) × 父累计缩放``
- 到根的累计缩放 = 自身与所有祖先的 localScale 连乘

实测该预制体所有节点 pivot 均为 (0.5, 0.5),但公式仍按通式实现。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RectTransform:
    """一个 RectTransform 节点(只保留布局求解需要的字段)。"""

    path_id: int
    game_object: int
    father: int | None
    anchored: tuple[float, float]
    size_delta: tuple[float, float]
    pivot: tuple[float, float]
    scale: tuple[float, float]
    anchor_min: tuple[float, float]
    anchor_max: tuple[float, float]


class RectTransformTree:
    """RectTransform 层级,带记忆化求解。"""

    def __init__(self, nodes: dict[int, RectTransform]) -> None:
        """初始化。

        Args:
            nodes: path_id → 节点。
        """
        self.nodes = nodes
        self._rect: dict[int, tuple[float, float]] = {}
        self._world: dict[int, tuple[tuple[float, float], tuple[float, float]]] = {}

    def rect_size(self, path_id: int) -> tuple[float, float]:
        """节点自身矩形尺寸(节点局部单位,不含自身缩放)。"""
        if path_id in self._rect:
            return self._rect[path_id]
        node = self.nodes[path_id]
        father = node.father
        if father is None or father not in self.nodes:
            value = node.size_delta
        else:
            fw, fh = self.rect_size(father)
            value = (
                fw * (node.anchor_max[0] - node.anchor_min[0]) + node.size_delta[0],
                fh * (node.anchor_max[1] - node.anchor_min[1]) + node.size_delta[1],
            )
        self._rect[path_id] = value
        return value

    def world(self, path_id: int) -> tuple[tuple[float, float], tuple[float, float]]:
        """节点中心与到根的累计缩放(单位:根局部单位)。

        Returns:
            (中心坐标, 累计缩放);中心含锚点位置与 pivot 偏移。
        """
        if path_id in self._world:
            return self._world[path_id]
        node = self.nodes[path_id]
        father = node.father
        if father is None or father not in self.nodes:
            value = ((0.0, 0.0), node.scale)
        else:
            (fx, fy), (fsx, fsy) = self.world(father)
            fw, fh = self.rect_size(father)
            amin, amax, piv = node.anchor_min, node.anchor_max, node.pivot
            # 锚点在父矩形中的位置(相对父 pivot)
            ax = -fw / 2 + (amin[0] + amax[0]) / 2 * fw
            ay = -fh / 2 + (amin[1] + amax[1]) / 2 * fh
            # pivot 与矩形中心不重合时的偏移(经自身缩放)
            own_w, own_h = self.rect_size(path_id)
            ox = (0.5 - piv[0]) * own_w * node.scale[0]
            oy = (0.5 - piv[1]) * own_h * node.scale[1]
            value = (
                (fx + (ax + node.anchored[0] + ox) * fsx, fy + (ay + node.anchored[1] + oy) * fsy),
                (fsx * node.scale[0], fsy * node.scale[1]),
            )
        self._world[path_id] = value
        return value

    def is_descendant(self, node_id: int, ancestor_id: int) -> bool:
        """判断节点是否为某祖先节点的后代(不含自身)。

        Args:
            node_id: 待判断节点。
            ancestor_id: 祖先节点。

        Returns:
            bool: 是后代返回 True。
        """
        cur = self.nodes.get(node_id)
        while cur is not None and cur.father is not None:
            if cur.father == ancestor_id:
                return True
            cur = self.nodes.get(cur.father)
        return False

    def drawn_rect(self, path_id: int) -> tuple[tuple[float, float], tuple[float, float]]:
        """节点在根坐标系里的绘制矩形。

        Returns:
            (中心坐标, 绘制尺寸);绘制尺寸 = 节点矩形 × 到根累计缩放。
        """
        center, scale = self.world(path_id)
        w, h = self.rect_size(path_id)
        return center, (w * scale[0], h * scale[1])
