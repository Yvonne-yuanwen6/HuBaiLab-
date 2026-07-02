"""Batch CAE mesh-only for mesh convergence levels (no compression INP / solve)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.cae_mesh_runner import run_cae_mesh
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.mesh.mesh_convergence import Q05_MESH_CONVERGENCE_LEVELS, slug_for_q05_level
from src.paths import CAD_VERIFIED_ROOT, EXPORT_ROOT, PROJECT_ROOT


def _paper_box_cad(gen: HuBaiLatticeGenerator, cells: int) -> Path:
    slug = f"hu_bai_{gen.variant_name.lower()}_L{int(gen.cell_size)}_{cells}x{cells}x{cells}"
    path = CAD_VERIFIED_ROOT / f"{slug}_paper_box_array.step"
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Mesh-only batch for Q0.5 convergence levels")
    parser.add_argument("--Q", type=float, default=0.5)
    parser.add_argument("--mesh-locally", action="store_true")
    parser.add_argument("--remote-host", default="")
    parser.add_argument("--remote-root", default="")
    parser.add_argument("--level", default="", help="Single level id")
    parser.add_argument(
        "--write-json",
        default=str(PROJECT_ROOT / "output" / "reports" / "mesh_convergence" / "q05_mesh_manifests.json"),
    )
    args = parser.parse_args()

    gen = HuBaiLatticeGenerator(cell_size=20, rod_diameter=2, amplitude=2, period_factor=args.Q)
    cad = _paper_box_cad(gen, cells=4)
    if not cad.is_file():
        print(f"[ERROR] missing CAD: {cad}")
        return 1

    levels = list(Q05_MESH_CONVERGENCE_LEVELS)
    if args.level:
        levels = [lv for lv in levels if lv["id"] == args.level]
        if not levels:
            print(f"[ERROR] unknown level {args.level!r}")
            return 1

    rows: list[dict] = []
    for lv in levels:
        slug = slug_for_q05_level(lv)
        export_dir = EXPORT_ROOT / slug
        export_dir.mkdir(parents=True, exist_ok=True)
        out_inp = export_dir / f"{slug}_cae_mesh.inp"
        print(f"=== {lv['id']}: {lv['label']} -> {out_inp}")
        try:
            loc = run_cae_mesh(
                str(PROJECT_ROOT),
                str(cad),
                str(out_inp),
                float(lv["cae_seed_mm"]),
                "LATTICE",
                mesh_on_server=not args.mesh_locally,
                remote_host=args.remote_host,
                remote_root=args.remote_root,
                mesh_mode="tet",
                mesh_quality=str(lv["cae_mesh_quality"]),
                rod_diameter_mm=2.0,
                rods_per_diameter=float(lv["cae_rods_per_diameter"]),
                virtual_topology=True,
            )
            manifest = out_inp.with_name(f"{slug}_cae_mesh_manifest.json")
            row = {"level_id": lv["id"], "slug": slug, "mesh_location": loc, "inp": str(out_inp)}
            if manifest.is_file():
                row["manifest"] = json.loads(manifest.read_text(encoding="utf-8"))
            rows.append(row)
            print(f"  OK location={loc} elements={row.get('manifest', {}).get('element_count')}")
        except Exception as exc:
            print(f"  [ERROR] {exc}")
            rows.append({"level_id": lv["id"], "slug": slug, "error": str(exc)})

    os.makedirs(os.path.dirname(args.write_json) or ".", exist_ok=True)
    with open(args.write_json, "w", encoding="utf-8") as f:
        json.dump({"levels": rows}, f, indent=2, ensure_ascii=False)
    print("Wrote:", args.write_json)
    return 0 if all("error" not in r for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
