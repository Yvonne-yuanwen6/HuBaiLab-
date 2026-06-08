from __future__ import annotations

import math

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Line3DCollection


def _node_bounds_3d(node_dict: dict[int, tuple[float, float, float]]) -> tuple[float, float, float, float, float, float]:
    xs = [p[0] for p in node_dict.values()]
    ys = [p[1] for p in node_dict.values()]
    zs = [p[2] for p in node_dict.values()]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def _set_axes3d_equal(ax, node_dict: dict[int, tuple[float, float, float]], *, pad: float = 0.05) -> None:
    xmin, xmax, ymin, ymax, zmin, zmax = _node_bounds_3d(node_dict)
    cx = 0.5 * (xmin + xmax)
    cy = 0.5 * (ymin + ymax)
    cz = 0.5 * (zmin + zmax)
    r = max(xmax - xmin, ymax - ymin, zmax - zmin) * 0.5
    r = max(r * (1.0 + pad), 1e-6)
    ax.set_xlim(cx - r, cx + r)
    ax.set_ylim(cy - r, cy + r)
    ax.set_zlim(cz - r, cz + r)
    try:
        ax.set_box_aspect((1, 1, 1))
    except AttributeError:
        pass


def _lattice_color_map() -> dict[str, str]:
    return {
        "frame": "black",
        "support": "red",
        "vertical": "blue",
        "sq_frame": "blue",
        "curved": "crimson",
        "cosine": "crimson",
        "star": "darkgreen",
        "crest": "orange",
        "link": "steelblue",
        "baffle": "forestgreen",
        "block": "saddlebrown",
        "endbar": "purple",
        "stub": "purple",
        "load": "darkorange",
        "bcc": "dimgray",
        "sfbls": "crimson",
    }


def radial_node_label_offsets(
    nodes: list,
    *,
    scale: float = 0.35,
    plane: str = "xz",
) -> dict[int, tuple[float, float, float]]:
    """Offset labels slightly outward from the structure centroid."""
    xs = [float(n[1]) for n in nodes]
    zs = [float(n[3]) for n in nodes]
    cx = 0.5 * (min(xs) + max(xs))
    cz = 0.5 * (min(zs) + max(zs))
    offsets: dict[int, tuple[float, float, float]] = {}
    for n in nodes:
        nid = int(n[0])
        x, y, z = float(n[1]), float(n[2]), float(n[3])
        dx, dz = x - cx, z - cz
        norm = math.hypot(dx, dz)
        if norm < 1e-9:
            ux, uz = 0.0, scale
        else:
            ux, uz = scale * dx / norm, scale * dz / norm
        if plane == "xz":
            offsets[nid] = (ux, uz)
        else:
            offsets[nid] = (ux, 0.12, uz)
    return offsets


def _merged_node_labels(
    nodes: list,
    node_labels: dict[int, str] | None,
    label_all_nodes: bool,
) -> dict[int, str]:
    labels: dict[int, str] = {}
    if label_all_nodes:
        for n in nodes:
            labels[int(n[0])] = str(int(n[0]))
    if node_labels:
        labels.update({int(k): str(v) for k, v in node_labels.items()})
    return labels


