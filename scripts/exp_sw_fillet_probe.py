"""
SolidWorks COM fillet probe on bare hard STEP (Q=1 / Q=1.5).

Requires SolidWorks already running.

  py -3 scripts/exp_sw_fillet_probe.py
  py -3 scripts/exp_sw_fillet_probe.py --qs 1.0 1.5 --r 0.30 0.25 0.20
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.sw_parasolid import _connect_solidworks, _doc_title, _sw_com_value


def _open_step(sw_app, step_path: str):
    """Open STEP using the same routes as convert_step_to_xt (SW 2025-safe)."""
    import pythoncom
    import win32com.client

    step_path = os.path.abspath(step_path)
    model = None
    last_err: Exception | None = None

    # Prefer LoadFile2 — OpenDoc6 often RPC-crashes on OCC STEP in SW 2025.
    for suffix in ("r", ""):
        try:
            ok = sw_app.LoadFile2(step_path, suffix)
            if ok:
                time.sleep(0.8)
                try:
                    model = sw_app.ActiveDoc
                except Exception:
                    model = None
                if model is None:
                    try:
                        model = sw_app.IActiveDoc2
                    except Exception:
                        model = None
                if model is None:
                    try:
                        model = sw_app.GetFirstDocument
                        if callable(model):
                            model = model()
                    except Exception:
                        model = None
                if model is not None:
                    return model
        except Exception as exc:
            last_err = exc

    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    for opts in (1, 0):
        try:
            model = sw_app.OpenDoc6(step_path, 1, opts, "", errors, warnings)
            if model is not None:
                return model
            last_err = RuntimeError(
                f"OpenDoc6 Nothing (errors={int(errors.value)}, warnings={int(warnings.value)})"
            )
        except Exception as exc:
            last_err = exc

    raise RuntimeError(f"SW failed to open {step_path}") from last_err


def _edge_midpoint_mm(edge) -> tuple[float, float, float] | None:
    """Best-effort edge midpoint in model mm."""
    try:
        params = edge.GetCurveParams2
        if callable(params):
            params = params()
        # Typical: startXYZ + endXYZ (+ extras)
        if params is not None and len(params) >= 6:
            return (
                0.5 * (float(params[0]) + float(params[3])),
                0.5 * (float(params[1]) + float(params[4])),
                0.5 * (float(params[2]) + float(params[5])),
            )
    except Exception:
        pass
    try:
        # Fallback: average of vertices
        verts = edge.GetVertices
        if callable(verts):
            verts = verts()
        if verts and len(verts) >= 2:
            p0 = verts[0].GetPoint
            p1 = verts[1].GetPoint
            if callable(p0):
                p0 = p0()
            if callable(p1):
                p1 = p1()
            return (
                0.5 * (float(p0[0]) + float(p1[0])),
                0.5 * (float(p0[1]) + float(p1[1])),
                0.5 * (float(p0[2]) + float(p1[2])),
            )
    except Exception:
        pass
    return None


def _edge_length_mm(edge) -> float | None:
    try:
        L = edge.GetLength2 if hasattr(edge, "GetLength2") else None
        if L is None:
            return None
        if callable(L):
            # GetLength2(startParam, endParam) — try GetLength
            pass
        # GetLength(ByRef start, ByRef end) awkward in pywin32; use curve params
        params = edge.GetCurveParams2
        if callable(params):
            params = params()
        if params is not None and len(params) >= 6:
            dx = float(params[3]) - float(params[0])
            dy = float(params[4]) - float(params[1])
            dz = float(params[5]) - float(params[2])
            return math.sqrt(dx * dx + dy * dy + dz * dz)
    except Exception:
        pass
    return None


def _collect_hub_edges(model, *, hub_r_mm: float, max_len_mm: float):
    try:
        bodies = model.GetBodies2(0, False)  # swSolidBody=0
    except Exception:
        try:
            bodies = model.GetBodies2(0)
        except Exception as exc:
            raise RuntimeError(f"GetBodies2 failed: {exc}") from exc
    if not bodies:
        raise RuntimeError("no solid bodies in SW doc")
    body = bodies[0]
    edges = body.GetEdges
    if callable(edges):
        edges = edges()
    if not edges:
        raise RuntimeError("no edges on body")

    # SW geometry API returns metres
    hub_r_m = float(hub_r_mm) / 1000.0
    max_len_m = float(max_len_mm) / 1000.0
    min_len_m = 0.15 / 1000.0

    selected = []
    for edge in edges:
        mid = _edge_midpoint_mm(edge)  # metres (legacy name)
        if mid is None:
            continue
        r_m = math.sqrt(mid[0] ** 2 + mid[1] ** 2 + mid[2] ** 2)
        if r_m > hub_r_m:
            continue
        elen_m = _edge_length_mm(edge)
        if elen_m is not None and elen_m > max_len_m:
            continue
        if elen_m is not None and elen_m < min_len_m:
            continue
        selected.append(
            (
                edge,
                r_m * 1000.0,
                (elen_m * 1000.0) if elen_m is not None else None,
                mid,
            )
        )
    selected.sort(
        key=lambda t: (
            float(t[2]) if t[2] is not None else 99.0,
            float(t[1]),
        )
    )
    return selected


def _clear_selection(model) -> None:
    try:
        model.ClearSelection2(True)
    except Exception:
        try:
            model.ClearSelection2
        except Exception:
            pass


def _select_edges(model, edge_infos: list) -> int:
    """
    Select edges with Mark=1 (required by FeatureFillet3).

    Midpoints in ``edge_infos`` are metres (SW native).
    Prefer Edge.Select2 — Select4/SelectByID2 type-mismatch on SW 2025 CN.
    """
    _clear_selection(model)
    ext = model.Extension
    n = 0
    for i, item in enumerate(edge_infos):
        edge = item[0]
        mid = item[3] if len(item) > 3 else None
        ok = False
        append = bool(i > 0)
        # 1) Select2(Append, Mark) — works on SW 2025
        try:
            ok = bool(edge.Select2(append, 1))
        except Exception:
            ok = False
        # 2) SelectByRay toward midpoint
        if not ok and mid is not None:
            x, y, z = float(mid[0]), float(mid[1]), float(mid[2])
            try:
                ok = bool(
                    ext.SelectByRay(x, y, z + 0.01, 0.0, 0.0, -1.0, 0.001, 1, append, 0, 0)
                )
            except Exception:
                ok = False
        # 3) SelectByID2 last
        if not ok and mid is not None:
            x, y, z = float(mid[0]), float(mid[1]), float(mid[2])
            try:
                ok = bool(ext.SelectByID2("", "EDGE", x, y, z, append, 1, None, 0))
            except Exception:
                ok = False
        if ok:
            n += 1
    return n


def _empty_variant_array():
    import pythoncom
    import win32com.client

    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, [])


def _insert_fillet(model, radius_mm: float) -> bool:
    """FeatureFillet3 with uniform radius (API units = metres)."""
    fm = model.FeatureManager
    r_m = float(radius_mm) / 1000.0
    trials = []
    empty = _empty_variant_array()

    def _call(name, fn):
        try:
            feat = fn()
            ok = feat is not None
            trials.append((name, ok, None if ok else "Nothing"))
            return ok
        except Exception as exc:
            trials.append((name, False, str(exc)[:200]))
            return False

    if hasattr(fm, "FeatureFillet3"):
        # opts=2 works on SW 2025 CN for single-edge selection
        for opts in (2, 195):
            if _call(
                f"FeatureFillet3_opts{opts}",
                lambda o=opts: fm.FeatureFillet3(
                    o,
                    r_m,
                    r_m,
                    0.0,
                    0,
                    0,
                    0,
                    empty,
                    empty,
                    empty,
                    empty,
                    empty,
                    empty,
                    empty,
                ),
            ):
                return True

    if trials:
        print(f"  [swFillet] FeatureFillet trials: {trials}", flush=True)
    return False


def _save_as(model, path: str) -> None:
    swSaveAsCurrentVersion = 0
    swSaveAsOptions_Silent = 1
    ok = model.SaveAs3(path, swSaveAsCurrentVersion, swSaveAsOptions_Silent)
    if not os.path.isfile(path) or os.path.getsize(path) < 500:
        raise RuntimeError(f"SaveAs3 failed for {path} return={ok!r}")


def _edge_endpoints_m(edge) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    try:
        params = edge.GetCurveParams2
        if callable(params):
            params = params()
        if params is not None and len(params) >= 6:
            return (
                (float(params[0]), float(params[1]), float(params[2])),
                (float(params[3]), float(params[4]), float(params[5])),
            )
    except Exception:
        pass
    return None


def _chain_hub_edges_by_planes_sw(
    hub_edges: list,
    plane_normals: dict[str, list[float]],
    *,
    max_plane_dist_mm: float = 1.6,
    gap_tol_mm: float = 0.15,
) -> list[list]:
    """
    Cluster SW hub edges onto bot/top/cross planes, then chain by endpoint gap.
    Midpoints/endpoints in hub_edges are metres.
    """
    if not plane_normals or not hub_edges:
        return []

    groups: dict[str, list] = {g: [] for g in plane_normals}
    for info in hub_edges:
        mid_m = info[3]
        if mid_m is None:
            continue
        mid_mm = (
            float(mid_m[0]) * 1000.0,
            float(mid_m[1]) * 1000.0,
            float(mid_m[2]) * 1000.0,
        )
        best_g = None
        best_d = 1e9
        for g, n in plane_normals.items():
            d = abs(
                mid_mm[0] * float(n[0])
                + mid_mm[1] * float(n[1])
                + mid_mm[2] * float(n[2])
            )
            if d < best_d:
                best_d = d
                best_g = g
        if best_g is None or best_d > float(max_plane_dist_mm):
            continue
        ends = _edge_endpoints_m(info[0])
        groups[best_g].append(
            {
                "info": info,
                "p0_mm": (
                    (ends[0][0] * 1000.0, ends[0][1] * 1000.0, ends[0][2] * 1000.0)
                    if ends
                    else mid_mm
                ),
                "p1_mm": (
                    (ends[1][0] * 1000.0, ends[1][1] * 1000.0, ends[1][2] * 1000.0)
                    if ends
                    else mid_mm
                ),
            }
        )

    def _dist(a, b) -> float:
        return math.sqrt(
            (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
        )

    chains_out: list[list] = []
    gap = float(gap_tol_mm)
    for g, items in groups.items():
        n = len(items)
        if n == 0:
            continue
        adj = [set() for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                pts_i = (items[i]["p0_mm"], items[i]["p1_mm"])
                pts_j = (items[j]["p0_mm"], items[j]["p1_mm"])
                linked = False
                for a in pts_i:
                    for b in pts_j:
                        if _dist(a, b) <= gap:
                            linked = True
                            break
                    if linked:
                        break
                if linked:
                    adj[i].add(j)
                    adj[j].add(i)
        visited = [False] * n
        for i in range(n):
            if visited[i]:
                continue
            stack = [i]
            visited[i] = True
            members = []
            while stack:
                u = stack.pop()
                members.append(u)
                for v in adj[u]:
                    if not visited[v]:
                        visited[v] = True
                        stack.append(v)
            chains_out.append([items[k]["info"] for k in members])

    chains_out.sort(key=lambda c: -len(c))
    return chains_out


def _load_plane_normals(diagnose_path: str | None) -> dict[str, list[float]]:
    if not diagnose_path or not os.path.isfile(diagnose_path):
        return {}
    with open(diagnose_path, encoding="utf-8") as f:
        diag = json.load(f)
    raw = diag.get("plane_normals") or {}
    return {str(k): [float(x) for x in v] for k, v in raw.items() if v}


def _match_chains_to_hub_edges(
    hub_edges: list,
    chain_targets: list[dict],
    *,
    tol_mm: float = 0.25,
) -> list[list]:
    """
    Map OCC chain midpoints (mm) to SW hub edge infos.
    SW midpoints in edge_infos are metres.
    """
    used = set()
    chains_out: list[list] = []
    for ct in chain_targets:
        mids = ct.get("mids_mm") or []
        matched = []
        for mid_mm in mids:
            mx, my, mz = (float(mid_mm[0]), float(mid_mm[1]), float(mid_mm[2]))
            best_i = None
            best_d = 1e9
            for i, info in enumerate(hub_edges):
                if i in used:
                    continue
                # info[3] is mid in metres
                mid_m = info[3]
                if mid_m is None:
                    continue
                dx = float(mid_m[0]) * 1000.0 - mx
                dy = float(mid_m[1]) * 1000.0 - my
                dz = float(mid_m[2]) * 1000.0 - mz
                d = math.sqrt(dx * dx + dy * dy + dz * dz)
                if d < best_d:
                    best_d = d
                    best_i = i
            if best_i is not None and best_d <= float(tol_mm):
                used.add(best_i)
                matched.append(hub_edges[best_i])
        if matched:
            chains_out.append(matched)
    return chains_out


def fillet_one(
    step_path: str,
    *,
    out_dir: str,
    radii_mm: list[float],
    hub_r_mm: float,
    max_edge_len_mm: float,
    max_edges: int,
    visible: bool,
    chain_targets_path: str | None = None,
    main_chain_only: bool = False,
    max_chains: int = 2,
) -> dict:
    import pythoncom

    pythoncom.CoInitialize()
    sw_app = None
    model = None
    row: dict = {
        "step_in": os.path.abspath(step_path),
        "ok": False,
        "fillet": "sw_fillet",
        "error": None,
    }
    chain_targets: list[dict] = []
    diagnose_path: str | None = None
    if chain_targets_path and os.path.isfile(chain_targets_path):
        with open(chain_targets_path, encoding="utf-8") as f:
            chain_targets = json.load(f)
        row["chain_targets_path"] = os.path.abspath(chain_targets_path)
        row["fillet"] = (
            "sw_plane_chain_main_only"
            if main_chain_only
            else "sw_plane_chain_fillet"
        )
        # sibling diagnose JSON for plane normals
        diagnose_path = chain_targets_path.replace(
            "_chain_targets.json", "_diagnose.json"
        )
        if not os.path.isfile(diagnose_path):
            diagnose_path = None

    def _build_chains(hub_edges_local):
        plane_ns_local = _load_plane_normals(diagnose_path)
        chains_local = []
        if plane_ns_local:
            chains_local = _chain_hub_edges_by_planes_sw(
                hub_edges_local,
                plane_ns_local,
                max_plane_dist_mm=1.6,
                gap_tol_mm=0.15,
            )
            print(
                f"  [swFillet] SW plane chains={len(chains_local)} "
                f"(edges {[len(c) for c in chains_local]})",
                flush=True,
            )
        if not chains_local and chain_targets:
            chains_local = _match_chains_to_hub_edges(hub_edges_local, chain_targets)
            print(
                f"  [swFillet] OCC mid chains matched={len(chains_local)} "
                f"(edges {[len(c) for c in chains_local]})",
                flush=True,
            )
        if not chains_local:
            return []
        # Longest chains first
        chains_local = sorted(chains_local, key=lambda c: -len(c))
        if main_chain_only:
            # Keep only the top N full chains (typically bot+top); no leftover.
            take_n = max(1, int(max_chains))
            chains_local = [c for c in chains_local if len(c) >= 2][:take_n]
            print(
                f"  [swFillet] main-chain-only → {len(chains_local)} chains "
                f"{[len(c) for c in chains_local]}",
                flush=True,
            )
            return chains_local
        budget = max(1, int(max_edges))
        capped: list[list] = []
        n_take = 0
        for ch in chains_local:
            if n_take >= budget:
                break
            room = budget - n_take
            capped.append(ch[:room])
            n_take += len(capped[-1])
        return [c for c in capped if c]

    try:
        sw_app = _connect_solidworks(allow_start=False)
        try:
            sw_app.Visible = bool(visible)
        except Exception:
            pass

        print(f"  [swFillet] open {step_path}", flush=True)
        model = _open_step(sw_app, os.path.abspath(step_path))
        time.sleep(0.5)

        hub_edges = _collect_hub_edges(
            model, hub_r_mm=hub_r_mm, max_len_mm=max_edge_len_mm
        )
        print(
            f"  [swFillet] hub candidate edges={len(hub_edges)} "
            f"(hub_r={hub_r_mm:g} max_len={max_edge_len_mm:g})",
            flush=True,
        )
        if not hub_edges:
            raise RuntimeError("no hub edges found for fillet")

        chains = _build_chains(hub_edges)

        base = os.path.splitext(os.path.basename(step_path))[0]
        last_err = None

        for ri, r in enumerate(radii_mm):
            if ri > 0:
                try:
                    title = _doc_title(model)
                    if title:
                        sw_app.CloseDoc(title)
                except Exception:
                    pass
                model = _open_step(sw_app, os.path.abspath(step_path))
                time.sleep(0.4)
                hub_edges = _collect_hub_edges(
                    model, hub_r_mm=hub_r_mm, max_len_mm=max_edge_len_mm
                )
                chains = _build_chains(hub_edges)

            n_ok = 0
            n_attempted = 0
            n_whole_chain_ok = 0
            mode_used = "sequential_edges"

            if chains:
                mode_used = "main_chain_only" if main_chain_only else "plane_chain"
                print(
                    f"  [swFillet] chain fillet r={r:g} mm on {len(chains)} chains "
                    f"(main_only={main_chain_only}) ...",
                    flush=True,
                )
                for ci, chain in enumerate(chains):
                    n_attempted += len(chain)
                    # Prefer whole-chain FeatureFillet3; fall back per-edge
                    n_sel = _select_edges(model, chain)
                    chain_ok = False
                    if n_sel == len(chain) and _insert_fillet(model, r):
                        chain_ok = True
                        n_ok += len(chain)
                        n_whole_chain_ok += 1
                        print(
                            f"    chain#{ci}: OK whole ({len(chain)} edges)",
                            flush=True,
                        )
                    else:
                        print(
                            f"    chain#{ci}: whole fail → sequential",
                            flush=True,
                        )
                        for idx, info in enumerate(chain):
                            n_sel = _select_edges(model, [info])
                            if n_sel < 1:
                                print(f"      edge#{idx}: select fail", flush=True)
                                continue
                            if not _insert_fillet(model, r):
                                print(f"      edge#{idx}: fillet fail", flush=True)
                                continue
                            try:
                                model.EditRebuild3()
                            except Exception:
                                try:
                                    model.ForceRebuild3(False)
                                except Exception:
                                    pass
                            n_ok += 1
                            print(f"      edge#{idx}: OK (total {n_ok})", flush=True)
                    if chain_ok:
                        try:
                            model.EditRebuild3()
                        except Exception:
                            try:
                                model.ForceRebuild3(False)
                            except Exception:
                                pass

                # Leftover sequential only when NOT main-chain-only
                if not main_chain_only:
                    try:
                        hub_edges = _collect_hub_edges(
                            model, hub_r_mm=hub_r_mm, max_len_mm=max_edge_len_mm
                        )
                    except Exception as exc:
                        print(f"  [swFillet] re-collect after chains warn: {exc}", flush=True)
                        hub_edges = []
                    remain = hub_edges[: max(0, int(max_edges))]
                    if remain:
                        print(
                            f"  [swFillet] leftover sequential on {len(remain)} edges ...",
                            flush=True,
                        )
                        for idx, info in enumerate(remain):
                            n_attempted += 1
                            n_sel = _select_edges(model, [info])
                            if n_sel < 1:
                                print(f"    leftover#{idx}: select fail", flush=True)
                                continue
                            if not _insert_fillet(model, r):
                                print(f"    leftover#{idx}: fillet fail", flush=True)
                                continue
                            try:
                                model.EditRebuild3()
                            except Exception:
                                try:
                                    model.ForceRebuild3(False)
                                except Exception:
                                    pass
                            n_ok += 1
                            print(f"    leftover#{idx}: OK (total {n_ok})", flush=True)
                            if (idx + 1) % 4 == 0:
                                try:
                                    hub_edges = _collect_hub_edges(
                                        model,
                                        hub_r_mm=hub_r_mm,
                                        max_len_mm=max_edge_len_mm,
                                    )
                                    remain = hub_edges
                                except Exception:
                                    pass
                else:
                    print("  [swFillet] skip leftover (main-chain-only)", flush=True)
            else:
                take = hub_edges[: max(1, int(max_edges))]
                n_attempted = len(take)
                print(
                    f"  [swFillet] sequential fillet r={r:g} mm on up to {len(take)} edges ...",
                    flush=True,
                )
                for idx, info in enumerate(take):
                    n_sel = _select_edges(model, [info])
                    if n_sel < 1:
                        print(f"    edge#{idx}: select fail", flush=True)
                        continue
                    if not _insert_fillet(model, r):
                        print(f"    edge#{idx}: fillet fail", flush=True)
                        continue
                    try:
                        model.EditRebuild3()
                    except Exception:
                        try:
                            model.ForceRebuild3(False)
                        except Exception:
                            pass
                    n_ok += 1
                    print(f"    edge#{idx}: OK (total {n_ok})", flush=True)

            if n_ok < 1:
                last_err = f"no edge filleted at r={r}"
                continue

            tag = "main" if main_chain_only else "swFillet"
            xt_path = os.path.join(
                out_dir,
                f"{base}_{tag}_r{str(r).replace('.', 'p')}_n{n_ok}.x_t",
            )
            step_out = os.path.join(
                out_dir,
                f"{base}_{tag}_r{str(r).replace('.', 'p')}_n{n_ok}.step",
            )
            try:
                _save_as(model, xt_path)
                _save_as(model, step_out)
            except Exception as exc:
                last_err = f"save failed after fillet r={r}: {exc}"
                continue

            # Readback gate
            mass = None
            topo = None
            try:
                from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
                from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology

                rb = ocp_read_step_shape(step_out)
                topo = ocp_shape_topology(rb, check_brep=True)
                mass = float(ocp_mass(rb))
                if int(topo.get("solids") or 0) != 1 or not bool(topo.get("brep_valid")):
                    last_err = f"STEP invalid after save topo={topo}"
                    print(f"  [swFillet] REJECT: {last_err}", flush=True)
                    continue
                if mass < 50.0:
                    last_err = f"STEP mass too small ({mass:.3f})"
                    print(f"  [swFillet] REJECT: {last_err}", flush=True)
                    continue
            except Exception as exc:
                last_err = f"STEP readback failed: {exc}"
                print(f"  [swFillet] REJECT: {last_err}", flush=True)
                continue

            row.update(
                {
                    "ok": True,
                    "radius_mm": r,
                    "n_edges_filleted": n_ok,
                    "n_edges_attempted": n_attempted,
                    "n_hub_candidates": len(hub_edges),
                    "n_chains": len(chains),
                    "n_whole_chain_ok": n_whole_chain_ok,
                    "mode": mode_used,
                    "main_chain_only": bool(main_chain_only),
                    "xt_path": os.path.abspath(xt_path),
                    "step_path": os.path.abspath(step_out),
                    "mass_mm3": mass,
                    "topology": topo,
                    "error": None,
                }
            )
            print(f"  [swFillet] OK r={r:g} n={n_ok} faces={topo.get('faces')} → {xt_path}", flush=True)
            return row

        raise RuntimeError(last_err or "all fillet radii failed")
    except Exception as exc:
        row["error"] = str(exc)[:500]
        print(f"  [swFillet] FAIL: {exc}", flush=True)
        return row
    finally:
        if model is not None and sw_app is not None:
            try:
                title = _doc_title(model)
                if title:
                    sw_app.CloseDoc(title)
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def main() -> int:
    p = argparse.ArgumentParser(description="SW COM fillet probe on bare hard STEP")
    p.add_argument("--qs", type=float, nargs="+", default=[1.0, 1.5])
    p.add_argument("--r", type=float, nargs="+", default=[0.20, 0.15, 0.10, 0.08, 0.05])
    p.add_argument("--hub-r", type=float, default=4.0)
    p.add_argument("--max-edge-len", type=float, default=3.5)
    p.add_argument("--max-edges", type=int, default=4)
    p.add_argument("--visible", action="store_true", default=True)
    p.add_argument(
        "--step",
        action="append",
        default=None,
        help="Explicit STEP path(s); paired with --qs order if multiple",
    )
    p.add_argument(
        "--chain-targets",
        action="append",
        default=None,
        help="planeChain *_chain_targets.json path(s); paired with --qs/--step",
    )
    p.add_argument(
        "--out-subdir",
        default="_sw_fillet_probe",
        help="Output folder under _hard_cad_delivery",
    )
    p.add_argument(
        "--main-chain-only",
        action="store_true",
        help="Only fillet top plane-chains (no leftover edges)",
    )
    p.add_argument(
        "--max-chains",
        type=int,
        default=2,
        help="With --main-chain-only, keep this many longest chains",
    )
    args = p.parse_args()

    delivery = os.path.join(default_exp_out_dir(), "_hard_cad_delivery")
    out_dir = os.path.join(delivery, str(args.out_subdir))
    os.makedirs(out_dir, exist_ok=True)

    step_map = {
        1.0: os.path.join(delivery, "exp_hardBare_af2q1p0_L20_d2p0_1x1.step"),
        1.5: os.path.join(delivery, "exp_hardBare_af2q1p5_L20_d2p0_1x1.step"),
    }
    chain_map = {
        1.0: os.path.join(
            delivery,
            "_plane_chain_heal",
            "exp_planeChain_af2q1p0_L20_d2p0_1x1_chain_targets.json",
        ),
        1.5: os.path.join(
            delivery,
            "_plane_chain_heal",
            "exp_planeChain_af2q1p5_L20_d2p0_1x1_chain_targets.json",
        ),
    }
    plane_step_map = {
        1.0: os.path.join(
            delivery, "_plane_chain_heal", "exp_planeChain_af2q1p0_L20_d2p0_1x1.step"
        ),
        1.5: os.path.join(
            delivery, "_plane_chain_heal", "exp_planeChain_af2q1p5_L20_d2p0_1x1.step"
        ),
    }

    rows = []
    for i, q in enumerate(args.qs):
        qf = float(q)
        key = min(step_map.keys(), key=lambda k: abs(k - qf))
        if args.step and i < len(args.step):
            step_path = args.step[i]
        else:
            # Prefer healed planeChain STEP when present
            pref = plane_step_map.get(key)
            step_path = pref if pref and os.path.isfile(pref) else step_map[key]
        if abs(key - qf) > 0.05 and not (args.step and i < len(args.step)):
            rows.append({"Q": qf, "ok": False, "error": f"no bare STEP for Q={qf}"})
            continue
        if not os.path.isfile(step_path):
            rows.append({"Q": qf, "ok": False, "error": f"missing {step_path}"})
            continue

        chain_path = None
        if args.chain_targets and i < len(args.chain_targets):
            chain_path = args.chain_targets[i]
        elif os.path.isfile(chain_map.get(key, "")):
            chain_path = chain_map[key]

        print(f"\n######## SW fillet Q={qf:g} ########", flush=True)
        row = fillet_one(
            step_path,
            out_dir=out_dir,
            radii_mm=[float(x) for x in args.r],
            hub_r_mm=float(args.hub_r),
            max_edge_len_mm=float(args.max_edge_len),
            max_edges=int(args.max_edges),
            visible=bool(args.visible),
            chain_targets_path=chain_path,
            main_chain_only=bool(args.main_chain_only),
            max_chains=int(args.max_chains),
        )
        row["Q"] = qf
        rows.append(row)

    summary_path = os.path.join(out_dir, "sw_fillet_probe_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"\nWrote {summary_path}", flush=True)
    wins = [r for r in rows if r.get("ok")]
    print(f"n_wins={len(wins)}/{len(rows)}", flush=True)
    return 0 if wins else 1


if __name__ == "__main__":
    raise SystemExit(main())
