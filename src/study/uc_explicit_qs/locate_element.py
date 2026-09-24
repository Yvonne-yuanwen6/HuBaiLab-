"""Locate a solid element in a CAE mesh INP (coords + region tag)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


_NODE_RE = re.compile(r"^\s*(\d+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)")


def _parse_nodes(lines: list[str], start: int) -> tuple[dict[int, tuple[float, float, float]], int]:
    nodes: dict[int, tuple[float, float, float]] = {}
    i = start
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("**"):
            i += 1
            continue
        if line.startswith("*"):
            break
        m = _NODE_RE.match(line)
        if m:
            nid = int(m.group(1))
            nodes[nid] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))
        i += 1
    return nodes, i


def _parse_elements(
    lines: list[str], start: int
) -> tuple[dict[int, list[int]], int]:
    elems: dict[int, list[int]] = {}
    i = start
    buf: list[str] = []
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("**"):
            i += 1
            continue
        if line.startswith("*"):
            break
        # Element cards may wrap; accumulate until we have eid + ≥4 nodes.
        buf.append(line.rstrip(","))
        joined = ",".join(buf)
        parts = [p.strip() for p in joined.split(",") if p.strip()]
        if len(parts) >= 5:
            try:
                eid = int(parts[0])
                nids = [int(x) for x in parts[1:]]
                elems[eid] = nids
                buf = []
            except ValueError:
                buf = []
        i += 1
    return elems, i


def load_mesh_nodes_elems(
    mesh_inp: Path,
) -> tuple[dict[int, tuple[float, float, float]], dict[int, list[int]]]:
    text = Path(mesh_inp).read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    nodes: dict[int, tuple[float, float, float]] = {}
    elems: dict[int, list[int]] = {}
    i = 0
    while i < len(lines):
        low = lines[i].strip().lower()
        if low.startswith("*node"):
            chunk, i = _parse_nodes(lines, i + 1)
            nodes.update(chunk)
            continue
        if low.startswith("*element"):
            chunk, i = _parse_elements(lines, i + 1)
            elems.update(chunk)
            continue
        i += 1
    return nodes, elems


def region_tag(
    centroid: tuple[float, float, float],
    *,
    bbox: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> str:
    """Classify element relative to model bounding box (compression along Z)."""
    (xmin, xmax), (ymin, ymax), (zmin, zmax) = bbox
    x, y, z = centroid
    dx, dy, dz = xmax - xmin, ymax - ymin, zmax - zmin
    # Relative position in [0,1]
    rx = (x - xmin) / dx if dx > 1e-12 else 0.5
    ry = (y - ymin) / dy if dy > 1e-12 else 0.5
    rz = (z - zmin) / dz if dz > 1e-12 else 0.5

    z_band = "bottom" if rz < 0.25 else ("top" if rz > 0.75 else "mid_height")
    # Near lateral face / corner vs core
    edge_tol = 0.12
    near_x = rx < edge_tol or rx > 1.0 - edge_tol
    near_y = ry < edge_tol or ry > 1.0 - edge_tol
    if near_x and near_y:
        lateral = "corner_rod"
    elif near_x or near_y:
        lateral = "side_face"
    else:
        lateral = "core"
    return f"{z_band}/{lateral}"


def _edge_length(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _tet_quality(corners: list[tuple[float, float, float]]) -> dict[str, float | None]:
    """Corner-tet metrics: edge lengths, aspect ratio, signed volume."""
    if len(corners) < 4:
        return {
            "edge_min_mm": None,
            "edge_max_mm": None,
            "edge_mean_mm": None,
            "aspect_ratio": None,
            "volume_mm3": None,
        }
    edges = []
    for a, b in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)):
        edges.append(_edge_length(corners[a], corners[b]))
    emin, emax = min(edges), max(edges)
    # Signed volume of corner tet
    ax, ay, az = corners[0]
    bx, by, bz = (corners[1][0] - ax, corners[1][1] - ay, corners[1][2] - az)
    cx, cy, cz = (corners[2][0] - ax, corners[2][1] - ay, corners[2][2] - az)
    dx, dy, dz = (corners[3][0] - ax, corners[3][1] - ay, corners[3][2] - az)
    vol = abs(
        bx * (cy * dz - cz * dy)
        - by * (cx * dz - cz * dx)
        + bz * (cx * dy - cy * dx)
    ) / 6.0
    return {
        "edge_min_mm": emin,
        "edge_max_mm": emax,
        "edge_mean_mm": sum(edges) / len(edges),
        "aspect_ratio": (emax / emin) if emin > 1e-15 else float("inf"),
        "volume_mm3": vol,
    }


def locate_element(
    mesh_inp: Path,
    element_id: int,
    *,
    L_mm: float | None = None,
    neighbor_ring: int = 1,
) -> dict[str, Any]:
    nodes, elems = load_mesh_nodes_elems(mesh_inp)
    if element_id not in elems:
        return {
            "ok": False,
            "element_id": element_id,
            "reason": f"element {element_id} not found in {mesh_inp}",
            "n_elements": len(elems),
            "n_nodes": len(nodes),
        }
    nids = elems[element_id]
    missing = [n for n in nids if n not in nodes]
    if missing:
        return {
            "ok": False,
            "element_id": element_id,
            "reason": f"missing nodes {missing[:8]}",
            "connectivity": nids,
        }
    coords = [nodes[n] for n in nids]
    # Use corner nodes (first 4) for tet10 centroid if available
    corners = coords[:4] if len(coords) >= 4 else coords
    cx = sum(c[0] for c in corners) / len(corners)
    cy = sum(c[1] for c in corners) / len(corners)
    cz = sum(c[2] for c in corners) / len(corners)
    centroid = (cx, cy, cz)

    xs = [c[0] for c in nodes.values()]
    ys = [c[1] for c in nodes.values()]
    zs = [c[2] for c in nodes.values()]
    bbox = ((min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs)))
    tag = region_tag(centroid, bbox=bbox)
    quality = _tet_quality(list(corners))

    # Neighbor elements sharing any corner node (local mesh quality).
    corner_set = set(nids[:4] if len(nids) >= 4 else nids)
    node_to_elems: dict[int, list[int]] = {}
    for eid, enodes in elems.items():
        for n in enodes[:4]:
            node_to_elems.setdefault(n, []).append(eid)
    neigh_ids = set()
    frontier = {element_id}
    for _ in range(max(1, neighbor_ring)):
        nxt = set()
        for eid in frontier:
            for n in (elems[eid][:4] if len(elems[eid]) >= 4 else elems[eid]):
                for e2 in node_to_elems.get(n, []):
                    if e2 != element_id:
                        nxt.add(e2)
        neigh_ids |= nxt
        frontier = nxt
    neigh_ids.discard(element_id)

    neigh_stats = []
    for eid in sorted(neigh_ids)[:80]:
        ec = [nodes[n] for n in elems[eid][:4] if n in nodes]
        if len(ec) < 4:
            continue
        q = _tet_quality(ec)
        neigh_stats.append(
            {
                "element_id": eid,
                "aspect_ratio": q["aspect_ratio"],
                "edge_mean_mm": q["edge_mean_mm"],
                "volume_mm3": q["volume_mm3"],
            }
        )
    aspects = [s["aspect_ratio"] for s in neigh_stats if isinstance(s["aspect_ratio"], float)]
    edge_means = [s["edge_mean_mm"] for s in neigh_stats if isinstance(s["edge_mean_mm"], float)]

    note = None
    if L_mm is not None:
        note = (
            f"UC L={L_mm:g} mm; Z compression; "
            f"z∈[{bbox[2][0]:.3g},{bbox[2][1]:.3g}]"
        )

    return {
        "ok": True,
        "element_id": element_id,
        "mesh_inp": str(mesh_inp),
        "n_nodes_in_elem": len(nids),
        "connectivity": nids,
        "corner_node_ids": list(corner_set),
        "corner_coords_mm": [list(c) for c in corners],
        "centroid_mm": [cx, cy, cz],
        "bbox_mm": {
            "x": list(bbox[0]),
            "y": list(bbox[1]),
            "z": list(bbox[2]),
        },
        "region": tag,
        "element_size": quality,
        "char_edge_mm": quality.get("edge_mean_mm"),
        "neighbor_count": len(neigh_ids),
        "neighbor_quality_summary": {
            "n_reported": len(neigh_stats),
            "aspect_ratio_min": min(aspects) if aspects else None,
            "aspect_ratio_max": max(aspects) if aspects else None,
            "aspect_ratio_mean": (sum(aspects) / len(aspects)) if aspects else None,
            "edge_mean_mm_min": min(edge_means) if edge_means else None,
            "edge_mean_mm_max": max(edge_means) if edge_means else None,
            "edge_mean_mm_mean": (sum(edge_means) / len(edge_means)) if edge_means else None,
            "n_aspect_gt_3": sum(1 for a in aspects if a > 3.0),
            "n_aspect_gt_5": sum(1 for a in aspects if a > 5.0),
        },
        "neighbors_sample": neigh_stats[:20],
        "note": note,
    }


def write_element_report(
    mesh_inp: Path,
    element_id: int,
    out_json: Path,
    *,
    L_mm: float | None = 20.0,
) -> dict[str, Any]:
    info = locate_element(mesh_inp, element_id, L_mm=L_mm)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info
