#!/usr/bin/env bash
# Write ready manifest after all fig33_v2_el jobs postpulled (called by fan-out or morning watcher).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

READY="output/logs/fig33_v2_el_ready.json"
POSTPULL="scripts/linux/postpull_paperbox_server.sh"

python3 <<'PY'
import json
from datetime import datetime
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator as G

BASE = "cae_tet0p6mm80_5mmin_paperbox"
items = [
    (1.5, "q15_v2_el", "af2q15"),
    (0.5, "fig33_v2_el", "af2q05"),
    (1.0, "fig33_v2_el", "af2q1"),
    (0.0, "fig33_v2_el", "bcc"),
]
rows = []
for q, suffix, key in items:
    tag = G(cell_size=20, rod_diameter=2, amplitude=2, period_factor=q).variant_name.lower()
    slug = f"hu_bai_{tag}_L20_4x4x4_solid_cad_f_{BASE}_{suffix}"
    rows.append({"Q": q, "key": key, "suffix": suffix, "slug": slug})

from pathlib import Path
root = Path(".")
out = {"structures": [], "all_ready": True, "updated_at": datetime.now().isoformat(timespec="seconds")}

for r in rows:
    slug = r["slug"]
    sta = root / "output/jobs" / slug / f"{slug}.sta"
    csv = root / "output/post" / slug / f"{slug}_stress_strain.csv"
    completed = sta.is_file() and "COMPLETED SUCCESSFULLY" in sta.read_text(encoding="utf-8", errors="ignore")
    entry = {**r, "completed": completed, "csv": str(csv), "csv_ready": csv.is_file()}
    if not entry["csv_ready"]:
        out["all_ready"] = False
    out["structures"].append(entry)

Path("output/logs/fig33_v2_el_ready.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(out, indent=2, ensure_ascii=False))
PY
