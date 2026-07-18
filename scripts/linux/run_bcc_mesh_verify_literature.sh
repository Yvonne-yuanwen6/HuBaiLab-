#!/usr/bin/env bash
# Run Abaqus ANALYSIS_CHECKS Mesh Verify on BCC meshseed cases; rebuild Table 2.1 xlsx.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
mkdir -p output/reports/mesh_convergence/verify_analysis_checks output/logs

LOG=output/logs/bcc_mesh_verify_analysis_checks.log
exec > >(tee -a "$LOG") 2>&1

echo "=== ANALYSIS_CHECKS verify $(date) ==="

python3 <<'PY'
import json
from pathlib import Path

ROOT = Path('.').resolve()
levels = [
    ("0.6", "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"),
    ("0.8", "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_08"),
    ("1.0", "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_10"),
    ("1.2", "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_meshseed_12"),
]
jobs = []
for seed, slug in levels:
    export = ROOT / "output" / "export" / slug
    mesh = export / f"{slug}_cae_mesh.inp"
    full = export / f"{slug}.inp"
    # Prefer CAE mesh-only INP (lattice), else compression INP
    inp = mesh if mesh.is_file() else full
    out = ROOT / "output" / "reports" / "mesh_convergence" / "verify_analysis_checks" / f"{slug}.json"
    jobs.append({"seed": seed, "slug": slug, "inp": str(inp), "out": str(out)})
    print("JOB", seed, inp, "exists" if Path(inp).is_file() else "MISSING")
(Path("output/reports/mesh_convergence/verify_analysis_checks") / "jobs.json").write_text(
    json.dumps(jobs, indent=2), encoding="utf-8"
)
PY

JOBS_JSON=output/reports/mesh_convergence/verify_analysis_checks/jobs.json
n=$(python3 -c "import json; print(len(json.load(open('$JOBS_JSON'))))")
for i in $(seq 0 $((n-1))); do
  seed=$(python3 -c "import json; print(json.load(open('$JOBS_JSON'))[$i]['seed'])")
  inp=$(python3 -c "import json; print(json.load(open('$JOBS_JSON'))[$i]['inp'])")
  out=$(python3 -c "import json; print(json.load(open('$JOBS_JSON'))[$i]['out'])")
  echo "--- verify seed=$seed ---"
  if [[ ! -f "$inp" ]]; then
    echo "SKIP missing $inp"
    continue
  fi
  export HU_BAI_MESH_INP="$ROOT/$inp"
  # paths from jobs.json may already be absolute
  if [[ "$inp" = /* ]]; then export HU_BAI_MESH_INP="$inp"; fi
  if [[ "$out" = /* ]]; then export HU_BAI_OUT_JSON="$out"; else export HU_BAI_OUT_JSON="$ROOT/$out"; fi
  abq cae noGUI=scripts/abaqus_mesh_verify_analysis_checks.py || echo "WARN verify failed seed=$seed"
done

echo "=== assemble literature table JSON $(date) ==="
python3 <<'PY'
import json, re
from pathlib import Path

ROOT = Path('.').resolve()
jobs = json.loads((ROOT/"output/reports/mesh_convergence/verify_analysis_checks/jobs.json").read_text(encoding="utf-8"))
# prior summary has wall times
old = {}
oldp = ROOT/"output/reports/mesh_convergence/bcc_mesh_quality_summary.json"
if oldp.is_file():
    for r in json.loads(oldp.read_text(encoding="utf-8")):
        old[str(r["mesh_size_mm"])] = r

rows = []
for j in jobs:
    seed = j["seed"]
    slug = j["slug"]
    vp = Path(j["out"])
    if not vp.is_file():
        print("missing verify", vp)
        continue
    v = json.loads(vp.read_text(encoding="utf-8"))
    o = old.get(seed, {})
    n = int(v.get("numElements") or 0)
    w = int(v.get("warningElements") or 0)
    rows.append({
        "mesh_size_mm": float(seed),
        "total_number_of_meshes": n,
        "warning_meshes": w,
        "warning_pct": (100.0 * w / n) if n else 0.0,
        "failed_elements": int(v.get("failedElements") or 0),
        "cpu_time_s": o.get("wall_time_s"),  # literature column: calc time; use wall
        "wall_time": o.get("wall_time"),
        "criterion": "ANALYSIS_CHECKS",
        "slug": slug,
        "source_json": str(vp),
    })

out = ROOT/"output/reports/mesh_convergence/bcc_mesh_quality_literature.json"
out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
print(json.dumps(rows, indent=2))
print("WROTE", out)
PY

echo "=== done $(date) ==="
