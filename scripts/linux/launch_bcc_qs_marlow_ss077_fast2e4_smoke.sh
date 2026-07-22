#!/usr/bin/env bash
# Mid-fast QS probe: BELOW MIN dt=2e-4 (~2× vs msb1e4; softer than failed 5e-4).
# Keep Marlow×0.77, C3D4, STORE OFFSETS + ContactSettle, 5 mm/min.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
CPUS="${BCC_QS_PROBE_CPUS:-32}"
SHORT_SLUG="bcc_marlow_ss077_f2e4"
BASELINE_MESH="output/export/hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox/hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_cae_mesh.inp"
mkdir -p output/logs
exec >> output/logs/bcc_qs_marlow_ss077_fast2e4_smoke.log 2>&1
echo "[$(date '+%F %T')] FAST msb2e4 SMOKE start (Marlow×0.77, dt=2e-4, short=$SHORT_SLUG, cpus=$CPUS)"
rm -rf "output/jobs/${SHORT_SLUG}"
bash scripts/linux/run_paperbox_variant.sh \
  --Q 0 \
  --variant-suffix qs_sm12_marlow_msb2e4_ss077 \
  --short-slug "$SHORT_SLUG" \
  --cpus "$CPUS" \
  --memory-mb 262144 \
  --cae-mesh-inp "$BASELINE_MESH" \
  --contact-store-offsets \
  --contact-settle \
  --strain 0.12 \
  --material-model marlow \
  --tpu-stress-scale 0.77 \
  --mass-scaling-mode below_min \
  --mass-scaling-dt 0.0002 \
  --explicit-dt 0.0002 \
  --explicit-dt-mode automatic
echo "[$(date '+%F %T')] FAST msb2e4 SMOKE done slug=$SHORT_SLUG"
