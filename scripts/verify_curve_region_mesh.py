"""Check whether SFBLS curved-strut regions are meshed finely enough (Fig.3.3 best cases)."""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import EXPORT_ROOT, REPORTS_ROOT

BEST_MANIFEST = REPORTS_ROOT / "fig33_best_exp_vs_sim_all.json"
L_MM = 20.0
ROD_D_MM = 2.0
ROD_R_MM = ROD_D_MM / 2.0
SEED_MM = 0.6
RODS_PER_D = 3.0
N_SEGMENTS = 12
NX = NY = NZ = 4

# s along chord: exclude junction caps near centre / corner
JUNCTION_S = 0.08
# peak bulge / high-curvature band (|sin(2*pi*Q*s)| large)
PEAK_SIN_MIN = 0.65


def _load_json(path: os.PathLike | str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _q_from_key(key: str) -> float | None:
    return {"af2q05": 0.5, "af2q1": 1.0, "af2q15": 1.5}.get(key)


def _stream_sample_tets(
    inp_path: str,
    segments: list[dict],
    grid: dict[tuple[int, int, int], list[int]],
    *,
    sample_stride: int,
) -> tuple[dict[str, list[float]], dict[str, int], list[float], list[float], int]:
    """Single-pass INP read; sample tets without storing full mesh."""
    coords: np.ndarray | None = None
    coords_cap = 350_000
    region_edges: dict[str, list[float]] = defaultdict(list)
    region_count: dict[str, int] = defaultdict(int)
    peak_s_samples: list[float] = []
    peak_arc_samples: list[float] = []
    section = None
    tet_index = 0
    n_tets = 0
    max_edge_samples = 80000

    def _ensure_coords() -> np.ndarray:
        nonlocal coords
        if coords is None:
            coords = np.zeros((coords_cap, 3), dtype=np.float32)
        return coords

    def _process_tet(nids: tuple[int, int, int, int]) -> None:
        nonlocal tet_index
        assert coords is not None
        tet_index += 1
        if (tet_index - 1) % sample_stride:
            return
        idx = [n - 1 for n in nids]
        if min(idx) < 0 or max(idx) >= coords.shape[0]:
            return
        pts = coords[idx]
        centroid = pts.mean(axis=0)
        si, dist, _ = _nearest_segment(centroid.astype(float), segments, grid)
        if si < 0:
            return
        seg = segments[si]
        region = _classify_region(seg, float(dist))
        region_count[region] += 1
        if len(region_edges[region]) < max_edge_samples:
            for i, j in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)):
                region_edges[region].append(float(np.linalg.norm(pts[j] - pts[i])))
        if region == "curve_peak":
            peak_s_samples.append(seg["sm"])
            peak_arc_samples.append(seg["arc0"] + 0.5 * (seg["arc1"] - seg["arc0"]))

    with open(inp_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s.startswith("*Node"):
                section = "node"
                continue
            if s.startswith("*Element") and "C3D4" in s.upper():
                section = "elem"
                continue
            if s.startswith("*"):
                section = None
                continue
            if not s or s.startswith("**"):
                continue
            parts = [p.strip() for p in s.split(",")]
            if section == "node" and len(parts) >= 4:
                try:
                    nid = int(parts[0])
                    arr = _ensure_coords()
                    if 1 <= nid <= coords_cap:
                        arr[nid - 1] = (float(parts[1]), float(parts[2]), float(parts[3]))
                except ValueError:
                    pass
            elif section == "elem" and len(parts) >= 5:
                try:
                    n_tets += 1
                    _process_tet((int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])))
                except ValueError:
                    pass

    if n_tets == 0 or coords is None:
        raise ValueError(f"no C3D4 mesh in {inp_path}")
    return region_edges, region_count, peak_s_samples, peak_arc_samples, n_tets


