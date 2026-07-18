#!/usr/bin/env bash
# BCC Q=0 full-stroke: Marlow Fig.2.5 stress×0.77 + BELOW MIN dt=1e-4 (ε=0.80).
# Continues after smoke bcc_marlow_ss077_sm12 matched Fig.3.3 early curve + KE/IE OK.
# Short slug required: long descriptive names trigger Abaqus OpenODBFile rfm_FileNoSuchFile.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/APP/abaqus2022/Commands:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="$ROOT"
CPUS="${BCC_QS_PROBE_CPUS:-32}"
SHORT_SLUG="bcc_marlow_ss077_s80"
BASELINE_MESH="output/export/hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox/hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_cae_mesh.inp"
mkdir -p output/logs
exec >> output/logs/bcc_qs_material_probe_ss077_full.log 2>&1
echo "[$(date '+%F %T')] ss077 FULL launcher start (Marlow×0.77, short=$SHORT_SLUG, strain=0.80, cpus=$CPUS)"

rm -rf "output/jobs/${SHORT_SLUG}"

bash scripts/linux/run_paperbox_variant.sh \
  --Q 0 \
  --variant-suffix qs_s80_marlow_msb1e4_ss077 \
  --short-slug "$SHORT_SLUG" \
  --cpus "$CPUS" \
  --memory-mb 262144 \
  --cae-mesh-inp "$BASELINE_MESH" \
  --contact-store-offsets \
  --contact-settle \
  --strain 0.80 \
  --material-model marlow \
  --tpu-stress-scale 0.77 \
  --mass-scaling-mode below_min \
  --mass-scaling-dt 0.0001 \
  --explicit-dt 0.0001 \
  --explicit-dt-mode automatic

echo "[$(date '+%F %T')] ss077 FULL launcher done slug=$SHORT_SLUG"
