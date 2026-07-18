#!/usr/bin/env python3
"""Summarize BCC qs/material probe: KE/IE + early peak / RMSE vs Fig.3.3 BCC."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Digitized Fig.3.3 BCC experiment (same source as other paperbox evaluators).
FIG33 = ROOT / "data" / "hu_bai_fig33_experiment_traced.json"
OUT_JSON = ROOT / "output" / "reports" / "mesh_convergence" / "bcc_qs_material_probe.json"


def _load_energy(path: Path) -> dict:
    rows: list[dict[str, float]] = []
    with path.open(newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            try:
                ie = float(
                    row.get("ALLIE_J")
                    or row.get("ALLIE")
                    or row.get("allie")
                    or 0.0
                )
                ke = float(
                    row.get("ALLKE_J")
                    or row.get("ALLKE")
                    or row.get("allke")
                    or 0.0
                )
                t = float(
                    row.get("time_s")
                    or row.get("time")
                    or row.get("Time")
                    or row.get("t")
                    or 0.0
                )
            except (TypeError, ValueError):
                continue
            ratio = (abs(ke) / ie) if ie > 1.0e-30 else float("nan")
            rows.append({"time": t, "ALLIE": ie, "ALLKE": ke, "ke_ie": ratio})
    if not rows:
        return {"ok": False, "reason": "empty energy csv"}
    ratios = [r["ke_ie"] for r in rows if r["ALLIE"] > 1.0e-9 and math.isfinite(r["ke_ie"])]
    max_ratio = max(ratios) if ratios else float("nan")
    # skip very early noise: after 5% of history length
    n = len(ratios)
    tail = ratios[max(0, int(0.05 * n)) :] if n else []
    max_ratio_tail = max(tail) if tail else max_ratio
    return {
        "ok": True,
        "n": len(rows),
        "max_ke_ie": max_ratio,
        "max_ke_ie_after_5pct": max_ratio_tail,
        "quasi_static_pass": bool(math.isfinite(max_ratio_tail) and max_ratio_tail < 0.05),
    }


def _load_ss(path: Path) -> tuple[list[float], list[float]]:
    eps: list[float] = []
    sig: list[float] = []
    with path.open(newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            keys = {k.lower(): k for k in row}
            ek = keys.get("engineering_strain") or keys.get("strain") or keys.get("eps")
            sk = keys.get("engineering_stress_mpa") or keys.get("stress_mpa") or keys.get("stress")
            if not ek or not sk:
                continue
            try:
                e = float(row[ek])
                s = float(row[sk])
            except (TypeError, ValueError):
                continue
            eps.append(e)
            sig.append(s)
    return eps, sig


def _fig33_bcc() -> tuple[list[float], list[float]]:
    data = json.loads(FIG33.read_text(encoding="utf-8"))
    series = data.get("series") or data.get("curves") or {}
    c = series.get("bcc") or series.get("BCC") or series.get("Q0")
    if c is None:
        raise KeyError(f"BCC curve not found in {FIG33}")
    if "points" in c:
        pts = c["points"]
        return [float(p[0]) for p in pts], [float(p[1]) for p in pts]
    return list(map(float, c["strain"])), list(map(float, c["stress"]))


def _interp(xp: list[float], yp: list[float], x: float) -> float:
    if x <= xp[0]:
        return yp[0]
    if x >= xp[-1]:
        return yp[-1]
    for i in range(1, len(xp)):
        if x <= xp[i]:
            t = (x - xp[i - 1]) / (xp[i] - xp[i - 1] + 1e-30)
            return yp[i - 1] + t * (yp[i] - yp[i - 1])
    return yp[-1]


def _curve_metrics(eps: list[float], sig: list[float], e_ref: list[float], s_ref: list[float]) -> dict:
    if len(eps) < 3:
        return {"ok": False, "reason": "too few stress-strain points"}
    peak_i = max(range(len(sig)), key=lambda i: sig[i])
    # early window for smoke (align with ε<=0.12)
    e_max = min(0.12, max(eps))
    mask = [i for i, e in enumerate(eps) if 0.01 <= e <= e_max]
    rmse = None
    if mask and e_ref:
        errs = []
        for i in mask:
            sr = _interp(e_ref, s_ref, eps[i])
            errs.append((sig[i] - sr) ** 2)
        rmse = math.sqrt(sum(errs) / len(errs))
    # rough early secant stiffness (0.02 → 0.06 if available)
    def _sig_at(target: float) -> float | None:
        for i in range(1, len(eps)):
            if eps[i] >= target:
                return _interp(eps, sig, target)
        return None

    s02, s06 = _sig_at(0.02), _sig_at(0.06)
    secant = None
    if s02 is not None and s06 is not None:
        secant = (s06 - s02) / 0.04
    return {
        "ok": True,
        "n": len(eps),
        "eps_max": max(eps),
        "peak_stress_MPa": sig[peak_i],
        "peak_strain": eps[peak_i],
        "early_rmse_vs_fig33_MPa": rmse,
        "secant_E_02_06_MPa": secant,
    }


def _guess_variant(slug: str) -> str:
    for key in (
        "marlow_noms",
        "nh_noms",
        "marlow_msb1e4",
        "nh_msb1e4",
        "marlow_msu10",
        "nh_msu10",
        "marlow_ms10",
        "nh_ms10",
        "marlow_ms50",
        "nh_ms50",
    ):
        if key in slug:
            return key
    return slug.rsplit("_", 1)[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    ap.add_argument("--slugs", nargs="*", default=[])
    ap.add_argument(
        "--out",
        type=Path,
        default=OUT_JSON,
        help="JSON report path",
    )
    args = ap.parse_args()

    e_ref: list[float] = []
    s_ref: list[float] = []
    if FIG33.is_file():
        try:
            e_ref, s_ref = _fig33_bcc()
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            print(f"WARN Fig.3.3 load failed: {exc}")

    reports: list[dict] = []
    for slug in args.slugs:
        energy_path = ROOT / "output" / "post" / slug / f"{slug}_energy.csv"
        ss_path = ROOT / "output" / "post" / slug / f"{slug}_stress_strain.csv"
        if not ss_path.is_file():
            alt = ROOT / "output" / "post" / slug / f"{slug}_stress_strain_raw.csv"
            ss_path = alt if alt.is_file() else ss_path
        item: dict = {
            "slug": slug,
            "variant": _guess_variant(slug),
            "mode": args.mode,
            "energy": {"ok": False, "reason": "missing"},
            "curve": {"ok": False, "reason": "missing"},
        }
        if energy_path.is_file():
            item["energy"] = _load_energy(energy_path)
        if ss_path.is_file():
            eps, sig = _load_ss(ss_path)
            item["curve"] = _curve_metrics(eps, sig, e_ref, s_ref)
        reports.append(item)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mode": args.mode, "cases": reports}
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))

    # human one-liner table
    print("\n--- summary ---")
    print(f"{'variant':<14} {'KE/IE_max':>10} {'QS<5%':>6} {'peak_MPa':>10} {'early_RMSE':>12}")
    for r in reports:
        en = r["energy"]
        cu = r["curve"]
        ke = en.get("max_ke_ie_after_5pct", float("nan")) if en.get("ok") else float("nan")
        qs = "Y" if en.get("quasi_static_pass") else ("N" if en.get("ok") else "?")
        pk = cu.get("peak_stress_MPa", float("nan")) if cu.get("ok") else float("nan")
        rm = cu.get("early_rmse_vs_fig33_MPa", float("nan")) if cu.get("ok") else float("nan")
        ke_s = f"{ke:.4f}" if isinstance(ke, float) and math.isfinite(ke) else "-"
        pk_s = f"{pk:.4f}" if isinstance(pk, float) and math.isfinite(pk) else "-"
        rm_s = f"{rm:.5f}" if isinstance(rm, float) and math.isfinite(rm) else "-"
        print(f"{r['variant']:<14} {ke_s:>10} {qs:>6} {pk_s:>10} {rm_s:>12}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