def _parse_c3d4_mesh(inp_path: str) -> tuple[np.ndarray, np.ndarray]:
    nodes: dict[int, np.ndarray] = {}
    elems: list[tuple[int, int, int, int]] = []
    section = None
    with open(inp_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s.startswith("*Node"):
                section = "node"
                continue
            if s.startswith("*Element") and "C3D4" in s.upper():
                section = "elem"
                continue
            if s.startswith("*"):
                section = None
                continue
            if not s or s.startswith("**"):
                continue
            parts = [p.strip() for p in s.split(",")]
            if section == "node" and len(parts) >= 4:
                try:
                    nodes[int(parts[0])] = np.array(
                        [float(parts[1]), float(parts[2]), float(parts[3])], dtype=float
                    )
                except ValueError:
                    pass
            elif section == "elem" and len(parts) >= 5:
                try:
                    elems.append((int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])))
                except ValueError:
                    pass

    if not nodes or not elems:
        raise ValueError(f"no C3D4 mesh in {inp_path}")

    node_ids = sorted(nodes)
    id_map = {nid: i for i, nid in enumerate(node_ids)}
    coords = np.array([nodes[nid] for nid in node_ids], dtype=float)
    conn = np.array(
        [[id_map[a], id_map[b], id_map[c], id_map[d]] for a, b, c, d in elems if all(x in id_map for x in (a, b, c, d))],
        dtype=np.int64,
    )
    return coords, conn


def _build_strut_segments(q: float) -> list[dict]:
    gen = HuBaiLatticeGenerator(
        cell_size=L_MM,
        rod_diameter=ROD_D_MM,
        amplitude=2.0,
        period_factor=q,
        n_segments=N_SEGMENTS,
    )
    gen.build_lattice(NX, NY, NZ)
    nodes, _, polylines = gen.get_data(copy=True)
    node_xyz = {int(n[0]): np.array([float(n[1]), float(n[2]), float(n[3])], dtype=float) for n in nodes}

    segments: list[dict] = []
    for pl in polylines:
        ids = pl["nodes"]
        if len(ids) < 2:
            continue
        pts = [node_xyz[int(nid)] for nid in ids]
        p0, p1 = pts[0], pts[-1]
        chord = p1 - p0
        chord_len = float(np.linalg.norm(chord))
        if chord_len < 1e-9:
            continue
        cum = 0.0
        cum_len = [0.0]
        for i in range(len(pts) - 1):
            cum += float(np.linalg.norm(pts[i + 1] - pts[i]))
            cum_len.append(cum)
        arc_total = cum_len[-1] if cum_len[-1] > 1e-9 else chord_len

        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            seg_len = float(np.linalg.norm(b - a))
            if seg_len < 1e-9:
                continue
            s0 = i / max(len(pts) - 1, 1)
            s1 = (i + 1) / max(len(pts) - 1, 1)
            sm = 0.5 * (s0 + s1)
            bulge = abs(math.sin(2.0 * math.pi * q * sm)) if q > 1e-9 else 0.0
            segments.append(
                {
                    "a": a,
                    "b": b,
                    "s0": s0,
                    "s1": s1,
                    "sm": sm,
                    "bulge": bulge,
                    "arc0": cum_len[i],
                    "arc1": cum_len[i + 1],
                    "arc_total": arc_total,
                    "p0": p0,
                    "p1": p1,
                }
            )
    return segments


def _point_segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    ab = b - a
    denom = float(np.dot(ab, ab))
    if denom < 1e-18:
        return float(np.linalg.norm(p - a)), 0.0
    t = float(np.clip(np.dot(p - a, ab) / denom, 0.0, 1.0))
    closest = a + t * ab
    return float(np.linalg.norm(p - closest)), t


def _voxel_key(x: float, y: float, z: float, cell: float) -> tuple[int, int, int]:
    return (int(math.floor(x / cell)), int(math.floor(y / cell)), int(math.floor(z / cell)))


def _index_segments(segments: list[dict], cell: float = 2.0) -> dict[tuple[int, int, int], list[int]]:
    grid: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for idx, seg in enumerate(segments):
        a, b = seg["a"], seg["b"]
        lo = np.minimum(a, b)
        hi = np.maximum(a, b)
        k0 = _voxel_key(lo[0], lo[1], lo[2], cell)
        k1 = _voxel_key(hi[0], hi[1], hi[2], cell)
        for ix in range(min(k0[0], k1[0]), max(k0[0], k1[0]) + 1):
            for iy in range(min(k0[1], k1[1]), max(k0[1], k1[1]) + 1):
                for iz in range(min(k0[2], k1[2]), max(k0[2], k1[2]) + 1):
                    grid[(ix, iy, iz)].append(idx)
    return grid


