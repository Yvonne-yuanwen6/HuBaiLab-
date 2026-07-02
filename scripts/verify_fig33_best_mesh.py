"""Verify mesh discretization for Fig.3.3 best-result cases (from case_manifest + local INP)."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.parse_cae_mesh_inp import count_cae_mesh_inp
from src.paths import EXPORT_ROOT, REPORTS_ROOT

PAPER_SEED_MM = 0.6
PAPER_ROD_MM = 2.0
BEST_MANIFEST = REPORTS_ROOT / "fig33_best_exp_vs_sim_all.json"

# lattice_contact @ seed=0.6, rods=3: mid-edge refine skipped (d/N == seed)
NOMINAL_ELEMS_ACROSS_ROD = PAPER_ROD_MM / PAPER_SEED_MM


def _load_json(path: os.PathLike | str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _count_inp_mesh(path: str) -> tuple[int, int] | None:
    if not os.path.isfile(path):
        return None
    try:
        return count_cae_mesh_inp(path)
    except Exception:
        pass
    # Fallback: count lines in *Node / *Element blocks (compression INP embeds mesh)
    n_nodes = 0
    n_elems = 0
    section = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if s.startswith("*Node"):
                section = "node"
                continue
            if s.startswith("*Element"):
                section = "elem" if "C3D4" in s.upper() else None
                continue
            if s.startswith("*"):
                section = None
                continue
            if not s or s.startswith("**"):
                continue
            if section == "node":
                n_nodes += 1
            elif section == "elem":
                n_elems += 1
    return (n_nodes, n_elems) if n_nodes and n_elems else None


def _estimate_tet_edge_stats(inp_path: str, *, sample: int = 5000) -> dict | None:
    """Sample C3D4 edge lengths from compression INP (mm)."""
    if not os.path.isfile(inp_path):
        return None
    nodes: dict[int, tuple[float, float, float]] = {}
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
                    nid = int(parts[0])
                    nodes[nid] = (float(parts[1]), float(parts[2]), float(parts[3]))
                except ValueError:
                    pass
            elif section == "elem" and len(parts) >= 5:
                try:
                    elems.append((int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])))
                except ValueError:
                    pass

    if not nodes or not elems:
        return None

    step = max(1, len(elems) // sample)
    edges: list[float] = []
    aspects: list[float] = []

    def dist(a: int, b: int) -> float:
        x0, y0, z0 = nodes[a]
        x1, y1, z1 = nodes[b]
        return math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2)

    for i, conn in enumerate(elems):
        if i % step:
            continue
        if not all(n in nodes for n in conn):
            continue
        ls = [dist(conn[0], conn[1]), dist(conn[0], conn[2]), dist(conn[0], conn[3]),
              dist(conn[1], conn[2]), dist(conn[1], conn[3]), dist(conn[2], conn[3])]
        edges.extend(ls)
        aspects.append(max(ls) / max(min(ls), 1e-9))

    if not edges:
        return None
    edges.sort()
    aspects.sort()
    return {
        "edge_mm_p50": edges[len(edges) // 2],
        "edge_mm_p95": edges[int(0.95 * (len(edges) - 1))],
        "edge_mm_min": edges[0],
        "aspect_p50": aspects[len(aspects) // 2],
        "aspect_p95": aspects[int(0.95 * (len(aspects) - 1))],
        "sample_tets": len(aspects),
    }


def _mesh_baseline_slug(cae_mesh_inp: str) -> str | None:
    m = re.search(r"/export/([^/]+)/[^/]+_cae_mesh\.inp", cae_mesh_inp.replace("\\", "/"))
    return m.group(1) if m else None


def verify_row(picked: dict) -> dict:
    slug = picked["slug"]
    manifest_path = EXPORT_ROOT / slug / "case_manifest.json"
    compression_inp = EXPORT_ROOT / slug / f"{slug}.inp"
    row: dict = {
        "key": picked["key"],
        "label": picked["label"],
        "slug": slug,
        "rmse": picked.get("rmse"),
    }
    if not manifest_path.is_file():
        row["status"] = "missing_case_manifest"
        return row

    cm = _load_json(manifest_path)
    mesh = cm.get("mesh") or {}
    row["mesh_settings"] = {
        "cae_seed_mm": mesh.get("cae_seed_mm"),
        "cae_mesh_quality": mesh.get("cae_mesh_quality"),
        "cae_rods_per_diameter": mesh.get("cae_rods_per_diameter"),
        "cae_virtual_topology": mesh.get("cae_virtual_topology"),
        "mesh_location": mesh.get("mesh_location"),
        "element": mesh.get("element"),
    }
    row["manifest_counts"] = {
        "node_count": mesh.get("node_count"),
        "element_count": mesh.get("element_count"),
    }
    cae_mesh = cm.get("cae_mesh_inp") or ""
    baseline = _mesh_baseline_slug(cae_mesh)
    row["mesh_source"] = {
        "cae_mesh_inp": cae_mesh,
        "baseline_slug": baseline,
        "reused_baseline": mesh.get("mesh_location") == "reuse",
    }

    seed = float(mesh.get("cae_seed_mm") or PAPER_SEED_MM)
    rods_n = float(mesh.get("cae_rods_per_diameter") or 3.0)
    quality = str(mesh.get("cae_mesh_quality") or "lattice_contact")
    row["derived"] = {
        "nominal_elems_across_rod_d_over_seed": PAPER_ROD_MM / seed,
        "target_rod_edge_mm_d_over_N": PAPER_ROD_MM / rods_n,
        "paper_seed_ok": abs(seed - PAPER_SEED_MM) < 1e-6,
        "curve_edge_forced": quality == "lattice_curve",
        "mid_edge_refine_active": (PAPER_ROD_MM / rods_n) < seed * 0.98,
    }

    checks: list[str] = []
    warnings: list[str] = []

    if mesh.get("element") != "C3D4":
        checks.append("FAIL: not C3D4")
    elif row["derived"]["paper_seed_ok"]:
        checks.append("PASS: seed=0.6 mm (paper §2.4.1)")
    else:
        warnings.append(f"seed={seed} mm differs from paper 0.6 mm")

    if quality != "lattice_curve" and picked["key"] != "bcc":
        warnings.append(
            "SFBLS uses lattice_contact only — no force_rod_edge_seeds on curved struts "
            f"(~{PAPER_ROD_MM / seed:.1f} elems/rod by global seed, target N={rods_n:.0f})"
        )
    if not row["derived"]["mid_edge_refine_active"] and quality == "lattice_contact":
        warnings.append(
            "lattice_contact mid-edge refine skipped (d/N ≈ global seed) — arc segments not extra-refined"
        )

    if compression_inp.is_file():
        counts = _count_inp_mesh(str(compression_inp))
        if counts:
            n_nodes, n_elems = counts
            row["inp_counts"] = {"node_count": n_nodes, "element_count": n_elems}
            mc = mesh.get("element_count")
            if mc and abs(n_elems - int(mc)) / int(mc) > 0.01:
                warnings.append(f"INP elem count {n_elems} vs manifest {mc} (>1% diff)")
            else:
                checks.append("PASS: INP element count matches manifest")
        stats = _estimate_tet_edge_stats(str(compression_inp))
        if stats:
            row["tet_sample_stats"] = stats
            if stats["aspect_p95"] > 10:
                warnings.append(f"high aspect p95={stats['aspect_p95']:.1f} (sampled)")
            else:
                checks.append(f"PASS: tet aspect p95≈{stats['aspect_p95']:.1f} (sampled)")
            if stats["edge_mm_p50"] > seed * 1.2:
                warnings.append(
                    f"median tet edge {stats['edge_mm_p50']:.3f} mm > 1.2× seed — coarser than target"
                )
    else:
        warnings.append("compression INP not local — skip INP recount")

    row["checks"] = checks
    row["warnings"] = warnings
    row["mesh_adequacy"] = (
        "adequate_for_paper_spec"
        if not any(w.startswith("SFBLS") or "curve" in w.lower() for w in warnings)
        and row["derived"]["paper_seed_ok"]
        else "paper_ok_curve_unverified"
        if row["derived"]["paper_seed_ok"]
        else "review"
    )
    row["status"] = "ok"
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(BEST_MANIFEST))
    parser.add_argument(
        "--write-json",
        default=str(REPORTS_ROOT / "fig33_best_mesh_verification.json"),
    )
    args = parser.parse_args()

    if not os.path.isfile(args.manifest):
        print(f"[ERROR] missing {args.manifest}")
        return 1

    picked = _load_json(args.manifest).get("picked") or []
    rows = [verify_row(p) for p in picked]

    print("Fig.3.3 best-result mesh verification\n")
    print(f"{'key':<8} {'label':<16} {'elems':>10} {'seed':>5} {'qual':<16} {'d/seed':>6} adequacy")
    print("-" * 90)
    for r in rows:
        ms = r.get("mesh_settings") or {}
        mc = r.get("manifest_counts") or {}
        dr = r.get("derived") or {}
        print(
            f"{r.get('key','?'):<8} {r.get('label','?'):<16} "
            f"{mc.get('element_count','?'):>10} "
            f"{ms.get('cae_seed_mm','?'):>5} "
            f"{str(ms.get('cae_mesh_quality','?')):<16} "
            f"{dr.get('nominal_elems_across_rod_d_over_seed',0):>6.1f} "
            f"{r.get('mesh_adequacy','?')}"
        )
        for c in r.get("checks") or []:
            print(f"  [OK] {c}")
        for w in r.get("warnings") or []:
            print(f"  [WARN] {w}")
        ts = r.get("tet_sample_stats")
        if ts:
            print(
                f"  tet sample: edge p50={ts['edge_mm_p50']:.3f} p95={ts['edge_mm_p95']:.3f} mm, "
                f"aspect p95={ts['aspect_p95']:.2f}"
            )
        print()

    os.makedirs(os.path.dirname(args.write_json) or ".", exist_ok=True)
    with open(args.write_json, "w", encoding="utf-8") as f:
        json.dump({"cases": rows}, f, indent=2, ensure_ascii=False)
    print("Wrote:", args.write_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