def plot_lattice(
    nodes,
    beams,
    save_path: str | None = None,
    polylines: list | None = None,
    node_labels: dict[int, str] | None = None,
    node_label_offsets: dict[int, tuple[float, float, float]] | None = None,
    label_all_nodes: bool = False,
    all_node_fontsize: float = 6.5,
    label_offset: float = 0.35,
    title: str = "Custom Lattice Structure",
    projection: str | None = None,
    star_rod_groups: list[dict] | None = None,
):
    """
    Draw lattice wireframe. ``projection='front'`` or ``'xz'`` = 正视图 (X–Z, view along +Y);
    ``'xy'`` = 俯视图; ``'yz'`` = 侧视图.
    """
    color_map = _lattice_color_map()
    node_dict = {int(n[0]): (float(n[1]), float(n[2]), float(n[3])) for n in nodes}
    labels = _merged_node_labels(nodes, node_labels, label_all_nodes)

    if projection in ("xz", "front"):
        fig, ax = plt.subplots(figsize=(14, 14))
        if node_label_offsets is None and labels:
            node_label_offsets = radial_node_label_offsets(nodes, scale=0.28, plane="xz")

        for _bid, n1, n2, _r, btype in beams:
            p1, p2 = node_dict[int(n1)], node_dict[int(n2)]
            ax.plot(
                [p1[0], p2[0]],
                [p1[2], p2[2]],
                color=color_map.get(str(btype), "gray"),
                linewidth=1.2,
            )

        for poly in polylines or []:
            btype = str(poly.get("type", "support"))
            pts = [node_dict[int(nid)] for nid in poly["nodes"]]
            ax.plot(
                [p[0] for p in pts],
                [p[2] for p in pts],
                color=color_map.get(btype, "gray"),
                linewidth=1.2,
            )

        if star_rod_groups:
            for group in star_rod_groups:
                chain = [int(n) for n in group["nodes"]]
                pts = [node_dict[nid] for nid in chain]
                mx = sum(p[0] for p in pts) / len(pts)
                mz = sum(p[2] for p in pts) / len(pts)
                ax.text(
                    mx,
                    mz,
                    str(group["name"]),
                    fontsize=10,
                    color="darkgreen",
                    weight="bold",
                    ha="center",
                    va="center",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="white", alpha=0.85),
                    zorder=5,
                    fontfamily="Microsoft YaHei",
                )

        for nid, label in labels.items():
            p = node_dict.get(int(nid))
            if p is None:
                continue
            off = node_label_offsets.get(int(nid)) if node_label_offsets else (0.0, 0.0)
            ox, oz = off[0], off[1] if len(off) == 2 else off[2]
            ax.text(
                p[0] + ox,
                p[2] + oz,
                label,
                fontsize=all_node_fontsize,
                color="navy",
                ha="center",
                va="center",
            )

        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Z (mm)")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.25, linewidth=0.5)
    elif projection == "xy":
        fig, ax = plt.subplots(figsize=(14, 14))
        for _bid, n1, n2, _r, btype in beams:
            p1, p2 = node_dict[int(n1)], node_dict[int(n2)]
            ax.plot(
                [p1[0], p2[0]],
                [p1[1], p2[1]],
                color=color_map.get(str(btype), "gray"),
                linewidth=1.2,
            )
        for poly in polylines or []:
            btype = str(poly.get("type", "support"))
            pts = [node_dict[int(nid)] for nid in poly["nodes"]]
            ax.plot(
                [p[0] for p in pts],
                [p[1] for p in pts],
                color=color_map.get(btype, "gray"),
                linewidth=1.2,
            )
        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.25, linewidth=0.5)
    elif projection == "yz":
        fig, ax = plt.subplots(figsize=(14, 14))
        for _bid, n1, n2, _r, btype in beams:
            p1, p2 = node_dict[int(n1)], node_dict[int(n2)]
            ax.plot(
                [p1[1], p2[1]],
                [p1[2], p2[2]],
                color=color_map.get(str(btype), "gray"),
                linewidth=1.2,
            )
        for poly in polylines or []:
            btype = str(poly.get("type", "support"))
            pts = [node_dict[int(nid)] for nid in poly["nodes"]]
            ax.plot(
                [p[1] for p in pts],
                [p[2] for p in pts],
                color=color_map.get(btype, "gray"),
                linewidth=1.2,
            )
        ax.set_xlabel("Y (mm)")
        ax.set_ylabel("Z (mm)")
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.25, linewidth=0.5)
    else:
        fig = plt.figure(figsize=(12, 12))
        ax = fig.add_subplot(111, projection="3d")
        if node_label_offsets is None and labels:
            node_label_offsets = radial_node_label_offsets(nodes, scale=0.35, plane="3d")

        # Line3DCollection: avoid mplot3d phantom chords when many polylines share the centre node.
        segments: list[list[tuple[float, float, float]]] = []
        seg_colors: list[str] = []
        for _bid, n1, n2, _r, btype in beams:
            p1, p2 = node_dict[int(n1)], node_dict[int(n2)]
            segments.append([p1, p2])
            seg_colors.append(color_map.get(str(btype), "gray"))
        for poly in polylines or []:
            btype = str(poly.get("type", "support"))
            color = color_map.get(btype, "gray")
            pts = [node_dict[int(nid)] for nid in poly["nodes"]]
            for i in range(len(pts) - 1):
                segments.append([pts[i], pts[i + 1]])
                seg_colors.append(color)
        if segments:
            ax.add_collection3d(
                Line3DCollection(segments, colors=seg_colors, linewidths=1.0)
            )
        # Mark shared cell centre once (if present).
        hub = [p for p in node_dict.values() if abs(p[0]) + abs(p[1]) + abs(p[2]) < 1e-9]
        if hub:
            ax.scatter([0.0], [0.0], [0.0], s=12, c="crimson", depthshade=False, zorder=5)
        _set_axes3d_equal(ax, node_dict)

        for nid, label in labels.items():
            p = node_dict.get(int(nid))
            if p is None:
                continue
            off = node_label_offsets.get(int(nid)) if node_label_offsets else None
            if off is None:
                ox, oy, oz = 0.0, float(label_offset), 0.0
            elif len(off) == 2:
                ox, oy, oz = off[0], 0.12, off[1]
            else:
                ox, oy, oz = off
            ax.text(
                p[0] + ox,
                p[1] + oy,
                p[2] + oz,
                label,
                fontsize=all_node_fontsize if label_all_nodes else 11,
                color="navy",
                weight="bold",
            )

        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")

    plt.title(title)
    if save_path:
        fig.savefig(save_path, dpi=200, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()
