"""
Step-by-step Q0.5 (SFBLS) unit-cell export for visual QA.

Run one stage at a time, inspect the artifact, then proceed:

  py -3 scripts/export_unitcell_stepwise_qa.py --stage 1
  py -3 scripts/export_unitcell_stepwise_qa.py --stage 2
  ...

Stages
------
  1  topology     JSON + wireframe PNG (nodes, polylines)
  2  primitives  JSON manifest (8 pipe + 9 sphere specs)
  3  occ17       STEP compound, 17 separate OCC solids (fuse=False)
  4  pipes8      STEP compound, 8 pipe sweeps only (sweep QA)
  5  pipes_fused STEP, batch-fused 8 pipes (no junction spheres)
  6  fused_raw   STEP after full fuse, before prune (may be multi-body)
  7  final       STEP after prune (production output)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import (
    _collect_solid_primitives,
    _configure_occ_for_fuse,
    _occ_dimtags_from_parts,
    _occ_fuse_lattice_primitives,
    _occ_fuse_pipe_tags,
    _finalize_occ_step_write,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs
from src.visualization.plot_lattice import plot_lattice

STAGE_HELP = {
    1: "拓扑：9 节点、8 根正弦杆路径（JSON + 线框 PNG）",
    2: "基元：17 个 OCC 基元清单（8 pipe + 9 sphere）",
    3: "OCC 建模：17 体 compound STEP（未融合）",
    4: "扫掠 QA：仅 8 根 pipe STEP（未融合，检查截面是否均匀圆柱）",
    5: "杆融合：pairwise 融 8 根 pipe 为 1 体（尚无节点球）",
    6: "全融合：杆+球 fuse 后、prune 前 STEP",
    7: "最终：prune + 写 STEP（与 export_unitcell_paper_box_cut 相同管线）",
}

STAGE_CHECKS = {
    1: [
        "结构结点 = 9（1 中心 + 8 角点；JSON 里 nodes 含路径采样点，约 193 个）",
        "polyline 数 = 8，每根 25 个采样点（n_segments=24）",
        "PNG 线框：8 根杆从中心向外弯，方向朝各角点",
    ],
    2: [
        "pipe 基元 = 8，sphere 基元 = 9",
        "每根 pipe 半径 r = 1.0 mm（杆径 d=2）",
        "9 个 sphere 半径均为 1.0 mm",
    ],
    3: [
        "优先打开 03_individual/ 下单体 STEP（SW 安全，一次一个文件）",
        "compound 03_occ_17bodies.step：17 solid，约 35 PRODUCT（未 prune，勿一次开太多）",
        "8 根杆 + 9 个节点球，几何互不融合",
        "杆截面均匀（spline + CorrectedFrenet）",
    ],
    4: [
        "本步为未融合 8 体 compound：STEP 约 26 PRODUCT / 8 SOLID",
        "SolidWorks 会按装配体导入 → 设计树 ~25 子项、多窗口（spline 构造 orphan）",
        "截面 QA 请用 03_individual/09..16_pipe.step 逐根打开",
        "单窗口看 8 杆交汇请直接跳到 Stage 5",
    ],
    5: [
        "（分步 QA 专用）pairwise/per-strut 融 8 杆；最终单胞已改统一融合",
        "SW 打开 STEP：1 个 solid",
        "8 根杆已在中心交汇融合，无节点球",
    ],
    6: [
        "SW 打开 STEP：统一融合后、prune 前",
        "9 个节点球与杆连接自然",
        "8 杆 + 9 球几何齐全",
    ],
    7: [
        "SW 打开 STEP：最终单胞（统一融合 + prune）",
        "1 个 MANIFOLD_SOLID",
        "所有 Q 走同一套 fuse 逻辑",
    ],
}


def _default_out_dir(q: float) -> str:
    q_tag = str(q).replace(".", "p")
    return os.path.join(str(CAD_ROOT), f"_stepwise_q{q_tag}")


def _build_lattice(*, q: float, af: float, n_segments: int):
    gen = HuBaiLatticeGenerator(
        cell_size=20.0,
        rod_diameter=2.0,
        amplitude=float(af),
        period_factor=float(q),
        n_segments=max(3, int(n_segments)),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    return gen, nodes, beams, polylines


def _primitive_summary(parts: list) -> list[dict]:
    rows: list[dict] = []
    for idx, (kind, *payload) in enumerate(parts):
        row: dict = {"index": idx, "kind": kind}
        if kind == "sphere":
            center, radius = payload
            row["center"] = [float(x) for x in center]
            row["radius_mm"] = float(radius)
        elif kind == "pipe":
            path_pts, radius = payload
            row["n_path_points"] = len(path_pts)
            row["radius_mm"] = float(radius)
            row["start"] = [float(x) for x in path_pts[0]]
            row["end"] = [float(x) for x in path_pts[-1]]
        else:
            p1, p2, radius = payload
            row["start"] = [float(x) for x in p1]
            row["end"] = [float(x) for x in p2]
            row["radius_mm"] = float(radius)
        rows.append(row)
    return rows


def _write_gmsh_step(path: str) -> None:
    import gmsh

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    gmsh.write(path)


def _count_volumes() -> int:
    import gmsh

    return len(gmsh.model.getEntities(3))


def stage_1_topology(out_dir: str, *, q: float, af: float, n_segments: int) -> dict:
    gen, nodes, beams, polylines = _build_lattice(q=q, af=af, n_segments=n_segments)

    topo = {
        "variant": gen.variant_name,
        "Q": q,
        "L_mm": gen.L,
        "rod_diameter_mm": gen.rod_diameter,
        "Af_mm": gen.amplitude,
        "n_segments": gen.n_segments,
        "node_count": len(nodes),
        "beam_count": len(beams),
        "polyline_count": len(polylines),
        "nodes": [[int(n[0]), float(n[1]), float(n[2]), float(n[3])] for n in nodes],
        "polylines": [
            {
                "id": int(p["id"]),
                "node_ids": [int(x) for x in p["nodes"]],
                "radius_mm": float(p["radius"]),
                "type": str(p["type"]),
                "n_points": len(p["nodes"]),
            }
            for p in polylines
        ],
    }
    json_path = os.path.join(out_dir, "01_topology.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(topo, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    png_path = os.path.join(out_dir, "01_topology_wireframe.png")
    title = f"{gen.variant_name} unit cell — topology (L={gen.L}, d={gen.rod_diameter}, Q={q})"
    plot_lattice(nodes, beams, save_path=png_path, polylines=polylines, title=title)

    return {
        "stage": 1,
        "artifacts": [json_path, png_path],
        "summary": {
            "nodes": len(nodes),
            "polylines": len(polylines),
            "points_per_polyline": [len(p["nodes"]) for p in polylines],
        },
    }


def stage_2_primitives(out_dir: str, *, q: float, af: float, n_segments: int) -> dict:
    _, nodes, beams, polylines = _build_lattice(q=q, af=af, n_segments=n_segments)
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    summary = _primitive_summary(parts)
    n_pipe = sum(1 for p in parts if p[0] == "pipe")
    n_sphere = sum(1 for p in parts if p[0] == "sphere")

    manifest = {
        "stage": 2,
        "total_parts": len(parts),
        "pipe_count": n_pipe,
        "sphere_count": n_sphere,
        "trim_for_junctions": False,
        "polyline_sweep": "pipe",
        "parts": summary,
    }
    json_path = os.path.join(out_dir, "02_primitives.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    return {
        "stage": 2,
        "artifacts": [json_path],
        "summary": {"total": len(parts), "pipes": n_pipe, "spheres": n_sphere},
        "parts": parts,
        "nodes": nodes,
        "beams": beams,
        "polylines": polylines,
    }


def _init_gmsh_model(name: str):
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(name)
    return gmsh


def stage_3_occ17(out_dir: str, *, q: float, af: float, n_segments: int) -> dict:
    from src.export.export_sw import export_lattice_step_occ

    _, nodes, beams, polylines = _build_lattice(q=q, af=af, n_segments=n_segments)
    step_path = os.path.join(out_dir, "03_occ_17bodies.step")
    report = export_lattice_step_occ(
        nodes,
        beams,
        step_path,
        polylines=polylines,
        junction_spheres=False,
        fuse=False,
    )

    # SW opens one window per STEP PRODUCT; spline pipe orphans add extras.
    # Export one body per file so you can inspect in SW without a GDI storm.
    ind_dir = os.path.join(out_dir, "03_individual")
    os.makedirs(ind_dir, exist_ok=True)
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    individual: list[str] = []
    gmsh = _init_gmsh_model("one_body")
    try:
        for idx, part in enumerate(parts):
            kind = part[0]
            tag = f"{idx:02d}_{kind}"
            _occ_dimtags_from_parts([part])
            gmsh.model.occ.synchronize()
            one_path = os.path.join(ind_dir, f"{tag}.step")
            _write_gmsh_step(one_path)
            individual.append(one_path)
            gmsh.model.occ.remove(gmsh.model.getEntities(), recursive=True)
            gmsh.model.occ.synchronize()
    finally:
        gmsh.finalize()

    return {
        "stage": 3,
        "artifacts": [step_path, ind_dir, *individual],
        "summary": {
            **report,
            "individual_steps": len(individual),
            "individual_dir": os.path.abspath(ind_dir),
        },
    }


def stage_4_pipes8(out_dir: str, *, q: float, af: float, n_segments: int) -> dict:
    _, nodes, beams, polylines = _build_lattice(q=q, af=af, n_segments=n_segments)
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    pipe_parts = [p for p in parts if p[0] == "pipe"]
    step_path = os.path.join(out_dir, "04_occ_8pipes.step")

    gmsh = _init_gmsh_model("pipes8")
    try:
        dimtags = _occ_dimtags_from_parts(pipe_parts)
        gmsh.model.occ.synchronize()
        n_vol = _count_volumes()
        _write_gmsh_step(step_path)
    finally:
        gmsh.finalize()

    return {
        "stage": 4,
        "artifacts": [step_path],
        "summary": {"pipe_bodies": len(pipe_parts), "occ_volumes": n_vol},
    }


def stage_5_pipes_fused(out_dir: str, *, q: float, af: float, n_segments: int) -> dict:
    _, nodes, beams, polylines = _build_lattice(q=q, af=af, n_segments=n_segments)
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    pipe_parts = [p for p in parts if p[0] == "pipe"]
    step_path = os.path.join(out_dir, "05_occ_8pipes_fused.step")

    gmsh = _init_gmsh_model("pipes_fused")
    try:
        dimtags = _occ_dimtags_from_parts(pipe_parts)
        gmsh.model.occ.synchronize()
        pipe_tags = list(dimtags)
        pipe_corners: list[tuple[tuple[float, float, float], float]] = []
        for _kind, path_pts, radius in pipe_parts:
            corner = tuple(float(x) for x in path_pts[-1])
            pipe_corners.append((corner, float(radius)))
        _configure_occ_for_fuse()
        _occ_fuse_pipe_tags(
            pipe_tags,
            pipe_endpoints=pipe_corners,
            progress_label="stage-5",
        )
        gmsh.model.occ.synchronize()
        from src.mesh.occ_pipe import prune_occ_for_step_export

        n_vol = prune_occ_for_step_export()
        _write_gmsh_step(step_path)
    finally:
        gmsh.finalize()

    return {
        "stage": 5,
        "artifacts": [step_path],
        "summary": {"occ_volumes_after_fuse": n_vol},
    }


def stage_6_fused_raw(out_dir: str, *, q: float, af: float, n_segments: int) -> dict:
    _, nodes, beams, polylines = _build_lattice(q=q, af=af, n_segments=n_segments)
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    step_path = os.path.join(out_dir, "06_occ_fused_pre_prune.step")

    gmsh = _init_gmsh_model("fused_raw")
    try:
        dimtags = _occ_dimtags_from_parts(parts)
        gmsh.model.occ.synchronize()
        _occ_fuse_lattice_primitives(parts, progress_label="stage-6")
        gmsh.model.occ.synchronize()
        n_vol = _count_volumes()
        _write_gmsh_step(step_path)
    finally:
        gmsh.finalize()

    return {
        "stage": 6,
        "artifacts": [step_path],
        "summary": {"occ_volumes_after_full_fuse": n_vol},
    }


def stage_7_final(out_dir: str, *, q: float, af: float, n_segments: int) -> dict:
    from src.export.export_sw import export_lattice_step_occ

    _, nodes, beams, polylines = _build_lattice(q=q, af=af, n_segments=n_segments)
    step_path = os.path.join(out_dir, "07_occ_final.step")
    try:
        report = export_lattice_step_occ(
            nodes,
            beams,
            step_path,
            polylines=polylines,
            junction_spheres=False,
            fuse=True,
        )
        sw_safe = report.get("step_solidworks_safe")
    except RuntimeError as exc:
        if not os.path.isfile(step_path):
            raise
        print(f"  [WARN] validation: {exc}", flush=True)
        sw_safe = False
        report = {"validation_error": str(exc)}

    return {
        "stage": 7,
        "artifacts": [step_path],
        "summary": {**report, "step_solidworks_safe": sw_safe},
    }


STAGE_FUNCS = {
    1: stage_1_topology,
    2: stage_2_primitives,
    3: stage_3_occ17,
    4: stage_4_pipes8,
    5: stage_5_pipes_fused,
    6: stage_6_fused_raw,
    7: stage_7_final,
}


def _print_stage_banner(stage: int) -> None:
    print(f"\n{'=' * 60}", flush=True)
    print(f"STAGE {stage}: {STAGE_HELP[stage]}", flush=True)
    print(f"{'=' * 60}", flush=True)
    print("请检查：", flush=True)
    for item in STAGE_CHECKS[stage]:
        print(f"  - {item}", flush=True)
    print(flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description="Step-by-step SFBLS unit-cell QA export")
    p.add_argument("--Q", type=float, default=0.5)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument("--out-dir", default="")
    p.add_argument(
        "--stage",
        type=int,
        choices=sorted(STAGE_FUNCS),
        required=True,
        help="Run a single stage (1–7)",
    )
    args = p.parse_args()

    ensure_output_dirs()
    out_dir = args.out_dir or _default_out_dir(float(args.Q))
    os.makedirs(out_dir, exist_ok=True)

    _print_stage_banner(int(args.stage))
    print(f"Output dir: {os.path.abspath(out_dir)}", flush=True)

    result = STAGE_FUNCS[int(args.stage)](
        out_dir,
        q=float(args.Q),
        af=float(args.Af),
        n_segments=int(args.n_segments),
    )

    print("\n生成的文件：", flush=True)
    for path in result["artifacts"]:
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        print(f"  {path}  ({size:,} bytes)", flush=True)

    if result.get("summary"):
        print(f"\n摘要: {json.dumps(result['summary'], ensure_ascii=False, indent=2)}", flush=True)

    progress_path = os.path.join(out_dir, "progress.json")
    progress: dict = {}
    if os.path.isfile(progress_path):
        with open(progress_path, encoding="utf-8") as fh:
            progress = json.load(fh)
    progress[f"stage_{args.stage}"] = {
        "done": True,
        "artifacts": [os.path.abspath(a) for a in result["artifacts"]],
        "summary": result.get("summary"),
    }
    with open(progress_path, "w", encoding="utf-8") as fh:
        json.dump(progress, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    next_stage = int(args.stage) + 1
    if next_stage in STAGE_FUNCS:
        print(
            f"\n确认无误后运行下一阶段：\n"
            f"  py -3 scripts/export_unitcell_stepwise_qa.py --Q {args.Q} --stage {next_stage}",
            flush=True,
        )
    else:
        print("\n全部 7 个阶段已完成。", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
