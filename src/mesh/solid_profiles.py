"""Solid cross-section rules for lattice → C3D8R/C3D4 meshing."""

from __future__ import annotations

# 黑色框架仅作线框尺寸参考，不生成实体
SOLID_SKIP_BEAM_TYPES = frozenset({"frame"})


def polyline_mesh_profile(poly: dict) -> dict:
    """
    折线实体截面参数。

    - support: 圆 R=0.5（poly['radius']）
    - load: 正方形 1×1（profile=square, square_half=0.5）
    """
    profile = str(poly.get("profile", "circle")).lower()
    if profile == "square":
        return {
            "profile": "square",
            "square_half": float(poly.get("square_half", 0.5)),
        }
    return {
        "profile": "circle",
        "radius": float(poly.get("radius", 0.5)),
    }
