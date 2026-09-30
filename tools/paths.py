# -*- coding: utf-8 -*-
"""路径发现:游戏安装目录、bundle 缓存、用户数据与输出目录。

优先级:显式参数 > 环境变量 > 默认值。
默认值按本机标准安装位置推导,换机器时用参数或环境变量覆盖:
    DOTABYSS_GAME_DIR  游戏安装目录(内含 ドットアビスX_Data)
    DOTABYSS_OUT_DIR   导出产物目录
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_GAME_DIR = "DOTABYSS_GAME_DIR"
ENV_OUT_DIR = "DOTABYSS_OUT_DIR"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GAME_DIR = Path(r"E:\dmm\dotabyss_x_cl")
USER_DATA_REL = Path("AppData") / "LocalLow" / "EXNOA LLC_" / "ドットアビスX"

# 缓存目录内每个 bundle 的存放层级:Caches/<32hex CDN 名>/<内容 md5>/__data
CACHE_LEAF_NAME = "__data"


@dataclass(frozen=True)
class Paths:
    """一次导出所需的全部输入/输出路径。"""

    game_dir: Path
    out_dir: Path

    @property
    def cache_dir(self) -> Path:
        """Unity 的 bundle 缓存目录(Caches)。"""
        return self.game_dir / "ドットアビスX_Data" / "Caches"

    @property
    def user_data_dir(self) -> Path:
        """游戏的用户数据目录(含 Addressables catalog 与 master data)。"""
        return Path(os.path.expanduser("~")) / USER_DATA_REL

    @property
    def catalog_dir(self) -> Path:
        """Addressables catalog 所在目录(每次版本更新会新增一个 .bin)。"""
        return self.user_data_dir / "com.unity.addressables"

    @property
    def download_cache_dir(self) -> Path:
        """下载缓存目录(内含 master data 的 .dat)。"""
        return self.user_data_dir / "DownloadCache"


def discover(game_dir: Path | None = None, out_dir: Path | None = None) -> Paths:
    """构造并校验路径集合。

    Args:
        game_dir: 游戏安装目录;为 None 时读环境变量,再退回默认值。
        out_dir: 输出目录;为 None 时读环境变量,再退回 <仓库>/output。

    Returns:
        Paths: 校验通过的路径集合。

    Raises:
        FileNotFoundError: 游戏目录或缓存目录不存在时抛出。
    """
    game = Path(game_dir) if game_dir else Path(os.environ.get(ENV_GAME_DIR) or DEFAULT_GAME_DIR)
    out = Path(out_dir) if out_dir else Path(os.environ.get(ENV_OUT_DIR) or (REPO_ROOT / "output"))
    paths = Paths(game_dir=game, out_dir=out)
    if not paths.game_dir.is_dir():
        raise FileNotFoundError(f"游戏目录不存在:{paths.game_dir}")
    if not paths.cache_dir.is_dir():
        raise FileNotFoundError(f"bundle 缓存目录不存在:{paths.cache_dir}")
    if not paths.user_data_dir.is_dir():
        raise FileNotFoundError(f"用户数据目录不存在:{paths.user_data_dir}")
    return paths
