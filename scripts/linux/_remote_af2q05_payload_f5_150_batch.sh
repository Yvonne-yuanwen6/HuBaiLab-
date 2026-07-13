#!/usr/bin/env bash
# AF2Q0.5 (Q=0.5): same payload sweep as BCC — 0/100/300/500 g, 5–150 Hz step 5.
set -euo pipefail
export Q=0.5
export VARIANT_PREFIX=comsol_fig321_af2q05_444
export VARIANT_LABEL=AF2Q0.5
export CAD=output/cad/verified/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step
export OUT_DIR=output/comsol_jobs/af2q05_payload_composite
export OVERLAY_SLUG=af2q05_p1_f5_150_payload_overlay
export BATCH_LOG=output/logs/af2q05_payload_f5_150_batch.log
export PAPER_OVERLAY=af2q05
exec "$(dirname "$0")/_remote_payload_f5_150_batch.sh"
