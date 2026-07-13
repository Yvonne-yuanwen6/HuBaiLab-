#!/usr/bin/env python3
"""Inspect freq excitation setup and nonzero displacement after quick solve."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.hu_bai_settings import HuBaiComsolSettings
from src.comsol.mph_builder import _ensure_comsol_env, _import_mph, build_mph_from_step


def _json_safe(value: object) -> object:
    """Convert COMSOL/Java values for json.dumps."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if hasattr(value, "__class__") and "java.lang" in str(type(value)):
        return str(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)

    out: dict = {"tag": tag, "present": False}
    tags = [str(t) for t in solid.feature().tags()]
    if tag not in tags:
        return out
    feat = solid.feature(tag)
    out["present"] = True
    out["type"] = str(feat.getType())
    try:
        ents = feat.selection().entities()
        n = int(ents.length) if hasattr(ents, "length") else len(ents)
        out["selection_n"] = n
        if n and n <= 8:
            out["selection_entities"] = [int(ents[i]) for i in range(n)]
    except Exception as exc:
        out["selection_err"] = str(exc)
    for prop in ("Ftot", "U0", "harmonicPerturbation"):
        try:
            out[prop] = list(feat.getStringArray(prop))
        except Exception:
            try:
                out[prop] = str(feat.getString(prop))
            except Exception:
                pass
    return out


def probe_model(
    mph_path: Path,
    settings: HuBaiComsolSettings,
    *,
    comsol_bin: str | None = None,
    solve: bool = False,
    plist: str = "10,30,68",
) -> dict:
    _ensure_comsol_env(comsol_bin)
    client = _import_mph().start(cores=2)
    model = client.load(str(mph_path.resolve()))
    java = model.java
    solid = java.component("comp1").physics("solid")

    report: dict = {
        "mph": str(mph_path.resolve()),
        "slug": settings.default_slug(),
        "A_base_m_s2": settings.base_acceleration_m_s2,
        "excitation_axis": settings.excitation_axis,
        "excitation_type": settings.excitation_type,
        "features": {
            "base_exc": _feature_summary(solid, "base_exc"),
            "fixbase": _feature_summary(solid, "fixbase"),
            "free1": _feature_summary(solid, "free1"),
        },
    }

    try:
        report["A_base_param"] = float(java.param().evaluate("A_base"))
    except Exception as exc:
        report["A_base_param_err"] = str(exc)

    if settings.study_freq_tag in [str(t) for t in java.study().tags()]:
        freq = java.study(settings.study_freq_tag).feature(settings.freq_feature_tag)
        activate: dict[str, bool | str] = {}
        for path in (
            "solid.fixbase",
            "solid.base_exc",
            "solid.free1",
            "solid.lemm_lattice",
            "solid.lemm_fixture",
        ):
            try:
                activate[path] = bool(freq.activate(path))
            except Exception as exc:
                activate[path] = str(exc)
        report["freq_study_activate"] = activate
        try:
            report["freq_plist"] = str(freq.getString("plist"))
        except Exception:
            pass

    if solve:
        freq = java.study(settings.study_freq_tag).feature(settings.freq_feature_tag)
        freq.set("plist", plist)
        try:
            java.sol().remove("sol1")
        except Exception:
            pass
        java.study(settings.study_freq_tag).createAutoSequences("all")
        java.study(settings.study_freq_tag).run()
        solved = mph_path.parent / f"{settings.default_slug()}_excitation_probe_solved.mph"
        model.save(str(solved))
        report["solved_mph"] = str(solved)

        freqs = np.array(model.evaluate("freq")).ravel()
        points: list[dict] = []
        ok = False
        for i in range(1, len(freqs) + 1):
            w = np.array(model.evaluate("w", inner=[i]))
            acc_expr = settings.excitation_acceleration_expr
            try:
                a = np.array(model.evaluate(acc_expr, inner=[i]))
                amax = float(np.max(np.abs(a)))
            except Exception:
                amax = float("nan")
            wmax = float(np.max(np.abs(w)))
            ok = ok or wmax > 0
            points.append(
                {
                    "solnum": i,
                    "freq_Hz": float(freqs[i - 1]),
                    "w_max_mm": wmax,
                    "acc_max_m_s2": amax,
                }
            )
        report["solve_points"] = points
        report["nonzero_response"] = ok

    client.remove(model)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe COMSOL freq excitation + quick solve.")
    parser.add_argument("--cad", default="", help="Rebuild from STEP if --build")
    parser.add_argument("--mph", default="", help="Existing .mph to probe")
    parser.add_argument("--slug", default="comsol_fig321_bcc_444_freq")
    parser.add_argument("--build", action="store_true", help="Build fresh mph before probe")
    parser.add_argument("--solve", action="store_true", help="Quick-solve plist and check |w|")
    parser.add_argument("--plist", default="10,30,68")
    parser.add_argument("--comsol-bin", default="")
    parser.add_argument("--out-json", default="")
    args = parser.parse_args(argv)

    settings = HuBaiComsolSettings(
        slug=args.slug,
        run_eigen=False,
        run_frequency=True,
        excitation_axis="z",
        base_acceleration_m_s2=0.98,
        include_top_payload=False,
        freq_min_hz=10.0,
        freq_max_hz=68.0,
        freq_step_hz=58.0,
    )

    if args.build:
        cad = Path(args.cad or ROOT / "output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step")
        mph_path = build_mph_from_step(settings, cad, comsol_bin=args.comsol_bin or None, cores=2)
    else:
        mph_path = Path(
            args.mph or settings.job_dir() / f"{settings.default_slug()}.mph"
        ).resolve()

    report = probe_model(
        mph_path,
        settings,
        comsol_bin=args.comsol_bin or None,
        solve=args.solve,
        plist=args.plist,
    )

    out_json = Path(args.out_json) if args.out_json else mph_path.parent / f"{args.slug}_excitation_probe.json"
    out_json.write_text(
        json.dumps(_json_safe(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(_json_safe(report), indent=2, ensure_ascii=False))
    print(f"\nSaved: {out_json}")
    if report.get("nonzero_response") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
