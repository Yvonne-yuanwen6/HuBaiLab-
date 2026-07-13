#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from src.comsol.mph_builder import _ensure_comsol_env, _import_mph

mph = Path(sys.argv[1])
comsol_bin = sys.argv[2] if len(sys.argv) > 2 else "/home/art/APP/comsol56/multiphysics/bin/comsol"
_ensure_comsol_env(comsol_bin)
c = _import_mph().start(cores=1)
m = c.load(str(mph))
tops = np.abs(np.array(m.evaluate("pb_top")).ravel())
bases = np.abs(np.array(m.evaluate("pb_base")).ravel())
nz = int((tops > 1e-15).sum())
print(f"pb_top nonzero: {nz}/{tops.size}")
print(f"pb_base[0]={bases[0]:.6g} pb_top[0]={tops[0]:.6g}")
try:
    wplt = float(np.max(np.abs(np.array(m.evaluate("w", "comp1.geom_lat", 2)).ravel())))
    print(f"max|w| plate domain 2: {wplt:.6g} mm")
except Exception as exc:
    print(f"plate w check: {exc}")
c.clear()
print("RESULT: PASS" if nz > 0 else "RESULT: FAIL")
