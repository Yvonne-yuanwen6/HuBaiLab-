#!/usr/bin/env python3
"""Check mesh_p1 mph has fin identity pairs ap1/ap2 (plate/lattice bonded)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.comsol.mph_builder import _ensure_comsol_env, _import_mph


def main() -> int:
    mph = Path(sys.argv[1])
    comsol_bin = (
        sys.argv[2] if len(sys.argv) > 2 else "/home/art/APP/comsol56/multiphysics/bin/comsol"
    )
    if not mph.is_file():
        print(f"RESULT: FAIL missing {mph}")
        return 1

    _ensure_comsol_env(comsol_bin)
    client = _import_mph().start(cores=1)
    model = client.load(str(mph.resolve()))
    comp = model.java.component("comp1")
    pairs = [str(t) for t in comp.pair().tags()]
    client.clear()

    missing = [t for t in ("ap1", "ap2") if t not in pairs]
    if missing:
        print(f"RESULT: FAIL missing pairs {missing} (have {pairs})")
        return 1
    print(f"RESULT: PASS p1_identity pairs={pairs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
