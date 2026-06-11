"""
Gmsh merge manual zslab_iz0..iz3.step → single solid STEP.

For multi-body layers (Q=1.5), fuses each layer to one body first, then inter-slab merge.

  py -3 scripts/merge_manual_zslabs_gmsh.py --Q 1.0
  py -3 scripts/merge_manual_zslabs_gmsh.py --manual-dir output/cad/manual/hu_bai_sfbls_af2q1_L20_4x4x4
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
    _configure_occ_for_fuse,
    _fuse_occ_layer_volumes,
    _lattice_cell_center_mm,
    _merge_step_solids_in_memory,
    _occ_fuse_sequential,
    _occ_list_volume_dimtags,
)
from src.export.sw_manual_merge import variant_dir_for_q
from src.mesh.occ_pipe import prune_occ_for_step_export


def _import_volume_count(step_path: str) -> int:
    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("count")
        gmsh.model.occ.importShapes(os.path.abspath(step_path))
        gmsh.model.occ.synchronize()
        return len(gmsh.model.getEntities(3))
    finally:
        gmsh.finalize()


def _fuse_multibody_layer_from_seed(
    manual_dir: str,
    iz: int,
    *,
    nx: int,
    ny: int,
    nz: int,
    L: float,
    step_out: str,
    label: str,
    resume: bool = True,
) -> str:
    """Rebuild one z-layer from unit-cell seed (16 OCC vols) and fuse without STEP re-import."""
    import gmsh

    seed = os.path.join(manual_dir, ".work_multibody", "unitcell_seed.step")
    if not os.path.isfile(seed):
        raise FileNotFoundError(f"Missing multibody seed: {seed}")

    if resume and os.path.isfile(step_out):
        n_out = _import_volume_count(step_out)
        if n_out == 1:
            print(
                f"  {label}: resume — reuse fused layer ({n_out} vol) -> {step_out}",
                flush=True,
            )
            return os.path.abspath(step_out)

    print(
        f"  {label}: rebuild {nx}x{ny} cells from seed + fuse -> {step_out}",
        flush=True,
    )
    os.makedirs(os.path.dirname(step_out) or ".", exist_ok=True)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(label.replace(" ", "_") or "layer_seed_fuse")
        gmsh.model.occ.importShapes(os.path.abspath(seed))
        gmsh.model.occ.synchronize()
        _configure_occ_for_fuse()

        seed_vols = _occ_list_volume_dimtags()
        if len(seed_vols) != 1:
            raise RuntimeError(f"{label}: seed must be 1 volume, got {len(seed_vols)}")
        seed_vol = seed_vols[0]

        for iy in range(ny):
            for ix in range(nx):
                dx = _lattice_cell_center_mm(ix, nx, L)
                dy = _lattice_cell_center_mm(iy, ny, L)
                dz = _lattice_cell_center_mm(iz, nz, L)
                copied = list(gmsh.model.occ.copy([seed_vol]))
                if abs(dx) > 1e-9 or abs(dy) > 1e-9 or abs(dz) > 1e-9:
                    gmsh.model.occ.translate(copied, float(dx), float(dy), float(dz))
                gmsh.model.occ.synchronize()

        gmsh.model.occ.remove([seed_vol], recursive=True)
        gmsh.model.occ.synchronize()
        vols = _occ_list_volume_dimtags()
        n_cells = nx * ny
        if len(vols) != n_cells:
            raise RuntimeError(f"{label}: expected {n_cells} volumes, got {len(vols)}")

        _fuse_occ_layer_volumes(vols, progress_label=label)
        prune_occ_for_step_export()
        if len(gmsh.model.getEntities(3)) != 1:
            raise RuntimeError(f"{label}: expected 1 volume after seed fuse")
        gmsh.write(step_out)
    finally:
        gmsh.finalize()
    return os.path.abspath(step_out)


def _fuse_step_to_single(step_in: str, step_out: str, *, label: str, resume: bool = True) -> str:
    import gmsh

    from src.export.export_sw import _configure_occ_for_fuse, _occ_list_volume_dimtags
    from src.mesh.occ_pipe import prune_occ_for_step_export

    n_in = _import_volume_count(step_in)
    if n_in <= 1:
        return os.path.abspath(step_in)

    if resume and os.path.isfile(step_out):
        n_out = _import_volume_count(step_out)
        if n_out == 1:
            print(
                f"  {label}: resume — reuse fused layer ({n_out} vol) -> {step_out}",
                flush=True,
            )
            return os.path.abspath(step_out)

    print(f"  {label}: fuse {n_in} OCC volume(s) in-layer -> {step_out}", flush=True)
    os.makedirs(os.path.dirname(step_out) or ".", exist_ok=True)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(label.replace(" ", "_") or "layer_fuse")
        gmsh.model.occ.importShapes(os.path.abspath(step_in))
        gmsh.model.occ.synchronize()
        _configure_occ_for_fuse()
        vols = _occ_list_volume_dimtags()
        if len(vols) > 1:
            if len(vols) > 32:
                _fuse_occ_layer_volumes(vols, progress_label=label)
            else:
                _occ_fuse_sequential(vols, progress_label=label, restrict_cleanup=True)
        prune_occ_for_step_export()
        if len(gmsh.model.getEntities(3)) != 1:
            raise RuntimeError(f"{label}: expected 1 volume after in-layer fuse")
        gmsh.write(step_out)
    finally:
        gmsh.finalize()
    return os.path.abspath(step_out)


def merge_manual_dir(manual_dir: str, out_step: str | None = None, *, resume: bool = True) -> dict:
    manual_dir = os.path.abspath(manual_dir)
    manifest_path = os.path.join(manual_dir, "manual_sw_manifest.json")
    manifest = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)

    slug = manifest.get("slug") or os.path.basename(manual_dir)
    block = manifest.get("block") or [4, 4, 4]
    nx, ny, nz = (int(block[0]), int(block[1]), int(block[2]))
    L = float(manifest.get("cell_size_mm") or 20.0)
    multibody = manifest.get("method") == "manual_sw_multibody_zslab"
    work = os.path.join(manual_dir, ".gmsh_merge")
    os.makedirs(work, exist_ok=True)
    if out_step is None:
        out_step = os.path.join(manual_dir, f"{slug}_solid_merged.step")
    out_step = os.path.abspath(out_step)

    if resume and os.path.isfile(out_step):
        n_merged = _import_volume_count(out_step)
        if n_merged == 1:
            print(f"OK: already merged ({n_merged} vol) -> {out_step}", flush=True)
            return {
                "slug": slug,
                "manual_dir": manual_dir,
                "merged_step": out_step,
                "solid_count": 1,
                "method": "gmsh_manual_zslab_merge",
                "resumed": True,
            }

    layer_inputs: list[str] = []
    for iz in range(nz):
        src = os.path.join(manual_dir, f"zslab_iz{iz}.step")
        if not os.path.isfile(src):
            raise FileNotFoundError(src)
        fused = os.path.join(work, f"zslab_iz{iz}_fused.step")
        if multibody:
            layer_inputs.append(
                _fuse_multibody_layer_from_seed(
                    manual_dir,
                    iz,
                    nx=nx,
                    ny=ny,
                    nz=nz,
                    L=L,
                    step_out=fused,
                    label=f"iz{iz}",
                    resume=resume,
                )
            )
            continue

        n = _import_volume_count(src)
        if n > 1:
            if n > nx * ny * 2:
                layer_inputs.append(
                    _fuse_multibody_layer_from_seed(
                        manual_dir,
                        iz,
                        nx=nx,
                        ny=ny,
                        nz=nz,
                        L=L,
                        step_out=fused,
                        label=f"iz{iz}",
                        resume=resume,
                    )
                )
            else:
                layer_inputs.append(_fuse_step_to_single(src, fused, label=f"iz{iz}", resume=resume))
        else:
            layer_inputs.append(os.path.abspath(src))

    print(f"Inter-slab merge ({len(layer_inputs)} layer(s)) -> {out_step}", flush=True)
    report = _merge_step_solids_in_memory(layer_inputs, out_step, progress_label="manual-gmsh")
    if int(report.get("solid_count") or 0) != 1:
        raise RuntimeError(f"Merge produced {report.get('solid_count')} volumes, expected 1")

    stats = {
        "slug": slug,
        "manual_dir": manual_dir,
        "merged_step": out_step,
        "layer_inputs": layer_inputs,
        "solid_count": report.get("solid_count"),
        "method": "gmsh_manual_zslab_merge",
    }
    manifest["merged_step"] = out_step
    manifest["gmsh_merge"] = stats
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"OK: {out_step} ({os.path.getsize(out_step)} bytes)", flush=True)
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description="Gmsh merge manual z-slabs")
    p.add_argument("--Q", type=float, default=None)
    p.add_argument("--manual-dir", default="")
    p.add_argument("--out-step", default="")
    p.add_argument("--force", action="store_true", help="Re-run even if fused/merged outputs exist")
    args = p.parse_args()

    if args.manual_dir:
        manual_dir = os.path.abspath(args.manual_dir)
    elif args.Q is not None:
        manual_dir = variant_dir_for_q(args.Q)
    else:
        print("[ERROR] Pass --Q or --manual-dir", file=sys.stderr)
        return 1

    try:
        merge_manual_dir(manual_dir, out_step=args.out_step or None, resume=not args.force)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
