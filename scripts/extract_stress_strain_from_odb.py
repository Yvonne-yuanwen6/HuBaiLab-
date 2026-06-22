"""
Extract engineering stress-strain from Abaqus ODB.

  abaqus python scripts\\extract_stress_strain_from_odb.py
  abaqus python scripts\\extract_stress_strain_from_odb.py --force-mode top_sum
"""

from __future__ import annotations

import argparse
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from odbAccess import openOdb  # type: ignore
except ImportError:
    print(
        "[ERROR] odbAccess not found. Run with Abaqus Python:\n"
        "  abaqus python scripts\\extract_stress_strain_from_odb.py"
    )
    sys.exit(1)

from src.postprocess.compression_curve import (
    build_curve_records,
    load_compression_meta,
    postprocess_history,
    write_curve_csv,
)
from src.postprocess.yield_strength import analyze_stress_strain_curve, save_yield_properties


def _default_paths_from_active_case() -> dict[str, str]:
    active = os.path.join(_ROOT, "output", "active_case.json")
    if not os.path.isfile(active):
        return {}
    try:
        from src.naming import load_case_manifest

        return load_case_manifest(active)
    except Exception:
        return {}


def _read_plate_ref_from_inp(inp_path: str) -> int | None:
    if not os.path.isfile(inp_path):
        return None
    with open(inp_path, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("*NSET") and "PLATE_REF" in line.upper():
            for j in range(i + 1, min(i + 4, len(lines))):
                row = lines[j].strip()
                if not row or row.startswith("*"):
                    break
                first = row.split(",")[0].strip()
                if first.isdigit():
                    return int(first)
    return None


def _resolve_ref_node_id(meta, root: str) -> int:
    ref_id = int(getattr(meta, "plate_ref_node_id", 0) or 0)
    if ref_id > 0:
        return ref_id
    active = _default_paths_from_active_case()
    if active.get("compression_inp"):
        ref_id = _read_plate_ref_from_inp(str(active["compression_inp"]))
        if ref_id:
            return ref_id
    raise ValueError(
        "plate_ref_node_id missing. Re-export INP (run_abaqus_export*.py) so meta includes plate_ref_node_id."
    )


def _region_has_rf_u3(region) -> bool:
    keys = region.historyOutputs.keys()
    return "RF3" in keys and "U3" in keys


def _history_series(region, key: str):
    if key not in region.historyOutputs:
        available = ", ".join(sorted(region.historyOutputs.keys()))
        raise KeyError(f"Missing '{key}' in historyOutputs. Available: {available}")
    out = region.historyOutputs[key]
    return [float(p[0]) for p in out.data], [float(p[1]) for p in out.data]


def _node_history_regions(step) -> list[tuple[int, str, object]]:
    """History regions like 'Node PART-1-1.118683' with RF3 and U3."""
    out: list[tuple[int, str, object]] = []
    pat = re.compile(r"^Node\s+.+\.(\d+)\s*$")
    for name, region in step.historyRegions.items():
        if not _region_has_rf_u3(region):
            continue
        m = pat.match(name.strip())
        if m:
            out.append((int(m.group(1)), name, region))
    return out


def _find_history_region(step, odb, ref_node_id: int, history_tag: str):
    tag_upper = history_tag.upper()

    for name, region in step.historyRegions.items():
        if tag_upper in name.upper() and _region_has_rf_u3(region):
            return region, name

    node_hist = _node_history_regions(step)
    if ref_node_id:
        for lid, name, region in node_hist:
            if lid == int(ref_node_id):
                return region, name

    if len(node_hist) == 1:
        lid, name, region = node_hist[0]
        if ref_node_id and lid != int(ref_node_id):
            print(
                f"[WARN] meta plate_ref_node_id={ref_node_id} != ODB node {lid}; "
                "using ODB (geometry/INP changed — re-run job for matching meta)."
            )
        return region, name

    for lid, name, region in node_hist:
        if ref_node_id and lid != int(ref_node_id):
            return region, name

    keys = ", ".join(sorted(step.historyRegions.keys())[:15])
    raise KeyError(
        f"No history region for PLATE_REF (meta id={ref_node_id}, "
        f"node histories={len(node_hist)}). Sample keys: {keys}"
    )


def _resolve_node_set(assembly, *hints: str):
    """Find node set by exact / case / substring match (Abaqus renames sets in ODB)."""
    keys = list(assembly.nodeSets.keys())
    for hint in hints:
        if hint in assembly.nodeSets:
            return assembly.nodeSets[hint], hint
    upper_map = {k.upper(): k for k in keys}
    for hint in hints:
        hu = hint.upper()
        if hu in upper_map:
            k = upper_map[hu]
            return assembly.nodeSets[k], k
    for hint in hints:
        hu = hint.upper()
        for k in keys:
            if hu in k.upper():
                return assembly.nodeSets[k], k
    return None, None


def _node_labels_from_set(odb, set_name: str) -> set[int]:
    assembly = odb.rootAssembly
    nset, _ = _resolve_node_set(assembly, set_name)
    if nset is None:
        return set()
    return {int(n.label) for n in nset.nodes}


def _bottom_nodes_by_z(assembly, z_cutoff: float) -> list[tuple[str, int]]:
    """Fallback: all mesh nodes with initial z <= z_cutoff."""
    found: list[tuple[str, int]] = []
    for inst_name, inst in assembly.instances.items():
        for n in inst.nodes:
            z = float(n.coordinates[2])
            if z <= z_cutoff + 1e-6:
                found.append((inst_name, int(n.label)))
    return found


def _sum_nset_rf3_history(step, labels: set[int]) -> tuple[list[float], list[float], int]:
    """Sum RF3 history over all nodes whose label is in ``labels``."""
    if not labels:
        return [], [], 0

    label_pat = re.compile(r"\.(\d+)\s*$")
    series: list[tuple[list[float], list[float]]] = []

    for name, region in step.historyRegions.items():
        if not _region_has_rf_u3(region):
            continue
        m = label_pat.search(name)
        if not m or int(m.group(1)) not in labels:
            continue
        t, rf = _history_series(region, "RF3")
        series.append((t, rf))

    if not series:
        return [], [], 0

    times = series[0][0]
    n = len(times)
    rf_sum = [0.0] * n
    for t, rf in series:
        if len(t) != n:
            raise ValueError("Top-node RF3 history time bases differ; re-export with uniform interval")
        for i in range(n):
            rf_sum[i] += rf[i]

    return times, rf_sum, len(series)


def _resolve_fixed_ref_node_id(meta, root: str) -> int:
    ref_id = int(getattr(meta, "plate_fixed_ref_node_id", 0) or 0)
    if ref_id > 0:
        return ref_id
    active = _default_paths_from_active_case()
    inp_path = active.get("compression_inp", "")
    if inp_path and os.path.isfile(inp_path):
        with open(inp_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.strip().upper().startswith("*NSET") and "PLATE_FIXED_REF" in line.upper():
                for j in range(i + 1, min(i + 4, len(lines))):
                    row = lines[j].strip()
                    if not row or row.startswith("*"):
                        break
                    first = row.split(",")[0].strip()
                    if first.isdigit():
                        return int(first)
    return 0


def _extract_plate_ref(step, odb, ref_node_id: int, *, source: str = "paper_top_plate"):
    region, name = _find_history_region(step, odb, ref_node_id, "PLATE_REF")
    times, u3 = _history_series(region, "U3")
    _, rf3 = _history_series(region, "RF3")
    return times, u3, rf3, name, source


def _extract_fixed_bottom_ref(step, odb, ref_node_id: int):
    region, name = _find_history_region(step, odb, ref_node_id, "PLATE_FIXED_REF")
    times, u3 = _history_series(region, "U3")
    _, rf3 = _history_series(region, "RF3")
    return times, u3, rf3, name, "paper_bottom_plate"


def _extract_top_sum(step, odb):
    labels = _node_labels_from_set(odb, "LATTICE_TOP_NODES")
    times, rf_sum, n_regions = _sum_nset_rf3_history(step, labels)

    if n_regions == 0:
        raise ValueError(
            "No LATTICE_TOP_NODES RF3 history in ODB. "
            "Use --force-mode plate_ref, or re-run with history_lattice_top_nodes=True (large ODB)."
        )

    ref_id = 0
    plate_nset, _ = _resolve_node_set(odb.rootAssembly, "PLATE_REF", "PLATE")
    try:
        ref_id = int(plate_nset.nodes[0].label) if plate_nset else 0
    except (AttributeError, IndexError):
        ref_id = 0
    if ref_id:
        times, u3, _, u_name, _ = _extract_plate_ref(step, odb, ref_id, source="top_sum_u3")
    else:
        u_name = "PLATE_REF U3 (missing)"
        u3 = [0.0] * len(times)

    if len(u3) != len(times):
        raise ValueError("U3 and summed RF3 point counts differ")

    return times, u3, rf_sum, f"sum({n_regions}) LATTICE_TOP_NODES RF3; U3 from {u_name}", "top_sum"


def _sum_rf3_from_field(step, assembly, bottom_region, bottom_label: str):
    plate, plate_label = _resolve_node_set(assembly, "PLATE_REF", "PLATE")
    if plate is None:
        raise ValueError(
            f"PLATE_REF not in ODB node sets. Available: {list(assembly.nodeSets.keys())[:25]}"
        )

    lookup: set[tuple[str, int]] | None = None
    if isinstance(bottom_region, list):
        lookup = set(bottom_region)

    times: list[float] = []
    u3_list: list[float] = []
    rf_list: list[float] = []

    for frame in step.frames:
        if "RF" not in frame.fieldOutputs or "U" not in frame.fieldOutputs:
            continue

        rf3_sum = 0.0
        if lookup is not None:
            for v in frame.fieldOutputs["RF"].values:
                inst = v.instance.name if v.instance else ""
                key = (inst, int(v.nodeLabel))
                if key in lookup:
                    rf3_sum += float(v.data[2])
        else:
            rf_sub = frame.fieldOutputs["RF"].getSubset(region=bottom_region)
            rf3_sum = sum(float(v.data[2]) for v in rf_sub.values)

        u_sub = frame.fieldOutputs["U"].getSubset(region=plate)
        if not u_sub.values:
            continue

        u3 = float(u_sub.values[0].data[2])
        times.append(float(frame.frameValue))
        rf_list.append(abs(rf3_sum))
        u3_list.append(u3)

    if len(times) < 3:
        raise ValueError(
            "Too few field frames with RF/U on bottom/plate. "
            "Try --force-mode plate_ref or re-export INP with BOTTOM_FIX RF field output."
        )

    return times, u3_list, rf_list, f"sum({bottom_label}) field RF3; U3 field {plate_label}", "bottom_field"


def _extract_bottom_field(step, odb, ref_node_id: int, meta):
    """Sum RF3 on bottom nodes from field frames; U3 from PLATE_REF field."""
    assembly = odb.rootAssembly
    bottom, bottom_label = _resolve_node_set(assembly, "BOTTOM_FIX", "BOTTOM")

    if bottom is None:
        z_cut = float(meta.mesh_z_min) + max(0.02 * meta.cell_size, 0.5)
        node_list = _bottom_nodes_by_z(assembly, z_cut)
        if len(node_list) < 10:
            keys = ", ".join(list(assembly.nodeSets.keys())[:20])
            raise ValueError(
                f"BOTTOM_FIX not in ODB and z-cutoff found {len(node_list)} nodes. "
                f"Node sets sample: {keys}"
            )
        return _sum_rf3_from_field(
            step,
            assembly,
            node_list,
            f"z<={z_cut:.3g}mm ({len(node_list)} nodes)",
        )

    return _sum_rf3_from_field(step, assembly, bottom, bottom_label)


def extract_from_odb(
    odb_path: str,
    meta_path: str,
    csv_path: str,
    *,
    force_mode: str = "paper",
    curve_method: str = "paper",
    step_name: str | None = None,
    root: str | None = None,
    trim_hold: bool = True,
    drop_spike: bool = True,
    raw_csv_path: str | None = None,
    yield_json_path: str | None = None,
) -> list[dict[str, float]]:
    meta = load_compression_meta(meta_path)
    step_name = step_name or meta.step_name
    root = root or _ROOT
    ref_node_id = _resolve_ref_node_id(meta, root)
    fixed_ref_node_id = _resolve_fixed_ref_node_id(meta, root)

    odb = openOdb(path=odb_path, readOnly=True)
    try:
        if step_name not in odb.steps:
            available = ", ".join(odb.steps.keys())
            raise KeyError(f"Step '{step_name}' not in ODB. Available: {available}")
        step = odb.steps[step_name]

        mode = force_mode.lower()
        if mode in ("paper", "plate_ref", "top_plate"):
            times, u3, rf3, region_name, source = _extract_plate_ref(
                step, odb, ref_node_id, source="paper_top_plate"
            )
        elif mode in ("fixed_bottom_ref", "bottom_plate", "paper_bottom"):
            if fixed_ref_node_id <= 0:
                raise ValueError("plate_fixed_ref_node_id missing in meta/INP")
            top_times, top_u3, _, _, _ = _extract_plate_ref(
                step, odb, ref_node_id, source="paper_top_plate"
            )
            times, _, rf3, region_name, source = _extract_fixed_bottom_ref(
                step, odb, fixed_ref_node_id
            )
            u3 = top_u3
            if len(u3) != len(times):
                raise ValueError("Top U3 and bottom RF3 history lengths differ")
        elif mode == "top_sum":
            times, u3, rf3, region_name, source = _extract_top_sum(step, odb)
        elif mode == "bottom_field":
            try:
                times, u3, rf3, region_name, source = _extract_bottom_field(
                    step, odb, ref_node_id, meta
                )
            except Exception as exc:
                print(f"[WARN] bottom_field failed ({exc}); fallback to paper top plate.")
                times, u3, rf3, region_name, source = _extract_plate_ref(
                    step, odb, ref_node_id, source="paper_top_plate"
                )
        else:
            raise ValueError(f"Unknown force_mode: {force_mode}")
    finally:
        odb.close()

    if raw_csv_path:
        raw_rows = build_curve_records(
            times, u3, rf3, meta, force_source=f"{source}_raw", method=curve_method
        )
        write_curve_csv(raw_rows, raw_csv_path)

    t2, u2, r2 = postprocess_history(
        times,
        u3,
        rf3,
        meta,
        trim_hold=trim_hold,
        drop_spike=drop_spike,
        method=curve_method,
    )
    rows = build_curve_records(t2, u2, r2, meta, force_source=source, method=curve_method)
    write_curve_csv(rows, csv_path)

    print(f"Force mode: {source}")
    print(f"Region: {region_name}")
    print(f"PLATE_REF node id: {ref_node_id}")
    if trim_hold:
        print(f"Trimmed hold: t < {meta.hold_end_time():.4g} s")
    if drop_spike and curve_method.lower() == "paper":
        print("Paper method: kept load-onset points (no RF spike filter)")
    elif drop_spike:
        print("Removed load-start RF spikes (large RF at near-zero displacement)")
    print(f"Points: {len(times)} raw -> {len(rows)} processed")
    print(f"CSV: {csv_path}")
    if raw_csv_path:
        print(f"Raw CSV: {raw_csv_path}")
    if rows:
        last = rows[-1]
        print(
            f"Last: strain={last['engineering_strain']:.6f}, "
            f"stress={last['engineering_stress_MPa']:.4f} MPa, RF3={last['RF3_N']:.2f} N"
        )
    if yield_json_path and rows:
        strains = [r["engineering_strain"] for r in rows]
        stresses = [r["engineering_stress_MPa"] for r in rows]
        try:
            props = analyze_stress_strain_curve(strains, stresses)
            save_yield_properties(props, yield_json_path)
            print(f"Yield (0.2% offset): {props['yield_stress_MPa']:.4f} MPa @ strain {props['yield_strain']:.5f}")
            print(f"Ultimate: {props['ultimate_stress_MPa']:.4f} MPa @ strain {props['ultimate_strain']:.5f}")
            print(f"Elastic modulus (fit): {props['elastic_modulus_MPa']:.4f} MPa")
            print(f"Saved: {yield_json_path}")
        except Exception as exc:
            print(f"[WARN] Yield analysis failed: {exc}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract stress-strain CSV from ODB")
    parser.add_argument("--odb", default="")
    parser.add_argument("--meta", default="")
    parser.add_argument("--csv", default="")
    parser.add_argument("--raw-csv", default="")
    parser.add_argument("--step", default=None)
    parser.add_argument(
        "--force-mode",
        choices=(
            "paper",
            "plate_ref",
            "top_plate",
            "fixed_bottom_ref",
            "bottom_plate",
            "top_sum",
            "bottom_field",
        ),
        default="paper",
        help="paper: top PLATE_REF RF3 + U3 (Hu & Bai Fig.3.3); fixed_bottom_ref: bottom reaction",
    )
    parser.add_argument(
        "--curve-method",
        choices=("paper", "legacy"),
        default="paper",
        help="paper: sigma=F/(nx*L*ny*L), eps=S/(nz*L), no RF spike filter",
    )
    parser.add_argument(
        "--yield-json",
        default="",
        help="Write 0.2%% offset yield etc. to JSON (optional path)",
    )
    parser.add_argument("--no-trim-hold", action="store_true")
    parser.add_argument("--no-drop-spike", action="store_true")
    parser.add_argument("--no-raw", action="store_true", help="Do not write raw CSV")
    args = parser.parse_args()

    defaults = _default_paths_from_active_case()
    if defaults:
        if not args.odb:
            args.odb = defaults.get("odb", "")
        if not args.meta:
            args.meta = defaults.get("meta_json", "")
        if not args.csv:
            args.csv = defaults.get("stress_strain_csv", "")
        if not args.raw_csv:
            args.raw_csv = defaults.get("stress_strain_raw_csv", "")
        if not args.yield_json and defaults.get("yield_json"):
            args.yield_json = defaults["yield_json"]

    if not args.odb or not args.meta or not args.csv:
        print("[ERROR] Missing --odb/--meta/--csv. Run export script first or pass explicit paths.")
        return 1
    if not os.path.isfile(args.odb):
        print(f"[ERROR] ODB not found: {args.odb}")
        return 1
    if not os.path.isfile(args.meta):
        print(f"[ERROR] Meta not found: {args.meta}")
        return 1

    try:
        extract_from_odb(
            args.odb,
            args.meta,
            args.csv,
            force_mode=args.force_mode,
            curve_method=args.curve_method,
            step_name=args.step,
            trim_hold=not args.no_trim_hold,
            drop_spike=not args.no_drop_spike,
            raw_csv_path=None if args.no_raw else args.raw_csv,
            yield_json_path=args.yield_json or None,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
