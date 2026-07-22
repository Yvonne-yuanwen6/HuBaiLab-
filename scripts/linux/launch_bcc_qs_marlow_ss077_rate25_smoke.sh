#!/usr/bin/env bash
# Rate-scaling QS probe (Abaqus GSA: load-rate OR mass scaling).
# Keep msb1e4 + Marlow×0.77; raise plate speed 5→25 mm/min (~5× shorter step time).
# Short slug; reuse C3D4 baseline mesh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
CPUS="${BCC_QS_PROBE_CPUS:-32}"
SHORT_SLUG="bcc_marlow_ss077_r25"
BASELINE_MESH="output/export/hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox/hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_cae_mesh.inp"
mkdir -p output/logs
exec >> output/logs/bcc_qs_marlow_ss077_rate25_smoke.log 2>&1
echo "[$(date '+%F %T')] RATE25 SMOKE start (Marlow×0.77, msb1e4, 25 mm/min, short=$SHORT_SLUG, cpus=$CPUS)"
rm -rf "output/jobs/${SHORT_SLUG}"
bash scripts/linux/run_paperbox_variant.sh \
  --Q 0 \
  --variant-suffix qs_sm12_marlow_msb1e4_ss077_r25 \
  --short-slug "$SHORT_SLUG" \
  --cpus "$CPUS" \
  --memory-mb 262144 \
  --cae-mesh-inp "$BASELINE_MESH" \
  --contact-store-offsets \
  --contact-settle \
  --strain 0.12 \
  --load-rate-mm-min 25 \
  --material-model marlow \
  --tpu-stress-scale 0.77 \
  --mass-scaling-mode below_min \
  --mass-scaling-dt 0.0001 \
  --explicit-dt 0.0001 \
  --explicit-dt-mode automatic
echo "[$(date '+%F %T')] RATE25 SMOKE done slug=$SHORT_SLUG"