def _nearest_segment(
    p: np.ndarray,
    segments: list[dict],
    grid: dict[tuple[int, int, int], list[int]],
    *,
    cell: float = 2.0,
    search_r: int = 2,
) -> tuple[int, float, float]:
    ix, iy, iz = _voxel_key(p[0], p[1], p[2], cell)
    best_d = float("inf")
    best_i = -1
    best_t = 0.0
    for dx in range(-search_r, search_r + 1):
        for dy in range(-search_r, search_r + 1):
            for dz in range(-search_r, search_r + 1):
                for si in grid.get((ix + dx, iy + dy, iz + dz), []):
                    d, t = _point_segment_distance(p, segments[si]["a"], segments[si]["b"])
                    if d < best_d:
                        best_d, best_i, best_t = d, si, t
    return best_i, best_d, best_t


def _tet_edges(coords: np.ndarray, tet: np.ndarray) -> np.ndarray:
    pts = coords[tet]
    return np.array(
        [
            np.linalg.norm(pts[1] - pts[0]),
            np.linalg.norm(pts[2] - pts[0]),
            np.linalg.norm(pts[3] - pts[0]),
            np.linalg.norm(pts[2] - pts[1]),
            np.linalg.norm(pts[3] - pts[1]),
            np.linalg.norm(pts[3] - pts[2]),
        ],
        dtype=float,
    )


def _classify_region(seg: dict, dist: float) -> str:
    if dist > ROD_R_MM * 1.15:
        return "bulk"
    sm = seg["sm"]
    if sm < JUNCTION_S or sm > 1.0 - JUNCTION_S:
        return "junction"
    if seg["bulge"] >= PEAK_SIN_MIN:
        return "curve_peak"
    if sm > JUNCTION_S and sm < 1.0 - JUNCTION_S:
        return "curve_arc"
    return "junction"


def analyze_case(key: str, slug: str, q: float, *, sample_stride: int = 1) -> dict:
    inp_path = EXPORT_ROOT / slug / f"{slug}.inp"
    if not inp_path.is_file():
        return {"key": key, "slug": slug, "status": "missing_inp"}

    segments = _build_strut_segments(q)
    grid = _index_segments(segments, cell=2.0)
    region_edges, region_count, peak_s_samples, peak_arc_samples, n_tets = _stream_sample_tets(
        str(inp_path),
        segments,
        grid,
        sample_stride=max(1, sample_stride),
    )

    target_cross = ROD_D_MM / RODS_PER_D
    target_elems_across = RODS_PER_D
    stride = max(1, sample_stride)

    def _edge_stats(name: str) -> dict | None:
        arr = region_edges.get(name)
        if not arr:
            return None
        a = np.array(arr, dtype=float)
        p50 = float(np.percentile(a, 50))
        p95 = float(np.percentile(a, 95))
        return {
            "samples": int(len(a)),
            "edge_mm_p50": p50,
            "edge_mm_p95": p95,
            "elems_across_d_est": ROD_D_MM / p50,
        }

    peak_stats = _edge_stats("curve_peak")
    arc_stats = _edge_stats("curve_arc")
    junc_stats = _edge_stats("junction")

    # Along-arc spacing in peak band (unique arc coords binned)
    along_peak_spacing = None
    elems_along_peak_arc = None
    if peak_arc_samples:
        arc = np.sort(np.array(peak_arc_samples, dtype=float))
        # merge within 0.25*seed
        tol = 0.25 * SEED_MM
        merged = [arc[0]]
        for v in arc[1:]:
            if v - merged[-1] > tol:
                merged.append(v)
        if len(merged) >= 2:
            spacings = np.diff(merged)
            along_peak_spacing = float(np.median(spacings))
        # typical peak arc length ~ fraction of strut with |sin|>0.65
        mean_arc_total = float(np.mean([s["arc_total"] for s in segments]))
        peak_frac = 0.22 if q <= 0.5 else (0.18 if q <= 1.0 else 0.15)
        peak_arc_len = mean_arc_total * peak_frac
        med_edge = peak_stats["edge_mm_p50"] if peak_stats else SEED_MM
        elems_along_peak_arc = peak_arc_len / max(med_edge, 1e-9)

    adequate_cross = bool(peak_stats and peak_stats["elems_across_d_est"] >= RODS_PER_D - 0.15)
    adequate_along = bool(elems_along_peak_arc and elems_along_peak_arc >= 5.0)

    verdict = "adequate"
    issues: list[str] = []
    if peak_stats:
        if peak_stats["elems_across_d_est"] < RODS_PER_D - 0.2:
            issues.append(
                f"curve peak ~{peak_stats['elems_across_d_est']:.1f} elems/diameter "
                f"(target {RODS_PER_D:.0f}, need ~{target_cross:.3f} mm edges, got p50={peak_stats['edge_mm_p50']:.3f} mm)"
            )
        if peak_stats["edge_mm_p50"] > target_cross * 1.08:
            issues.append(
                f"peak edge p50 {peak_stats['edge_mm_p50']:.3f} mm > d/N={target_cross:.3f} mm — rod-edge refine inactive"
            )
    else:
        issues.append("no curve_peak samples (check geometry)")
        verdict = "unknown"

    if elems_along_peak_arc is not None and elems_along_peak_arc < 5.0:
        issues.append(
            f"only ~{elems_along_peak_arc:.1f} elems along peak arc "
            f"(spacing ~{along_peak_spacing or 0:.2f} mm)"
        )

    if issues:
        verdict = "coarse" if peak_stats and peak_stats["elems_across_d_est"] < RODS_PER_D - 0.25 else "marginal"

    return {
        "key": key,
        "slug": slug,
        "Q": q,
        "status": "ok",
        "mesh_file": str(inp_path),
        "n_tets_total": n_tets,
        "n_tets_sampled": int(math.ceil(n_tets / stride)),
        "sample_stride": stride,
        "region_tet_counts": dict(region_count),
        "curve_peak": peak_stats,
        "curve_arc": arc_stats,
        "junction": junc_stats,
        "along_peak_arc": {
            "median_spacing_mm": along_peak_spacing,
            "elems_in_peak_band_est": elems_along_peak_arc,
            "mean_strut_arc_mm": float(np.mean([s["arc_total"] for s in segments])),
        },
        "targets": {
            "seed_mm": SEED_MM,
            "rods_per_diameter": RODS_PER_D,
            "rod_edge_mm": target_cross,
            "recommended_rods_per_diameter": 4,
            "recommended_rod_edge_mm": ROD_D_MM / 4.0,
        },
        "adequate_cross_section": adequate_cross,
        "adequate_along_arc": adequate_along,
        "verdict": verdict,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(BEST_MANIFEST))
    parser.add_argument(
        "--write-json",
        default=str(REPORTS_ROOT / "fig33_curve_region_mesh_check.json"),
    )
    parser.add_argument(
        "--sample-stride",
        type=int,
        default=4,
        help="analyze every Nth tet (default 4 ~ 300k samples on 1.2M mesh)",
    )
    args = parser.parse_args()

    picked = _load_json(args.manifest).get("picked") or []
    rows = []
    for p in picked:
        q = _q_from_key(p["key"])
        if q is None:
            continue
        rows.append(analyze_case(p["key"], p["slug"], q, sample_stride=args.sample_stride))
        gc.collect()

    print("SFBLS curve-region mesh check (best Fig.3.3 cases)\n")
    print(
        f"{'key':<8} {'Q':>4} {'peak p50':>9} {'elems/d':>8} {'along peak':>11} verdict"
    )
    print("-" * 62)
    for r in rows:
        pk = r.get("curve_peak") or {}
        al = r.get("along_peak_arc") or {}
        al_est = al.get("elems_in_peak_band_est")
        print(
            f"{r['key']:<8} {r['Q']:>4.1f} "
            f"{pk.get('edge_mm_p50', 0):>9.3f} "
            f"{pk.get('elems_across_d_est', 0):>8.1f} "
            f"{(al_est if al_est is not None else 0):>11.1f} "
            f"{r.get('verdict', '?')}"
        )
        for issue in r.get("issues") or []:
            print(f"  - {issue}")
        print()

    os.makedirs(os.path.dirname(args.write_json) or ".", exist_ok=True)
    with open(args.write_json, "w", encoding="utf-8") as f:
        json.dump({"cases": rows}, f, indent=2, ensure_ascii=False)
    print("Wrote:", args.write_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
